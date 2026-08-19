"""Button entities, one per learned command."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BroadlinkConfigEntry, BroadlinkRuntime, device as bl
from .const import CODE_TYPE_RF, CONF_AREA_ID, CONF_CODE, CONF_CODE_TYPE, CONF_MODEL, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BroadlinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for subentry in entry.subentries.values():
        async_add_entities(
            [BroadlinkCommandButton(entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class BroadlinkCommandButton(ButtonEntity):
    """Replays one learned code."""

    _attr_has_entity_name = True

    def __init__(self, entry: BroadlinkConfigEntry, subentry: ConfigSubentry) -> None:
        self._runtime: BroadlinkRuntime = entry.runtime_data
        self._code: str = subentry.data[CONF_CODE]
        self._area_id: str | None = subentry.data.get(CONF_AREA_ID)
        self._attr_name = subentry.title
        self._attr_unique_id = subentry.subentry_id
        self._attr_icon = (
            "mdi:remote" if subentry.data.get(CONF_CODE_TYPE) == CODE_TYPE_RF else "mdi:remote-tv"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=entry.title,
            manufacturer="Broadlink",
            model=entry.data.get(CONF_MODEL),
            connections={(CONNECTION_NETWORK_MAC, format_mac(self._runtime.mac))},
        )

    async def async_added_to_hass(self) -> None:
        """Honour the area chosen while learning, which the device does not supply."""
        await super().async_added_to_hass()
        if not self._area_id:
            return
        registry = er.async_get(self.hass)
        entry = registry.async_get(self.entity_id)
        if entry is not None and entry.area_id is None:
            registry.async_update_entity(self.entity_id, area_id=self._area_id)

    async def async_press(self) -> None:
        try:
            device = await self.hass.async_add_executor_job(self._runtime.connect)
            await self.hass.async_add_executor_job(bl.send, device, self._code)
        except OSError as err:
            raise HomeAssistantError(
                f"Could not reach {self._runtime.host}: {err}"
            ) from err
