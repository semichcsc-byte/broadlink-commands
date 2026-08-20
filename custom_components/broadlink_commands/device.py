"""Blocking helpers around the broadlink library.

Every function here talks to the device over UDP and must be run in an executor.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import broadlink
from broadlink.exceptions import BroadlinkException, ReadError, StorageError

from .const import (
    DISCOVERY_TIMEOUT,
    LEARN_TIMEOUT,
    POLL_INTERVAL,
    SWEEP_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

# Only these can learn; plain switches and sensors would just confuse the picker.
_LEARNING_TYPES = ("rmmini", "rmpro", "rm4mini", "rm4pro")


class LearnTimeout(Exception):
    """Nothing was captured before the timeout."""


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
    return _describe(device)


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
    device.auth()
    _unlock(device)
    return device


def _unlock(device: Any) -> None:
    """Clear the Broadlink app's lock, which blocks learning and sending.

    gendevice cannot know the lock state, so it has to be read off the device.
    hello() also fills in the name, which set_lock writes back - without it the
    device would be renamed to an empty string.
    """
    try:
        device.hello()
        if not device.is_locked:
            return
        device.set_lock(False)
        _LOGGER.warning("%s was locked by the Broadlink app; unlocked it", device.host[0])
    except (OSError, BroadlinkException):
        _LOGGER.warning("Could not check or clear the lock on %s", device.host[0])


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


def send(device: Any, code: str, repeats: int = 0) -> None:
    """Replay a stored code.

    Byte 1 of the packet is how many extra times the device retransmits it back
    to back. Some receivers - fan motors especially - ignore a lone frame,
    because a real remote repeats it for as long as the button is held.
    """
    data = bytearray.fromhex(code)
    if repeats:
        data[1] = min(repeats, 0xFF)
    device.send_data(bytes(data))
