"""Blocking helpers around the broadlink library.

Network operations talk to the device over UDP and must run in an executor.
"""

from __future__ import annotations

import time
from typing import Any

import broadlink
from broadlink.exceptions import ReadError, StorageError

from .const import (
    DISCOVERY_TIMEOUT,
    LEARN_TIMEOUT,
    POLL_INTERVAL,
    SWEEP_TIMEOUT,
)

# Only these can learn; plain switches and sensors would just confuse the picker.
_LEARNING_TYPES = ("RMMINI", "RMPRO", "RM4MINI", "RM4PRO")
_RF_TYPES = ("RMPRO", "RM4PRO")


class LearnTimeout(Exception):
    """Nothing was captured before the timeout."""


class DeviceLocked(Exception):
    """The device must be unlocked by the user in the Broadlink app."""


class UnsupportedDevice(Exception):
    """The device cannot learn remote control commands."""


def discover(timeout: int = DISCOVERY_TIMEOUT, target: str | None = None) -> list[dict[str, Any]]:
    """Find learning-capable Broadlink devices on the network."""
    kwargs: dict[str, Any] = {"timeout": timeout}
    if target:
        kwargs["discover_ip_address"] = target

    found = []
    for device in broadlink.discover(**kwargs):
        if device.type not in _LEARNING_TYPES:
            continue
        found.append(_describe(device))
    return found


def identify(host: str) -> dict[str, Any]:
    """Look up a single device by address, for when discovery cannot reach it."""
    device = broadlink.hello(host, timeout=DISCOVERY_TIMEOUT)
    if device.type not in _LEARNING_TYPES:
        raise UnsupportedDevice(f"{device.type} cannot learn remote control commands")
    return _describe(device)


def supports_rf(host: str, mac: str, devtype: int) -> bool:
    """Determine RF support locally, including for entries saved without a type."""
    device = broadlink.gendevice(devtype, (host, 80), bytes.fromhex(mac))
    return device.type in _RF_TYPES


def _describe(device: Any) -> dict[str, Any]:
    return {
        "host": device.host[0],
        "mac": device.mac.hex(),
        "devtype": device.devtype,
        "model": f"{device.manufacturer} {device.model}".strip(),
        "type": device.type,
    }


def connect(host: str, mac: str, devtype: int) -> Any:
    """Build an authenticated device handle."""
    device = broadlink.gendevice(devtype, (host, 80), bytes.fromhex(mac))
    # gendevice does not know the lock state until hello queries the device.
    device.hello()
    if device.is_locked:
        raise DeviceLocked(
            "The Broadlink device is locked. Unlock it in the Broadlink app "
            "and try again."
        )
    device.auth()
    return device


def learn_ir(device: Any) -> str:
    """Capture one IR code."""
    device.enter_learning()
    return _await_data(device)


def sweep_rf(device: Any) -> float:
    """Lock onto the remote's frequency. The button must be held down."""
    device.sweep_frequency()
    deadline = time.monotonic() + SWEEP_TIMEOUT
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)
        is_found, frequency = device.check_frequency()
        if is_found:
            return frequency
    device.cancel_sweep_frequency()
    raise LearnTimeout("No RF frequency found")


def learn_rf(device: Any, frequency: float | None = None) -> str:
    """Capture one RF code.

    With a frequency the device listens on it directly, so the sweep - and the
    press-and-hold it requires - can be skipped entirely.
    """
    device.find_rf_packet(frequency)
    return _await_data(device)


def _await_data(device: Any) -> str:
    deadline = time.monotonic() + LEARN_TIMEOUT
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)
        try:
            data = device.check_data()
        except (ReadError, StorageError):
            continue
        return data.hex()
    raise LearnTimeout("No code received")


def send(device: Any, code: str) -> None:
    """Replay a stored code."""
    device.send_data(bytes.fromhex(code))
