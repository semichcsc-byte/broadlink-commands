"""Button entities, one per learned command."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BroadlinkConfigEntry, BroadlinkRuntime, device as bl
from .const import CODE_TYPE_RF, CONF_AREA_ID, CONF_CODE, CONF_CODE_TYPE, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BroadlinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    _prune_removed_commands(hass, entry)

    # Deliberately not passing config_subentry_id: every button hangs off the one
    # physical remote, and a device can only belong to a single subentry, so
    # tagging them would make each new command steal the device from the last.
    async_add_entities(
        BroadlinkCommandButton(entry, subentry)
        for subentry in entry.subentries.values()
    )


def _prune_removed_commands(hass: HomeAssistant, entry: BroadlinkConfigEntry) -> None:
    """Drop registry entries for commands that no longer exist.

    Home Assistant cleans up entities owned by a subentry automatically; ours are
    not, so deleting a command would otherwise leave its button behind.
    """
    registry = er.async_get(hass)
    live = set(entry.subentries)
    for record in er.async_entries_for_config_entry(registry, entry.entry_id):
        if record.unique_id not in live:
            _LOGGER.debug("Removing %s, its command is gone", record.entity_id)
            registry.async_remove(record.entity_id)


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
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)}
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
