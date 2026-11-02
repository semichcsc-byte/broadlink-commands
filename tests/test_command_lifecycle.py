"""Learning, editing and deleting commands through real Home Assistant flows."""

import asyncio
from types import MappingProxyType
from unittest.mock import MagicMock, patch

import broadlink
from broadlink.remote import rmpro
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

from custom_components.broadlink_commands import device as bl
from custom_components.broadlink_commands.const import DOMAIN

HOST = "192.0.2.1"
MAC = "001122334455"
IR_CODE = bytes.fromhex("2600040001020304")
RF_CODE = bytes.fromhex("b200040001020304")


@pytest.fixture
async def remote_entry(hass, enable_custom_integrations):
    device = MagicMock(spec=rmpro)
    device.is_locked = False
    device.type = "RMPRO"
    device.check_data.return_value = IR_CODE
    device.check_frequency.return_value = (True, 433.92)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        title="RM pro",
        data={"host": HOST, "mac": MAC, "devtype": 0x2712, "model": "RM pro"},
    )
    entry.add_to_hass(hass)
    with (
        patch.object(broadlink, "gendevice", return_value=device),
        patch.object(bl, "POLL_INTERVAL", 0),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        yield entry, device
        device.set_lock.assert_not_called()


async def start_learning(hass, entry, kind):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "command"), context={"source": "user"}
    )
    assert result["type"] == "menu"
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": kind}
    )


async def finish_learning(hass, result, steps):
    for step in steps:
        assert result["type"] == "progress"
        assert result["step_id"] == step
        await hass.async_block_till_done()
        result = await hass.config_entries.subentries.async_configure(result["flow_id"])
    assert result["type"] == "form"
    assert result["step_id"] == "name"
    return result


async def add_command(hass, entry, *, code_type="ir", frequency=None):
    subentry = ConfigSubentry(
        data=MappingProxyType(
            {
                "code": IR_CODE.hex(),
                "code_type": code_type,
                "area_id": None,
                "frequency": frequency,
            }
        ),
        subentry_type="command",
        title="Power",
        unique_id=None,
    )
    assert hass.config_entries.async_add_subentry(entry, subentry)
    await hass.async_block_till_done()
    return subentry


@pytest.mark.parametrize(
    ("kind", "steps", "code", "code_type", "frequency"),
    [
        ("learn_ir", ("learn_ir",), IR_CODE, "ir", None),
        ("learn_rf", ("hold_rf", "press_rf"), RF_CODE, "rf", 433.92),
    ],
)
async def test_learn_save_press_and_delete(
    hass, remote_entry, kind, steps, code, code_type, frequency
):
    entry, device = remote_entry
    device.check_data.return_value = code
    area = ar.async_get(hass).async_create("Living room")
    result = await finish_learning(
        hass, await start_learning(hass, entry, kind), steps
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Power", "area_id": area.id, "test": False}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert len(entry.subentries) == 1
    subentry = next(iter(entry.subentries.values()))
    assert dict(subentry.data) == {
        "code": code.hex(),
        "code_type": code_type,
        "area_id": area.id,
        "frequency": frequency,
    }
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("button", DOMAIN, subentry.subentry_id)
    assert entity_id is not None
    assert hass.states.get(entity_id) is not None
    entity = registry.async_get(entity_id)
    assert entity.area_id == area.id
    remote = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, MAC), entry.entry_id
    )
    assert remote is not None
    assert entity.device_id == remote.id
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )
    device.send_data.assert_awaited_once_with(code)
    assert hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    await hass.async_block_till_done()
    assert registry.async_get(entity_id) is None
    assert hass.states.get(entity_id) is None
    assert dr.async_get(hass).async_get(remote.id) is not None


async def test_rename_and_move_preserves_code_and_entity(hass, remote_entry):
    entry, _ = remote_entry
    subentry = await add_command(hass, entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("button", DOMAIN, subentry.subentry_id)
    area = ar.async_get(hass).async_create("Kitchen")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "command"),
        context={"source": "reconfigure", "subentry_id": subentry.subentry_id},
    )
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "TV Power", "area_id": area.id}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.subentries[subentry.subentry_id].title == "TV Power"
    assert subentry.data["code"] == IR_CODE.hex()
    assert registry.async_get_entity_id("button", DOMAIN, subentry.subentry_id) == entity_id
    assert registry.async_get(entity_id).area_id == area.id


async def test_relearn_preserves_entity_and_pending_name(hass, remote_entry):
    entry, device = remote_entry
    subentry = await add_command(hass, entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("button", DOMAIN, subentry.subentry_id)
    device.check_data.return_value = IR_CODE + b"\x05"
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "command"),
        context={"source": "reconfigure", "subentry_id": subentry.subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "TV Power", "relearn": True}
    )
    assert result["type"] == "menu"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "learn_ir"}
    )
    result = await finish_learning(hass, result, ("learn_ir",))
    defaults = result["data_schema"]({})
    assert defaults["name"] == "TV Power"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], defaults
    )
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert len(entry.subentries) == 1
    assert subentry.data["code"] == (IR_CODE + b"\x05").hex()
    assert registry.async_get_entity_id("button", DOMAIN, subentry.subentry_id) == entity_id


async def test_cached_rf_frequency_falls_back_to_sweep(hass, remote_entry):
    entry, _ = remote_entry
    await add_command(hass, entry, code_type="rf", frequency=315.0)
    with patch.object(
        bl, "learn_rf", side_effect=[bl.LearnTimeout("No code"), RF_CODE.hex()]
    ) as learn:
        result = await start_learning(hass, entry, "learn_rf")
        for _ in range(4):
            if result["type"] == "form":
                break
            assert result["type"] == "progress"
            await hass.async_block_till_done()
            result = await hass.config_entries.subentries.async_configure(
                result["flow_id"]
            )
    assert learn.await_args_list[0].args[1] == 315.0
    assert learn.await_args_list[1].args[1] == 433.92
    assert result["step_id"] == "name"
    hass.config_entries.subentries.async_abort(result["flow_id"])


@pytest.mark.parametrize(
    ("kind", "waiting_method"),
    [("learn_ir", "check_data"), ("learn_rf", "check_frequency")],
)
async def test_aborting_flow_cancels_io_and_closes_endpoint(
    hass, remote_entry, kind, waiting_method
):
    entry, device = remote_entry
    started = asyncio.Event()
    task = None

    async def wait_for_device():
        nonlocal task
        task = asyncio.current_task()
        started.set()
        await asyncio.Future()

    getattr(device, waiting_method).side_effect = wait_for_device
    device.aclose.reset_mock()
    result = await start_learning(hass, entry, kind)
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
    finally:
        hass.config_entries.subentries.async_abort(result["flow_id"])
    assert task is not None
    with pytest.raises(asyncio.CancelledError):
        await task
    await hass.async_block_till_done()
    device.aclose.assert_awaited_once_with()
    assert not entry.subentries
