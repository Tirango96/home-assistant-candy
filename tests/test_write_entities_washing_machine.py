"""Tests for write entities (select/number/button) in Full Control mode."""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN
from custom_components.candy.client.model import MachineState
from custom_components.candy.const import (
    CONF_KEY_MODE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_COORDINATOR,
    MODE_FULL_CONTROL,
    MODE_READ_ONLY,
    UNIQUE_ID_WASH_DELAY_NUMBER,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_SOIL_SELECT,
    UNIQUE_ID_WASH_SPIN_SELECT,
    UNIQUE_ID_WASH_START_BUTTON,
    UNIQUE_ID_WASH_STOP_BUTTON,
    UNIQUE_ID_WASH_TEMP_SELECT,
)

from .common import TEST_IP

# ---------------------------------------------------------------------------
# Minimal program catalog used across all tests
# ---------------------------------------------------------------------------

# COTTON: pos=1, supports temp/spin/soil selection
_COTTON = {
    "program": {
        "position": 1,
        "name": "DUAL_WM_WD_PROGRAM_NAME_COTTON",
        "command_parameters": [
            {"command_parameter": {"name": "pr_code", "validation": "136"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "90"}},
            {"command_parameter": {"name": "default_temperature", "validation": "40"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "1400"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "800"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "1"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "3"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "2"}},
        ],
    }
}

# RAPID: pos=2, temp and spin fixed (255 = not selectable), soil fixed
_RAPID = {
    "program": {
        "position": 2,
        "name": "DUAL_WM_WD_PROGRAM_NAME_RAPID",
        "command_parameters": [
            {"command_parameter": {"name": "pr_code", "validation": "5"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "255"}},
            {"command_parameter": {"name": "default_temperature", "validation": "30"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "255"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "800"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "0"}},
        ],
    }
}

_PROGRAMS = [_COTTON, _RAPID]

_IDLE_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
  }
}"""

_RUNNING_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "2", "Pr": "1", "PrPh": "2",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "1800", "FillR": "50", "CheckUpState": "0"
  }
}"""

# MachMd=1 (IDLE) is the closest the device returns; OFF is synthetic (unreachable).
# Simulate it by using IDLE JSON and then patching the coordinator data to MachineState.OFF.
_OFF_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "0", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
  }
}"""

_STATS_OK = '{"Program1": "0"}'


def _add_stats_mocks(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(
        f"http://{TEST_IP}/http-prepareStatistics.json?encrypted=0",
        text='{"response":"SUCCESS"}',
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-getStatistics.json?encrypted=0",
        text=_STATS_OK,
    )


async def _init_full_control(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status_json: str
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-full-control",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: _PROGRAMS,
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    _add_stats_mocks(aioclient_mock)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _init_full_control_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> MockConfigEntry:
    """Init Full Control with the machine in the synthetic OFF state."""
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    off_status = copy.copy(coordinator.data)
    off_status.machine_state = MachineState.OFF
    coordinator.async_set_updated_data(off_status)
    await hass.async_block_till_done()
    return entry


def _state(hass: HomeAssistant, entry: MockConfigEntry, platform: str, uid_tpl: str):
    """Look up an entity by unique_id template and return its state."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        platform, DOMAIN, uid_tpl.format(entry.entry_id)
    )
    if entity_id is None:
        return None
    return hass.states.get(entity_id)


# ---------------------------------------------------------------------------
# Program select
# ---------------------------------------------------------------------------


async def test_program_select_options(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    assert "COTTON" in state.attributes["options"]
    assert "RAPID" in state.attributes["options"]


async def test_program_select_available_when_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")


async def test_program_select_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    assert state.state == "unavailable"


# ---------------------------------------------------------------------------
# Temperature select
# ---------------------------------------------------------------------------


async def test_temp_select_available_for_cotton_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_TEMP_SELECT)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    assert "90" in state.attributes["options"]
    assert "0" in state.attributes["options"]


async def test_temp_select_unavailable_for_rapid_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    rapid_idle = _IDLE_JSON.replace('"Pr": "1"', '"Pr": "2"').replace(
        '"PrCode": "136"', '"PrCode": "5"'
    )
    entry = await _init_full_control(hass, aioclient_mock, rapid_idle)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_TEMP_SELECT)
    assert state is not None
    assert state.state == "unavailable"


async def test_temp_select_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_TEMP_SELECT)
    assert state is not None
    assert state.state == "unavailable"


# ---------------------------------------------------------------------------
# Spin select
# ---------------------------------------------------------------------------


async def test_spin_select_available_for_cotton_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_SPIN_SELECT)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    assert "1400" in state.attributes["options"]
    assert "400" in state.attributes["options"]


async def test_spin_select_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_SPIN_SELECT)
    assert state is not None
    assert state.state == "unavailable"


# ---------------------------------------------------------------------------
# Soil select
# ---------------------------------------------------------------------------


async def test_soil_select_available_for_cotton_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_SOIL_SELECT)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    assert state.attributes["options"] == ["1", "2", "3"]


async def test_soil_select_unavailable_for_rapid_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    rapid_idle = _IDLE_JSON.replace('"Pr": "1"', '"Pr": "2"').replace(
        '"PrCode": "136"', '"PrCode": "5"'
    )
    entry = await _init_full_control(hass, aioclient_mock, rapid_idle)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_SOIL_SELECT)
    assert state is not None
    assert state.state == "unavailable"


async def test_soil_select_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_SOIL_SELECT)
    assert state is not None
    assert state.state == "unavailable"


# ---------------------------------------------------------------------------
# Delay number
# ---------------------------------------------------------------------------


async def test_delay_number_available_when_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "number", UNIQUE_ID_WASH_DELAY_NUMBER)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    assert state.state == "0"


async def test_delay_number_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "number", UNIQUE_ID_WASH_DELAY_NUMBER)
    assert state is not None
    assert state.state == "unavailable"


# ---------------------------------------------------------------------------
# Start button
# ---------------------------------------------------------------------------


async def test_start_button_available_when_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_START_BUTTON)
    assert state is not None
    assert state.state != "unavailable"


async def test_start_button_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_START_BUTTON)
    assert state is not None
    assert state.state == "unavailable"


async def test_start_button_unavailable_when_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_off(hass, aioclient_mock)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_START_BUTTON)
    assert state is not None
    assert state.state == "unavailable"


async def test_program_select_available_when_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_off(hass, aioclient_mock)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")


async def test_delay_number_available_when_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_off(hass, aioclient_mock)
    state = _state(hass, entry, "number", UNIQUE_ID_WASH_DELAY_NUMBER)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")


async def test_start_button_sends_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    assert entity_id is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )

    mock_send.assert_called_once()
    query_string: str = mock_send.call_args[0][0]
    assert "Write=1" in query_string
    assert "StSt=1" in query_string
    assert "PrNm=1" in query_string
    assert "PrCode=136" in query_string
    assert "PrStr=COTTON" in query_string


# ---------------------------------------------------------------------------
# Stop button
# ---------------------------------------------------------------------------


async def test_stop_button_unavailable_when_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_STOP_BUTTON)
    assert state is not None
    assert state.state == "unavailable"


async def test_stop_button_available_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_STOP_BUTTON)
    assert state is not None
    assert state.state != "unavailable"


async def test_stop_button_sends_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_STOP_BUTTON.format(entry.entry_id)
    )
    assert entity_id is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )

    mock_send.assert_called_once()
    query_string: str = mock_send.call_args[0][0]
    assert "Write=1" in query_string
    assert "StSt=0" in query_string


# ---------------------------------------------------------------------------
# Read-only mode — no write entities registered
# ---------------------------------------------------------------------------


async def test_no_write_entities_in_read_only_mode(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-read-only",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=_IDLE_JSON)
    _add_stats_mocks(aioclient_mock)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
        )
        is None
    )
    assert (
        registry.async_get_entity_id(
            "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
        )
        is None
    )
    assert (
        registry.async_get_entity_id(
            "button", DOMAIN, UNIQUE_ID_WASH_STOP_BUTTON.format(entry.entry_id)
        )
        is None
    )
    assert (
        registry.async_get_entity_id(
            "number", DOMAIN, UNIQUE_ID_WASH_DELAY_NUMBER.format(entry.entry_id)
        )
        is None
    )
