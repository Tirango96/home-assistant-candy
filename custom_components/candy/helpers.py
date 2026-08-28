from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo

from .client.model import WashingMachineStatus
from .const import (
    CONF_KEY_DEVICE_MODEL,
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_MODE,
    CONF_KEY_PURCHASE_DATE,
    CONF_KEY_SERIAL_NUMBER,
    DEVICE_NAME_WASHING_MACHINE,
    DOMAIN,
    MODE_FULL_CONTROL,
    SUGGESTED_AREA_BATHROOM,
)


def remote_control_enabled(data: object) -> bool:
    """Return True when the washing machine accepts remote commands."""
    return isinstance(data, WashingMachineStatus) and data.remote_control


def cycles_remaining(total: int, last_reset: int, threshold: int) -> int:
    """Return cycles until next maintenance alert, or 0 when due (including overdue).

    Returns 0 for any elapsed >= threshold so notifications fire on every wash
    until the user manually resets the counter.
    """
    elapsed = total - last_reset
    if elapsed <= 0:
        return threshold
    if elapsed >= threshold:
        return 0
    return threshold - elapsed


def wash_device_info(config_entry: ConfigEntry) -> DeviceInfo:
    info = DeviceInfo(
        identifiers={(DOMAIN, config_entry.entry_id)},
        name=DEVICE_NAME_WASHING_MACHINE,
        manufacturer="Candy",
        suggested_area=SUGGESTED_AREA_BATHROOM,
    )
    if config_entry.data.get(CONF_KEY_MAC_ADDRESS):
        info["connections"] = {
            (
                dr.CONNECTION_NETWORK_MAC,
                config_entry.data[CONF_KEY_MAC_ADDRESS],
            )
        }
    if config_entry.data.get(CONF_KEY_MODE) == MODE_FULL_CONTROL:
        if config_entry.data.get(CONF_KEY_DEVICE_MODEL):
            info["model"] = config_entry.data[CONF_KEY_DEVICE_MODEL]
        if config_entry.data.get(CONF_KEY_SERIAL_NUMBER):
            info["serial_number"] = config_entry.data[CONF_KEY_SERIAL_NUMBER]
        if config_entry.data.get(CONF_KEY_PURCHASE_DATE):
            info["hw_version"] = config_entry.data[CONF_KEY_PURCHASE_DATE]
    return info
