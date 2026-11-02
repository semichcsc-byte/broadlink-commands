"""Asynchronous helpers around the python-broadlink library.

Network operations talk to the device over UDP without blocking the event loop.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from inspect import iscoroutinefunction
from typing import Any

import broadlink
from broadlink.device import Device
from broadlink.exceptions import ReadError, StorageError
from broadlink.remote import rmmini, rmpro

from .const import (
    DISCOVERY_TIMEOUT,
    LEARN_TIMEOUT,
    LIBRARY_RECOVERY_URL,
    POLL_INTERVAL,
    SWEEP_TIMEOUT,
)

# Only these can learn; plain switches and sensors would just confuse the picker.
_LEARNING_TYPES = ("RMMINI", "RMMINIB", "RMPRO", "RM4MINI", "RM4PRO")
_RF_TYPES = ("RMPRO", "RM4PRO")


class LearnTimeout(Exception):
    """Nothing was captured before the timeout."""


class DeviceLocked(Exception):
    """The device must be unlocked by the user in the Broadlink app."""


class UnsupportedDevice(Exception):
    """The device cannot learn remote control commands."""


class IncompatibleLibrary(Exception):
    """The loaded module does not provide the required asynchronous API."""


def check_library() -> None:
    """Check the loaded code, not just metadata from overlapping distributions."""
    required_api = (
        (broadlink, "discover"),
        (broadlink, "hello"),
        (Device, "hello"),
        (Device, "auth"),
        (Device, "aclose"),
        (rmmini, "enter_learning"),
        (rmmini, "check_data"),
        (rmmini, "send_data"),
        (rmpro, "sweep_frequency"),
        (rmpro, "check_frequency"),
        (rmpro, "cancel_sweep_frequency"),
        (rmpro, "find_rf_packet"),
    )
    if not all(
        iscoroutinefunction(getattr(owner, name, None))
        for owner, name in required_api
    ):
        raise IncompatibleLibrary(
            f"Incompatible Broadlink code loaded from {broadlink.__file__}. "
            "Broadlink Commands requires asynchronous python-broadlink>=1.0.6. "
            f"Repair the dependency and restart Home Assistant: {LIBRARY_RECOVERY_URL}"
        )


async def discover(timeout: int = DISCOVERY_TIMEOUT, target: str | None = None) -> list[dict[str, Any]]:
    """Find learning-capable Broadlink devices on the network."""
    check_library()
    kwargs: dict[str, Any] = {"timeout": timeout}
    if target:
        kwargs["discover_ip_address"] = target

    found = []
    for device in await broadlink.discover(**kwargs):
        if device.type not in _LEARNING_TYPES:
            continue
        found.append(_describe(device))
    return found


async def identify(host: str) -> dict[str, Any]:
    """Look up a single device by address, for when discovery cannot reach it."""
    check_library()
    async with aclosing(
        await broadlink.hello(host, timeout=DISCOVERY_TIMEOUT)
    ) as device:
        if device.type not in _LEARNING_TYPES:
            raise UnsupportedDevice(f"{device.type} cannot learn remote control commands")
        return _describe(device)


def supports_rf(host: str, mac: str, devtype: int) -> bool:
    """Determine RF support locally, including for entries saved without a type."""
    check_library()
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


@asynccontextmanager
async def connect(host: str, mac: str, devtype: int) -> AsyncIterator[Device]:
    """Authenticate a device and close its endpoint when the operation finishes."""
    check_library()
    async with aclosing(
        broadlink.gendevice(devtype, (host, 80), bytes.fromhex(mac))
    ) as device:
        # gendevice does not know the lock state until hello queries the device.
        await device.hello()
        if device.is_locked:
            raise DeviceLocked(
                "The Broadlink device is locked. Unlock it in the Broadlink app "
                "and try again."
            )
        await device.auth()
        yield device


async def learn_ir(device: Any) -> str:
    """Capture one IR code."""
    await device.enter_learning()
    return await _await_data(device)


async def sweep_rf(device: Any) -> float:
    """Lock onto the remote's frequency. The button must be held down."""
    await device.sweep_frequency()
    deadline = time.monotonic() + SWEEP_TIMEOUT
    while time.monotonic() < deadline:
        await asyncio.sleep(POLL_INTERVAL)
        is_found, frequency = await device.check_frequency()
        if is_found:
            return frequency
    await device.cancel_sweep_frequency()
    raise LearnTimeout("No RF frequency found")


async def learn_rf(device: Any, frequency: float | None = None) -> str:
    """Capture one RF code.

    With a frequency the device listens on it directly, so the sweep - and the
    press-and-hold it requires - can be skipped entirely.
    """
    await device.find_rf_packet(frequency)
    return await _await_data(device)


async def _await_data(device: Any) -> str:
    deadline = time.monotonic() + LEARN_TIMEOUT
    while time.monotonic() < deadline:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            data = await device.check_data()
        except (ReadError, StorageError):
            continue
        return data.hex()
    raise LearnTimeout("No code received")


async def send(device: Any, code: str) -> None:
    """Replay a stored code."""
    await device.send_data(bytes.fromhex(code))
