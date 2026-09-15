"""Diagnostics platform for candy."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import (
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_SERIAL_NUMBER,
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
    DOMAIN,
)

TO_REDACT = {
    CONF_PASSWORD,
    CONF_IP_ADDRESS,
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_SERIAL_NUMBER,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for the config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    coordinator = data.get(DATA_KEY_COORDINATOR)
    stats_coordinator = data.get(DATA_KEY_STATS_COORDINATOR)

    return {
        "config_entry": async_redact_data(entry.data, TO_REDACT),
        "coordinator_data": coordinator.data if coordinator else None,
        "stats_coordinator_data": stats_coordinator.data if stats_coordinator else None,
    }
