"""Tests for the self check-up feature."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN
from custom_components.candy.button import _should_send_checkup
from custom_components.candy.client.model import CheckUpResult
from custom_components.candy.const import (
    CHECKUP_SCHEDULE_EVERY_CYCLE,
    CHECKUP_SCHEDULE_MONTHLY,
    CHECKUP_SCHEDULE_WEEKLY,
    CONF_KEY_CHECKUP_ENABLED,
    CONF_KEY_CHECKUP_LAST_DATE,
    CONF_KEY_CHECKUP_SCHEDULE,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_COORDINATOR,
    MODE_FULL_CONTROL,
    UNIQUE_ID_WASH_CHECKUP_RESULT,
    UNIQUE_ID_WASH_LAST_CHECKUP,
)

from .common import TEST_IP

# ---------------------------------------------------------------------------
# Minimal program entry (no steam)
# ---------------------------------------------------------------------------

_COTTON = {
    "program": {
        "position": 1,
        "name": "DUAL_WM_WD_PROGRAM_NAME_COTTON",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "1"}},
            {"command_parameter": {"name": "pr_code", "validation": "136"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "90"}},
            {"command_parameter": {"name": "default_temperature", "validation": "40"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "1400"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "800"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "1"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "3"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "2"}},
            {"command_parameter": {"name": "steam", "validation": "0"}},
            {"command_parameter": {"name": "default_duration", "validation": "90"}},
            {
                "command_parameter": {
                    "name": "remaining_time_soil_max",
                    "validation": "120",
                }
            },
            {
                "command_parameter": {
                    "name": "remaining_time_soil_medium",
                    "validation": "90",
                }
            },
            {
                "command_parameter": {
                    "name": "remaining_time_soil_min",
                    "validation": "60",
                }
            },
            {"command_parameter": {"name": "available_options", "validation": "0"}},
        ],
    }
}

_IDLE_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
  }
}"""

_IDLE_WITH_DIS_TEST_RES_0 = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0", "DisTestRes": "0"
  }
}"""

_IDLE_WITH_DIS_TEST_RES_1 = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "2", "DisTestRes": "1"
  }
}"""

_IDLE_WITH_DIS_TEST_RES_2 = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "2", "DisTestRes": "2"
  }
}"""

_STATS_OK = '{"statusCounters": {"Program1": "40"}}'

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(**extra) -> MockConfigEntry:
    data = {
        CONF_IP_ADDRESS: TEST_IP,
        CONF_KEY_USE_ENCRYPTION: False,
        CONF_PASSWORD: "",
        CONF_KEY_MODE: MODE_FULL_CONTROL,
        CONF_KEY_PROGRAMS: [_COTTON],
    }
    data.update(extra)
    return MockConfigEntry(domain=DOMAIN, unique_id="test-checkup", data=data)


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status_json: str,
    **extra_data,
) -> MockConfigEntry:
    entry = _make_entry(**extra_data)
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    aioclient_mock.get(
        f"http://{TEST_IP}/http-prepareStatistics.json?encrypted=0",
        text='{"response":"SUCCESS"}',
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-getStatistics.json?encrypted=0",
        text=_STATS_OK,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _sensor_state(hass: HomeAssistant, entry: MockConfigEntry, uid_tpl: str):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, uid_tpl.format(entry.entry_id)
    )
    if entity_id is None:
        return None
    return hass.states.get(entity_id)


# ---------------------------------------------------------------------------
# Unit tests for _should_send_checkup
# ---------------------------------------------------------------------------


def test_checkup_disabled_returns_0():
    entry = _make_entry(**{CONF_KEY_CHECKUP_ENABLED: False})
    assert _should_send_checkup(entry, _NOW) == 0


def test_checkup_disabled_ignores_schedule():
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: False,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_EVERY_CYCLE,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 0


def test_checkup_every_cycle_returns_1():
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_EVERY_CYCLE,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


def test_checkup_every_cycle_returns_1_even_if_recently_run():
    yesterday = (_NOW - timedelta(days=1)).timestamp()
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_EVERY_CYCLE,
            CONF_KEY_CHECKUP_LAST_DATE: yesterday,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


def test_checkup_weekly_no_last_date_returns_1():
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


def test_checkup_weekly_8_days_elapsed_returns_1():
    last = (_NOW - timedelta(days=8)).timestamp()
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_LAST_DATE: last,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


def test_checkup_weekly_3_days_elapsed_returns_0():
    last = (_NOW - timedelta(days=3)).timestamp()
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_LAST_DATE: last,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 0


def test_checkup_weekly_exactly_7_days_elapsed_returns_1():
    last = (_NOW - timedelta(days=7)).timestamp()
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_LAST_DATE: last,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


def test_checkup_monthly_no_last_date_returns_1():
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_MONTHLY,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


def test_checkup_monthly_31_days_elapsed_returns_1():
    last = (_NOW - timedelta(days=31)).timestamp()
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_MONTHLY,
            CONF_KEY_CHECKUP_LAST_DATE: last,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


def test_checkup_monthly_20_days_elapsed_returns_0():
    last = (_NOW - timedelta(days=20)).timestamp()
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_MONTHLY,
            CONF_KEY_CHECKUP_LAST_DATE: last,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 0


def test_checkup_monthly_exactly_30_days_elapsed_returns_1():
    last = (_NOW - timedelta(days=30)).timestamp()
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_MONTHLY,
            CONF_KEY_CHECKUP_LAST_DATE: last,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


# ---------------------------------------------------------------------------
# CheckUpResult model
# ---------------------------------------------------------------------------


def test_checkup_result_enum_values():
    assert CheckUpResult.NOT_RUN.code == 0
    assert CheckUpResult.OK.code == 1
    assert CheckUpResult.PROBLEM.code == 2


def test_checkup_result_from_code():
    assert CheckUpResult.from_code(0) == CheckUpResult.NOT_RUN
    assert CheckUpResult.from_code(1) == CheckUpResult.OK
    assert CheckUpResult.from_code(2) == CheckUpResult.PROBLEM


# ---------------------------------------------------------------------------
# DisTestRes transition listener — timestamp persistence
# ---------------------------------------------------------------------------


async def test_dis_test_res_transition_0_to_1_writes_timestamp(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """DisTestRes 0->1: config entry must be updated with checkup_last_date."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_0,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    new_status = copy.copy(coordinator.data)
    new_status.dis_test_res = CheckUpResult.OK
    coordinator.async_set_updated_data(new_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is not None


async def test_dis_test_res_transition_0_to_2_writes_timestamp(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """DisTestRes 0->2 (problem): config entry must still be updated."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_0,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    new_status = copy.copy(coordinator.data)
    new_status.dis_test_res = CheckUpResult.PROBLEM
    coordinator.async_set_updated_data(new_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is not None


async def test_dis_test_res_stays_non_zero_no_duplicate_write(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """DisTestRes already non-zero on second update: no timestamp overwrite."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_0,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # First update: 0 -> 1 (listener fires, writes timestamp)
    ok_status = copy.copy(coordinator.data)
    ok_status.dis_test_res = CheckUpResult.OK
    coordinator.async_set_updated_data(ok_status)
    await hass.async_block_till_done()

    first_ts = entry.data.get(CONF_KEY_CHECKUP_LAST_DATE)
    assert first_ts is not None

    # Second update: still 1, no 0->non-zero transition, must NOT overwrite
    still_ok = copy.copy(coordinator.data)
    still_ok.dis_test_res = CheckUpResult.OK
    coordinator.async_set_updated_data(still_ok)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) == first_ts


async def test_dis_test_res_1_to_0_no_write(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """DisTestRes 1→0 (reset/cancel): no timestamp written."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_1,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    new_status = copy.copy(coordinator.data)
    new_status.dis_test_res = CheckUpResult.NOT_RUN
    coordinator.async_set_updated_data(new_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None


async def test_checkup_listener_not_registered_when_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When checkup is disabled, no timestamp is ever written even on transition."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_0,
        **{CONF_KEY_CHECKUP_ENABLED: False},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    new_status = copy.copy(coordinator.data)
    new_status.dis_test_res = CheckUpResult.OK
    coordinator.async_set_updated_data(new_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None


# ---------------------------------------------------------------------------
# Sensor registration
# ---------------------------------------------------------------------------


async def test_checkup_result_sensor_registered_when_enabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_1,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    state = _sensor_state(hass, entry, UNIQUE_ID_WASH_CHECKUP_RESULT)
    assert state is not None
    assert state.state == "ok"


async def test_checkup_result_sensor_not_registered_when_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_1,
        **{CONF_KEY_CHECKUP_ENABLED: False},
    )
    state = _sensor_state(hass, entry, UNIQUE_ID_WASH_CHECKUP_RESULT)
    assert state is None


async def test_checkup_result_sensor_problem(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_2,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    state = _sensor_state(hass, entry, UNIQUE_ID_WASH_CHECKUP_RESULT)
    assert state is not None
    assert state.state == "problem"


async def test_checkup_result_sensor_not_run(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_0,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    state = _sensor_state(hass, entry, UNIQUE_ID_WASH_CHECKUP_RESULT)
    assert state is not None
    assert state.state == "not_run"


async def test_last_checkup_sensor_shows_stored_timestamp(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    ts = _NOW.timestamp()
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_LAST_DATE: ts,
        },
    )
    state = _sensor_state(hass, entry, UNIQUE_ID_WASH_LAST_CHECKUP)
    assert state is not None
    assert state.state not in ("unknown", "unavailable")


async def test_last_checkup_sensor_unknown_when_never_run(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    state = _sensor_state(hass, entry, UNIQUE_ID_WASH_LAST_CHECKUP)
    assert state is not None
    assert state.state in ("unknown", "unavailable")
