"""Legacy dependency code is blocked with an actionable recovery path."""

from unittest.mock import MagicMock, patch

import broadlink
from broadlink.device import Device
from broadlink.remote import rmmini, rmpro
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError
from homeassistant.helpers import issue_registry as ir, translation
from homeassistant.setup import async_setup_component
from homeassistant.util.package import is_installed
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

from custom_components import broadlink_commands as component
from custom_components.broadlink_commands import device as bl
from custom_components.broadlink_commands.button import BroadlinkCommandButton
from custom_components.broadlink_commands.config_flow import BroadlinkCommandsConfigFlow
from custom_components.broadlink_commands.const import DOMAIN, LIBRARY_RECOVERY_URL

INFO = {
    "host": "192.0.2.1",
    "mac": "001122334455",
    "devtype": 0x2712,
    "model": "RM pro",
}


@pytest.fixture
def legacy_library():
    discover = MagicMock(
        side_effect=AssertionError("Legacy discovery must not be called")
    )
    with patch.object(broadlink, "discover", discover):
        yield discover
    discover.assert_not_called()


@pytest.fixture
def entry():
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=INFO["mac"],
        data=INFO,
        title=INFO["model"],
        subentries_data=[
            {
                "subentry_type": "command",
                "title": "Power",
                "unique_id": None,
                "data": {"code": "2600", "code_type": "ir"},
            }
        ],
    )


def test_current_library_is_compatible():
    bl.check_library()


def test_legacy_namespace_is_rejected_despite_satisfied_metadata(legacy_library):
    assert is_installed("python-broadlink>=1.0.6")
    with pytest.raises(bl.IncompatibleLibrary, match="python-broadlink>=1.0.6"):
        bl.check_library()


@pytest.mark.parametrize(
    ("owner", "method"),
    [
        (broadlink, "hello"),
        (Device, "hello"),
        (Device, "auth"),
        (rmmini, "enter_learning"),
        (rmmini, "check_data"),
        (rmmini, "send_data"),
        (rmpro, "sweep_frequency"),
        (rmpro, "check_frequency"),
        (rmpro, "cancel_sweep_frequency"),
        (rmpro, "find_rf_packet"),
    ],
)
def test_mixed_synchronous_methods_are_rejected(owner, method):
    with patch.object(owner, method, MagicMock()):
        with pytest.raises(bl.IncompatibleLibrary):
            bl.check_library()


def test_missing_endpoint_cleanup_is_rejected(monkeypatch):
    monkeypatch.delattr(Device, "aclose")
    with pytest.raises(bl.IncompatibleLibrary):
        bl.check_library()


@pytest.mark.parametrize("operation", ["discover", "identify", "connect", "supports_rf"])
async def test_device_helpers_reject_legacy_code_before_use(legacy_library, operation):
    with patch.object(broadlink, "gendevice") as factory:
        with pytest.raises(bl.IncompatibleLibrary):
            if operation == "discover":
                await bl.discover()
            elif operation == "identify":
                await bl.identify(INFO["host"])
            elif operation == "connect":
                async with bl.connect(INFO["host"], INFO["mac"], INFO["devtype"]):
                    pass
            else:
                bl.supports_rf(INFO["host"], INFO["mac"], INFO["devtype"])
    factory.assert_not_called()


async def test_legacy_library_is_blocked_over_http(
    hass, hass_client, enable_custom_integrations, legacy_library
):
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()
    with patch.object(broadlink, "gendevice") as factory:
        response = await client.post(
            "/api/config/config_entries/flow", json={"handler": DOMAIN}
        )
    assert response.status == 200
    result = await response.json()
    assert result["type"] == "abort"
    assert result["reason"] == "incompatible_library"
    assert not hass.config_entries.async_entries(DOMAIN)
    factory.assert_not_called()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "incompatible_library")
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.is_persistent
    assert issue.learn_more_url == LIBRARY_RECOVERY_URL


async def test_manual_setup_reports_legacy_library(hass, legacy_library):
    handler = BroadlinkCommandsConfigFlow()
    handler.hass = hass
    result = await handler.async_step_manual({"host": INFO["host"]})
    assert result["type"] == "abort"
    assert result["reason"] == "incompatible_library"


async def test_setup_raises_translated_error(hass, entry, legacy_library):
    with pytest.raises(ConfigEntryError) as caught:
        await component.async_setup_entry(hass, entry)
    assert caught.value.translation_key == "incompatible_library"


async def test_setup_failure_preserves_commands(
    hass, enable_custom_integrations, entry, legacy_library
):
    entry.add_to_hass(hass)
    commands = dict(entry.subentries)
    with patch.object(broadlink, "gendevice") as factory:
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.subentries == commands
    assert hass.config_entries.async_get_entry(entry.entry_id) is entry
    factory.assert_not_called()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "incompatible_library")


@pytest.mark.parametrize("source", ["user", "reconfigure"])
async def test_command_flows_block_legacy_library(
    hass, enable_custom_integrations, entry, legacy_library, source
):
    entry.add_to_hass(hass)
    context = {"source": source}
    if source == "reconfigure":
        context["subentry_id"] = next(iter(entry.subentries))
    with patch.object(broadlink, "gendevice") as factory:
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, "command"), context=context
        )
    assert result["type"] == "abort"
    assert result["reason"] == "incompatible_library"
    factory.assert_not_called()
    assert len(entry.subentries) == 1


async def test_button_reports_legacy_library(hass, entry, legacy_library):
    entry.runtime_data = component.BroadlinkRuntime(
        INFO["host"], INFO["mac"], INFO["devtype"]
    )
    button = BroadlinkCommandButton(entry, next(iter(entry.subentries.values())))
    button.hass = hass
    with patch.object(broadlink, "gendevice") as factory:
        with pytest.raises(HomeAssistantError) as caught:
            await button.async_press()
    assert caught.value.translation_key == "incompatible_library"
    factory.assert_not_called()


def test_repair_is_cleared_after_recovery(hass, caplog):
    with patch.object(broadlink, "discover", MagicMock()):
        assert not component.async_check_library(hass)
    assert broadlink.__file__ in caplog.text
    assert LIBRARY_RECOVERY_URL in caplog.text
    assert ir.async_get(hass).async_get_issue(DOMAIN, "incompatible_library")
    assert component.async_check_library(hass)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "incompatible_library") is None


@pytest.mark.parametrize("language", ["en", "pt"])
async def test_repair_translation_is_available(
    hass, enable_custom_integrations, language
):
    translations = await translation.async_get_translations(
        hass, language, "issues", {DOMAIN}
    )
    prefix = f"component.{DOMAIN}.issues.incompatible_library"
    assert translations[f"{prefix}.title"]
    assert "{documentation_url}" in translations[f"{prefix}.description"]
