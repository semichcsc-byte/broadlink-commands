"""The Broadlink Commands integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from . import device as bl
from .const import CONF_DEVTYPE, CONF_HOST, CONF_MAC

PLATFORMS = [Platform.BUTTON]

type BroadlinkConfigEntry = ConfigEntry[BroadlinkRuntime]


@dataclass
class BroadlinkRuntime:
    """What the platforms need at runtime."""

    host: str
    mac: str
    devtype: int

    def connect(self) -> Any:
        """Authenticate fresh; sessions expire and the device may have rebooted."""
        return bl.connect(self.host, self.mac, self.devtype)


async def async_setup_entry(hass: HomeAssistant, entry: BroadlinkConfigEntry) -> bool:
    runtime = BroadlinkRuntime(
        host=entry.data[CONF_HOST],
        mac=entry.data[CONF_MAC],
        devtype=entry.data[CONF_DEVTYPE],
    )

    try:
        await hass.async_add_executor_job(runtime.connect)
    except OSError as err:
        raise ConfigEntryNotReady(f"Cannot reach {runtime.host}") from err

    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BroadlinkConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: BroadlinkConfigEntry) -> None:
    """Adding or removing a command changes which buttons should exist."""
    await hass.config_entries.async_reload(entry.entry_id)
