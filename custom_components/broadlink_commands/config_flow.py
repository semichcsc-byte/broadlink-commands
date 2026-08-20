"""Config and subentry flows for Broadlink Commands."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector

from . import device as bl
from .const import (
    CODE_TYPE_IR,
    CODE_TYPE_RF,
    CONF_AREA_ID,
    CONF_CODE,
    CONF_CODE_TYPE,
    CONF_DEVTYPE,
    CONF_FREQUENCY,
    CONF_HOST,
    CONF_MAC,
    CONF_MODEL,
    CONF_RELEARN,
    CONF_REPEATS,
    CONF_TEST,
    DOMAIN,
    MAX_REPEATS,
    SUBENTRY_TYPE_COMMAND,
)

_LOGGER = logging.getLogger(__name__)

MANUAL = "manual"

REPEATS = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0, max=MAX_REPEATS, step=1, mode=selector.NumberSelectorMode.BOX
    )
)

FREQUENCY = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=300,
        max=1000,
        step=0.01,
        mode=selector.NumberSelectorMode.BOX,
        unit_of_measurement="MHz",
    )
)


def _repeats(data: dict[str, Any]) -> int:
    return int(data.get(CONF_REPEATS) or 0)


def _frequency(data: dict[str, Any]) -> float | None:
    value = data.get(CONF_FREQUENCY)
    return float(value) if value else None


class BroadlinkCommandsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Find a Broadlink device and set it up."""

    VERSION = 1

    def __init__(self) -> None:
        self._devices: dict[str, dict[str, Any]] = {}

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TYPE_COMMAND: CommandSubentryFlowHandler}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            if user_input[CONF_HOST] == MANUAL:
                return await self.async_step_manual()
            return await self._create(self._devices[user_input[CONF_HOST]])

        try:
            devices = await self.hass.async_add_executor_job(bl.discover)
        except OSError:
            _LOGGER.exception("Discovery failed")
            devices = []

        self._devices = {d["mac"]: d for d in devices}
        options = [
            selector.SelectOptionDict(
                value=mac, label=f"{d['model']} ({d['host']})"
            )
            for mac, d in self._devices.items()
        ]
        options.append(
            selector.SelectOptionDict(value=MANUAL, label="Enter an address manually")
        )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    )
                }
            ),
            description_placeholders={"count": str(len(self._devices))},
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Broadcast discovery does not cross VLANs; this does."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await self.hass.async_add_executor_job(
                    bl.identify, user_input[CONF_HOST]
                )
            except OSError:
                errors["base"] = "cannot_connect"
            else:
                return await self._create(info)

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def _create(self, info: dict[str, Any]) -> ConfigFlowResult:
        await self.async_set_unique_id(info["mac"])
        self._abort_if_unique_id_configured(updates={CONF_HOST: info["host"]})

        try:
            await self.hass.async_add_executor_job(
                bl.connect, info["host"], info["mac"], info["devtype"]
            )
        except OSError:
            return self.async_abort(reason="cannot_connect")

        return self.async_create_entry(
            title=info["model"],
            data={
                CONF_HOST: info["host"],
                CONF_MAC: info["mac"],
                CONF_DEVTYPE: info["devtype"],
                CONF_MODEL: info["model"],
            },
        )


class CommandSubentryFlowHandler(ConfigSubentryFlow):
    """Learn one command and turn it into a button."""

    def __init__(self) -> None:
        self._code: str | None = None
        self._code_type: str | None = None
        self._task: asyncio.Task | None = None
        # The RF sweep and the packet capture must use the same authenticated handle.
        self._device_handle: Any = None
        self._frequency: float | None = None
        self._swept: bool = False
        self._reconfiguring: bool = False
        self._pending: dict[str, Any] | None = None

    @property
    def _entry(self) -> ConfigEntry:
        return self._get_entry()

    def _known_frequency(self) -> float | None:
        """Frequency learned previously, so the sweep can be skipped.

        Kept on the subentries rather than the config entry: writing to the entry
        mid-flow would trigger a reload while the flow is still running.
        """
        for subentry in reversed(list(self._entry.subentries.values())):
            frequency = subentry.data.get(CONF_FREQUENCY)
            if frequency:
                return float(frequency)
        return None

    async def _device(self) -> Any:
        data = self._entry.data
        return await self.hass.async_add_executor_job(
            bl.connect, data[CONF_HOST], data[CONF_MAC], data[CONF_DEVTYPE]
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=["learn_ir", "learn_rf"]
        )

    # --- Editing an existing command ---------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Rename, move, or recapture a command without replacing its entity."""
        subentry = self._get_reconfigure_subentry()
        self._reconfiguring = True

        if user_input is not None:
            if user_input.get(CONF_RELEARN):
                # Keep the name and area; only the code is being replaced. A
                # cleared frequency means sweep for it again.
                self._pending = user_input
                self._frequency = _frequency(user_input)
                return await self.async_step_user()
            return self._save(user_input, subentry)

        # Carried over so a rename does not discard the code already captured.
        self._code = subentry.data[CONF_CODE]
        self._code_type = subentry.data.get(CONF_CODE_TYPE)
        self._frequency = subentry.data.get(CONF_FREQUENCY)

        area_id = subentry.data.get(CONF_AREA_ID)
        area_field = (
            vol.Optional(CONF_AREA_ID, default=area_id)
            if area_id
            else vol.Optional(CONF_AREA_ID)
        )
        fields: dict[Any, Any] = {
            vol.Required("name", default=subentry.title): str,
            area_field: selector.AreaSelector(),
            vol.Optional(CONF_REPEATS, default=_repeats(subentry.data)): REPEATS,
        }
        # Only worth showing once a command exists and turns out not to work.
        if self._code_type == CODE_TYPE_RF:
            frequency_field = (
                vol.Optional(CONF_FREQUENCY, default=self._frequency)
                if self._frequency
                else vol.Optional(CONF_FREQUENCY)
            )
            fields[frequency_field] = FREQUENCY
        fields[vol.Optional(CONF_RELEARN, default=False)] = bool

        return self.async_show_form(
            step_id="reconfigure", data_schema=vol.Schema(fields)
        )

    def _save(
        self, user_input: dict[str, Any], subentry: ConfigSubentry
    ) -> SubentryFlowResult:
        if CONF_FREQUENCY in user_input:
            self._frequency = _frequency(user_input)
        area_id = user_input.get(CONF_AREA_ID)
        self._apply_area(subentry.subentry_id, area_id)
        return self.async_update_and_abort(
            self._entry,
            subentry,
            title=user_input["name"],
            data={
                CONF_CODE: self._code,
                CONF_CODE_TYPE: self._code_type,
                CONF_AREA_ID: area_id,
                CONF_FREQUENCY: self._frequency,
                CONF_REPEATS: _repeats(user_input),
            },
        )

    def _apply_area(self, subentry_id: str, area_id: str | None) -> None:
        """The entity keeps its own area, so changing it here has to be explicit."""
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(BUTTON_DOMAIN, DOMAIN, subentry_id)
        if entity_id:
            registry.async_update_entity(entity_id, area_id=area_id)

    # --- IR: one press is enough -------------------------------------------------

    async def async_step_learn_ir(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if self._task is None:
            self._code_type = CODE_TYPE_IR
            self._task = self.hass.async_create_task(self._learn_ir())

        if not self._task.done():
            return self.async_show_progress(
                step_id="learn_ir",
                progress_action="learn_ir",
                progress_task=self._task,
            )

        return self._finish_task()

    async def _learn_ir(self) -> str:
        device = await self._device()
        return await self.hass.async_add_executor_job(bl.learn_ir, device)

    # --- RF: sweep for the frequency, then capture the packet --------------------

    async def async_step_learn_rf(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Skip the sweep when this device already found a frequency."""
        self._code_type = CODE_TYPE_RF
        if self._frequency is None and not self._reconfiguring:
            self._frequency = self._known_frequency()
        if self._frequency is not None:
            self._device_handle = await self._device()
            return await self.async_step_press_rf()
        return await self.async_step_hold_rf()

    async def async_step_hold_rf(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if self._task is None:
            self._code_type = CODE_TYPE_RF
            self._swept = True
            self._task = self.hass.async_create_task(self._sweep_rf())

        if not self._task.done():
            return self.async_show_progress(
                step_id="hold_rf",
                progress_action="hold_rf",
                progress_task=self._task,
            )

        try:
            self._device_handle, self._frequency = self._task.result()
        except (OSError, bl.LearnTimeout):
            self._task = None
            return self.async_show_progress_done(next_step_id="failed")

        self._task = None
        return self.async_show_progress_done(next_step_id="press_rf")

    async def _sweep_rf(self) -> tuple[Any, float]:
        device = await self._device()
        frequency = await self.hass.async_add_executor_job(bl.sweep_rf, device)
        return device, frequency

    async def async_step_press_rf(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if self._task is None:
            self._task = self.hass.async_create_task(self._learn_rf())

        if not self._task.done():
            return self.async_show_progress(
                step_id="press_rf",
                progress_action="press_rf",
                progress_task=self._task,
            )

        try:
            self._code = self._task.result()
        except (OSError, bl.LearnTimeout):
            self._task = None
            # The remembered frequency may belong to a different remote, so fall
            # back to a full sweep rather than declaring failure.
            if not self._swept:
                self._frequency = None
                return self.async_show_progress_done(next_step_id="hold_rf")
            return self.async_show_progress_done(next_step_id="failed")

        self._task = None
        return self.async_show_progress_done(next_step_id="name")

    async def _learn_rf(self) -> str:
        return await self.hass.async_add_executor_job(
            bl.learn_rf, self._device_handle, self._frequency
        )

    def _finish_task(self) -> SubentryFlowResult:
        try:
            self._code = self._task.result()
        except (OSError, bl.LearnTimeout):
            self._task = None
            return self.async_show_progress_done(next_step_id="failed")

        self._task = None
        return self.async_show_progress_done(next_step_id="name")

    async def async_step_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if user_input is not None:
            return await self.async_step_user()
        return self.async_show_form(step_id="failed", data_schema=vol.Schema({}))

    # --- Test, name, place -------------------------------------------------------

    async def async_step_name(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Let the code be tested as often as needed before it is saved."""
        errors: dict[str, str] = {}
        placeholders = {"result": ""}
        # After a relearn the name and area were already chosen; carry them over.
        previous = user_input or self._pending or {}

        if user_input is not None:
            if user_input.get(CONF_TEST):
                try:
                    device = await self._device()
                    await self.hass.async_add_executor_job(
                        bl.send, device, self._code, _repeats(user_input)
                    )
                except OSError:
                    errors["base"] = "cannot_connect"
                else:
                    placeholders["result"] = "Sent. If nothing happened, learn it again."
            elif self._reconfiguring:
                return self._save(user_input, self._get_reconfigure_subentry())
            else:
                return self.async_create_entry(
                    title=user_input["name"],
                    data={
                        CONF_CODE: self._code,
                        CONF_CODE_TYPE: self._code_type,
                        CONF_AREA_ID: user_input.get(CONF_AREA_ID),
                        CONF_FREQUENCY: self._frequency,
                        CONF_REPEATS: _repeats(user_input),
                    },
                )

        name_field = (
            vol.Required("name", default=previous["name"])
            if "name" in previous
            else vol.Required("name")
        )
        area_field = (
            vol.Optional(CONF_AREA_ID, default=previous[CONF_AREA_ID])
            if previous.get(CONF_AREA_ID)
            else vol.Optional(CONF_AREA_ID)
        )

        return self.async_show_form(
            step_id="name",
            data_schema=vol.Schema(
                {
                    name_field: str,
                    area_field: selector.AreaSelector(),
                    vol.Optional(CONF_REPEATS, default=_repeats(previous)): REPEATS,
                    vol.Optional(CONF_TEST, default=False): bool,
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )
