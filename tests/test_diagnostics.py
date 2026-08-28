"""Tests for the diagnostics platform."""

from unittest.mock import MagicMock

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.candy.const import (
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_SERIAL_NUMBER,
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
    DOMAIN,
)
from custom_components.candy.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_happy_path(hass):
    """Both coordinators present — sensitive fields are redacted."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="diag-happy",
        data={
            CONF_IP_ADDRESS: "192.168.0.10",
            CONF_PASSWORD: "secret",
            CONF_KEY_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
            CONF_KEY_SERIAL_NUMBER: "SN12345",
        },
    )
    entry.add_to_hass(hass)

    coordinator = MagicMock()
    coordinator.data = {"machine_state": "idle"}
    stats_coordinator = MagicMock()
    stats_coordinator.data = {"total_cycles": 42}

    hass.data[DOMAIN] = {
        entry.entry_id: {
            DATA_KEY_COORDINATOR: coordinator,
            DATA_KEY_STATS_COORDINATOR: stats_coordinator,
        }
    }

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["coordinator_data"] == {"machine_state": "idle"}
    assert result["stats_coordinator_data"] == {"total_cycles": 42}
    config_data = result["config_entry"]
    assert config_data[CONF_IP_ADDRESS] == "**REDACTED**"
    assert config_data[CONF_PASSWORD] == "**REDACTED**"
    assert config_data[CONF_KEY_MAC_ADDRESS] == "**REDACTED**"
    assert config_data[CONF_KEY_SERIAL_NUMBER] == "**REDACTED**"


async def test_diagnostics_no_stats_coordinator(hass):
    """Stats coordinator absent — stats_coordinator_data is None."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="diag-no-stats", data={})
    entry.add_to_hass(hass)

    coordinator = MagicMock()
    coordinator.data = {"machine_state": "running"}

    hass.data[DOMAIN] = {entry.entry_id: {DATA_KEY_COORDINATOR: coordinator}}

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["coordinator_data"] == {"machine_state": "running"}
    assert result["stats_coordinator_data"] is None


async def test_diagnostics_coordinators_none_data(hass):
    """Coordinators present but data is None — both data fields are None."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="diag-none-data", data={})
    entry.add_to_hass(hass)

    coordinator = MagicMock()
    coordinator.data = None
    stats_coordinator = MagicMock()
    stats_coordinator.data = None

    hass.data[DOMAIN] = {
        entry.entry_id: {
            DATA_KEY_COORDINATOR: coordinator,
            DATA_KEY_STATS_COORDINATOR: stats_coordinator,
        }
    }

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["coordinator_data"] is None
    assert result["stats_coordinator_data"] is None
