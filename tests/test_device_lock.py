"""Device locks are reported without changing settings or sending commands."""

import asyncio
import json
from pathlib import Path
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

from broadlink.exceptions import NetworkTimeoutError
from homeassistant.config_entries import ConfigSubentry
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

from custom_components.broadlink_commands import (
    BroadlinkRuntime,
    async_setup_entry,
    device as bl,
)
from custom_components.broadlink_commands.button import BroadlinkCommandButton
from custom_components.broadlink_commands.config_flow import (
    BroadlinkCommandsConfigFlow,
    CommandSubentryFlowHandler,
)
from custom_components.broadlink_commands.const import DOMAIN

INFO = {
    "host": "192.0.2.1",
    "mac": "001122334455",
    "devtype": 0x2737,
    "model": "Broadlink RM mini",
}
COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / DOMAIN


@pytest.fixture
def handle():
    """No test communicates with real hardware."""
    with patch.object(bl.broadlink, "gendevice") as factory:
        device = factory.return_value
        device.is_locked = True
        device.type = "RMPRO"
        yield device
        device.set_lock.assert_not_called()
        if device.is_locked or device.hello.side_effect:
            device.send_data.assert_not_called()
            device.enter_learning.assert_not_called()
            device.sweep_frequency.assert_not_called()
            device.find_rf_packet.assert_not_called()


@pytest.fixture
def entry():
    return MockConfigEntry(domain=DOMAIN, data=INFO, title=INFO["model"])


@pytest.fixture
def button(hass, entry):
    entry.runtime_data = BroadlinkRuntime(INFO["host"], INFO["mac"], INFO["devtype"])
    subentry = ConfigSubentry(
        data=MappingProxyType({"code": "2600"}),
        subentry_type="command",
        title="Power",
        unique_id=None,
    )
    entity = BroadlinkCommandButton(entry, subentry)
    entity.hass = hass
    return entity


@pytest.fixture
def flow(hass, entry):
    handler = CommandSubentryFlowHandler()
    handler.hass = hass
    with patch.object(handler, "_get_entry", return_value=entry):
        yield handler


def test_locked_connection(handle):
    with pytest.raises(bl.DeviceLocked, match="Unlock it in the Broadlink app"):
        bl.connect(INFO["host"], INFO["mac"], INFO["devtype"])
    handle.hello.assert_called_once_with()
    handle.auth.assert_not_called()


def test_unlocked_connection(handle):
    handle.is_locked = False
    assert bl.connect(INFO["host"], INFO["mac"], INFO["devtype"]) is handle
    assert handle.method_calls == [
        ("hello", (), {}),
        ("auth", (), {}),
    ]


@pytest.mark.parametrize("error", [OSError("offline"), NetworkTimeoutError(-4000)])
def test_lock_check_failure_is_not_ignored(handle, error):
    handle.hello.side_effect = error
    with pytest.raises(type(error)):
        bl.connect(INFO["host"], INFO["mac"], INFO["devtype"])
    handle.auth.assert_not_called()


async def test_setup_locked(hass, entry, handle):
    with pytest.raises(ConfigEntryNotReady) as caught:
        await async_setup_entry(hass, entry)
    assert caught.value.translation_key == "device_locked"


async def test_press_locked(button, handle):
    with pytest.raises(HomeAssistantError) as caught:
        await button.async_press()
    assert caught.value.translation_key == "device_locked"


@pytest.mark.parametrize("manual", [False, True])
async def test_config_flow_locked(hass, handle, manual):
    handler = BroadlinkCommandsConfigFlow()
    handler.hass = hass
    handler.async_set_unique_id = AsyncMock()
    handler._abort_if_unique_id_configured = MagicMock()
    with patch.object(bl, "identify", return_value=INFO), patch.object(
        bl, "discover", return_value=[INFO]
    ):
        if manual:
            result = await handler.async_step_manual({"host": INFO["host"]})
        else:
            await handler.async_step_user()
            result = await handler.async_step_user({"host": INFO["mac"]})
    assert result["type"] == "abort"
    assert result["reason"] == "device_locked"


@pytest.mark.parametrize("step", ["learn_ir", "hold_rf"])
async def test_learning_locked(flow, handle, step):
    method = getattr(flow, f"async_step_{step}")
    result = await method()
    if result["type"] == "progress":
        await asyncio.gather(flow._task, return_exceptions=True)
        result = await method()
    assert result["type"] == "progress_done"
    assert result["step_id"] == "device_locked"
    assert flow._task is None
    result = await flow.async_step_device_locked()
    assert result["reason"] == "device_locked"


async def test_rf_known_frequency_locked(flow, handle):
    flow._frequency = 433.92
    result = await flow.async_step_learn_rf()
    assert result["type"] == "abort"
    assert result["reason"] == "device_locked"
    assert flow._task is None


async def test_test_command_locked(flow, handle):
    flow._code = "2600"
    result = await flow.async_step_name({"name": "Power", "test": True})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "device_locked"}
    assert result["description_placeholders"]["result"] == ""


@pytest.mark.parametrize("surface", ["setup", "press", "config", "test", "rf"])
async def test_query_failure_surfaces(hass, entry, button, flow, handle, surface):
    handle.hello.side_effect = NetworkTimeoutError(-4000)
    if surface == "setup":
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)
    elif surface == "press":
        with pytest.raises(HomeAssistantError):
            await button.async_press()
    elif surface == "config":
        handler = BroadlinkCommandsConfigFlow()
        handler.hass = hass
        handler.async_set_unique_id = AsyncMock()
        handler._abort_if_unique_id_configured = MagicMock()
        result = await handler._create(INFO)
        assert result["reason"] == "cannot_connect"
    elif surface == "test":
        flow._code = "2600"
        result = await flow.async_step_name({"name": "Power", "test": True})
        assert result["errors"] == {"base": "cannot_connect"}
    else:
        flow._frequency = 433.92
        result = await flow.async_step_learn_rf()
        assert result["reason"] == "cannot_connect"


async def test_press_unlocked(button, handle):
    handle.is_locked = False
    await button.async_press()
    handle.send_data.assert_called_once_with(bytes.fromhex("2600"))


async def test_config_flow_unlocked(hass, handle):
    handle.is_locked = False
    handler = BroadlinkCommandsConfigFlow()
    handler.hass = hass
    handler.async_set_unique_id = AsyncMock()
    handler._abort_if_unique_id_configured = MagicMock()
    result = await handler._create(INFO)
    assert result["type"] == "create_entry"
    assert result["data"] == INFO


async def test_test_command_unlocked(flow, handle):
    handle.is_locked = False
    flow._code = "2600"
    result = await flow.async_step_name({"name": "Power", "test": True})
    assert result["errors"] == {}
    assert result["description_placeholders"]["result"].startswith("Sent.")
    handle.send_data.assert_called_once_with(bytes.fromhex("2600"))


@pytest.mark.parametrize("step", ["learn_ir", "hold_rf", "learn_rf"])
async def test_learning_unlocked(flow, handle, step):
    handle.is_locked = False
    if step == "learn_rf":
        flow._frequency = 433.92
    with (
        patch.object(bl, "learn_ir", return_value="2600"),
        patch.object(bl, "sweep_rf", return_value=433.92),
        patch.object(bl, "learn_rf", return_value="2600"),
    ):
        method = getattr(flow, f"async_step_{step}")
        result = await method()
        if result["type"] == "progress":
            await flow._task
            method = flow.async_step_press_rf if step == "learn_rf" else method
            result = await method()
    assert result["type"] == "progress_done"
    assert result["step_id"] == ("press_rf" if step == "hold_rf" else "name")


def test_lock_translations():
    strings = json.loads((COMPONENT / "strings.json").read_text())
    english = json.loads((COMPONENT / "translations/en.json").read_text())
    assert strings == english
    for data in (strings, json.loads((COMPONENT / "translations/pt.json").read_text())):
        assert data["config"]["abort"]["device_locked"]
        command = data["config_subentries"]["command"]
        assert command["abort"]["device_locked"]
        assert command["error"]["device_locked"]
        assert data["exceptions"]["device_locked"]["message"]
