"""Supported devices, learning capabilities and address recovery."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import broadlink
from broadlink.device import Device
from broadlink.remote import rmmini, rmpro, rm4mini, rm4pro
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

from custom_components.broadlink_commands import device as bl
from custom_components.broadlink_commands.config_flow import (
    BroadlinkCommandsConfigFlow,
    CommandSubentryFlowHandler,
)
from custom_components.broadlink_commands.const import DISCOVERY_TIMEOUT, DOMAIN

HOST = "192.0.2.1"
MAC = "001122334455"
LEARNING_CLASSES = (rmmini, rmpro, rm4mini, rm4pro)


def make_device(cls):
    devtype = next(iter(broadlink.SUPPORTED_TYPES[cls]))
    return broadlink.gendevice(devtype, (HOST, 80), bytes.fromhex(MAC))


@pytest.fixture(params=LEARNING_CLASSES, ids=lambda cls: cls.__name__)
def remote(request):
    return make_device(request.param)


def test_discovery_accepts_supported_devices_and_filters_others():
    remotes = [make_device(cls) for cls in LEARNING_CLASSES]
    plug = broadlink.gendevice(0x2711, (HOST, 80), bytes.fromhex(MAC))
    with patch.object(bl.broadlink, "discover", return_value=[plug, *remotes]) as discover:
        found = bl.discover(target=HOST)
    discover.assert_called_once_with(
        timeout=DISCOVERY_TIMEOUT, discover_ip_address=HOST
    )
    assert [info["type"] for info in found] == [
        "RMMINI", "RMPRO", "RM4MINI", "RM4PRO"
    ]
    assert [info["devtype"] for info in found] == [d.devtype for d in remotes]


def test_manual_identification_accepts_supported_devices(remote):
    with patch.object(bl.broadlink, "hello", return_value=remote) as hello:
        info = bl.identify(HOST)
    hello.assert_called_once_with(HOST, timeout=DISCOVERY_TIMEOUT)
    assert info["type"] == remote.type
    assert info["mac"] == MAC
    assert info["devtype"] == remote.devtype


@pytest.mark.parametrize("devtype", [0x2711, 0xFFFF], ids=["switch", "unknown"])
def test_manual_identification_rejects_unsupported_devices(devtype):
    device = broadlink.gendevice(devtype, (HOST, 80), bytes.fromhex(MAC))
    with patch.object(bl.broadlink, "hello", return_value=device):
        with pytest.raises(bl.UnsupportedDevice):
            bl.identify(HOST)


def test_rf_capability_is_local_and_matches_library(remote):
    expected = isinstance(remote, (rmpro, rm4pro))
    with (
        patch.object(Device, "hello") as hello,
        patch.object(Device, "auth") as auth,
        patch.object(Device, "send_packet") as send_packet,
    ):
        assert bl.supports_rf(HOST, MAC, remote.devtype) is expected
    hello.assert_not_called()
    auth.assert_not_called()
    send_packet.assert_not_called()


async def test_learning_menu_matches_capabilities(hass, remote):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": HOST, "mac": MAC, "devtype": remote.devtype},
    )
    handler = CommandSubentryFlowHandler()
    handler.hass = hass
    with patch.object(handler, "_get_entry", return_value=entry):
        result = await handler.async_step_user()
    expected = ["learn_ir"]
    if isinstance(remote, (rmpro, rm4pro)):
        expected.append("learn_rf")
    assert result["type"] == "menu"
    assert result["menu_options"] == expected


@pytest.mark.parametrize("cls", [rmmini, rm4mini], ids=lambda cls: cls.__name__)
async def test_ir_only_device_rejects_direct_rf_learning(hass, cls):
    remote = make_device(cls)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": HOST, "mac": MAC, "devtype": remote.devtype},
    )
    handler = CommandSubentryFlowHandler()
    handler.hass = hass
    with (
        patch.object(handler, "_get_entry", return_value=entry),
        patch.object(bl, "connect") as connect,
        patch.object(bl, "sweep_rf") as sweep,
        patch.object(bl, "learn_rf") as learn,
    ):
        result = await handler.async_step_learn_rf()
    assert result["type"] == "abort"
    assert result["reason"] == "unsupported_rf"
    assert handler._task is None
    connect.assert_not_called()
    sweep.assert_not_called()
    learn.assert_not_called()


async def test_manual_setup_can_retry_after_unsupported_device(hass):
    plug = broadlink.gendevice(0x2711, (HOST, 80), bytes.fromhex(MAC))
    remote = make_device(rmmini)
    handler = BroadlinkCommandsConfigFlow()
    handler.hass = hass
    handler.async_set_unique_id = AsyncMock()
    handler._abort_if_unique_id_configured = MagicMock()
    with (
        patch.object(bl.broadlink, "hello", side_effect=[plug, remote]),
        patch.object(bl, "connect", return_value=remote) as connect,
    ):
        result = await handler.async_step_manual({"host": HOST})
        assert result["type"] == "form"
        assert result["step_id"] == "manual"
        assert result["errors"] == {"base": "unsupported_device"}
        connect.assert_not_called()
        handler.async_set_unique_id.assert_not_called()
        result = await handler.async_step_manual({"host": HOST})
    assert result["type"] == "create_entry"
    assert result["data"]["devtype"] == remote.devtype
    connect.assert_called_once_with(HOST, MAC, remote.devtype)


@pytest.mark.parametrize("manual", [False, True], ids=["discovery", "manual"])
async def test_adding_same_device_updates_ip_and_preserves_commands(
    hass, enable_custom_integrations, manual
):
    remote = make_device(rmpro)
    info = bl._describe(remote)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        data={**info, "host": "192.0.2.99"},
        state=ConfigEntryState.LOADED,
        subentries_data=[
            {
                "subentry_type": "command",
                "title": "Power",
                "unique_id": None,
                "data": {"code": "2600", "code_type": "ir"},
            }
        ],
    )
    entry.add_to_hass(hass)
    commands = dict(entry.subentries)
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "button", DOMAIN, next(iter(commands)), config_entry=entry
    )
    with (
        patch.object(bl, "discover", return_value=[info]),
        patch.object(bl, "identify", return_value=info),
        patch.object(bl, "connect") as connect,
        patch.object(hass.config_entries, "async_schedule_reload") as reload,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == "form"
        if manual:
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"host": "manual"}
            )
            assert result["step_id"] == "manual"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": HOST if manual else MAC}
        )
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == HOST
    assert entry.subentries == commands
    assert registry.async_get(entity.entity_id) == entity
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    reload.assert_called_once_with(entry.entry_id)
    connect.assert_not_called()


def test_support_translations():
    component = Path(__file__).resolve().parents[1] / "custom_components" / DOMAIN
    strings = json.loads((component / "strings.json").read_text())
    assert strings == json.loads((component / "translations/en.json").read_text())
    for data in (strings, json.loads((component / "translations/pt.json").read_text())):
        assert data["config"]["error"]["unsupported_device"]
        assert data["config_subentries"]["command"]["abort"]["unsupported_rf"]
