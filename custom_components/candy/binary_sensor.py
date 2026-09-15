from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .client.model import WashingMachineStatus
from .const import (
    DATA_KEY_COORDINATOR,
    DOMAIN,
    UNIQUE_ID_WASH_DETERGENT_AUTODOSE,
    UNIQUE_ID_WASH_DETERGENT_WARN,
    UNIQUE_ID_WASH_REMOTE_CONTROL,
    UNIQUE_ID_WASH_SOFTENER_AUTODOSE,
    UNIQUE_ID_WASH_SOFTENER_WARN,
)
from .helpers import wash_device_info


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
):
    """Set up the Candy binary sensors from config entry."""

    config_id = config_entry.entry_id
    coordinator = hass.data[DOMAIN][config_id][DATA_KEY_COORDINATOR]

    if isinstance(coordinator.data, WashingMachineStatus):
        async_add_entities(
            [
                CandyWashRemoteControlBinarySensor(coordinator, config_entry),
                CandyWashDetergentWarningBinarySensor(coordinator, config_entry),
                CandyWashSoftenerWarningBinarySensor(coordinator, config_entry),
                CandyWashDetergentAutodoseBinarySensor(coordinator, config_entry),
                CandyWashSoftenerAutodoseBinarySensor(coordinator, config_entry),
            ]
        )


class CandyWashRemoteControlBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_translation_key = "remote_control"
    _attr_name = "Remote control"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:remote"

    def __init__(self, coordinator: DataUpdateCoordinator, config_entry: ConfigEntry):
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_REMOTE_CONTROL.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)

    @property
    def is_on(self) -> bool | None:
        if not isinstance(self.coordinator.data, WashingMachineStatus):
            return None
        return self.coordinator.data.remote_control


class CandyWashDetergentWarningBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_translation_key = "wash_detergent_warning"
    _attr_name = "Waschmittel leer"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:cup-water"

    def __init__(self, coordinator: DataUpdateCoordinator, config_entry: ConfigEntry):
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_DETERGENT_WARN.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)

    @property
    def is_on(self) -> bool | None:
        if not isinstance(self.coordinator.data, WashingMachineStatus):
            return None
        return self.coordinator.data.detergent_warning


class CandyWashSoftenerWarningBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_translation_key = "wash_softener_warning"
    _attr_name = "Weichspüler leer"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:bottle-tonic-outline"

    def __init__(self, coordinator: DataUpdateCoordinator, config_entry: ConfigEntry):
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_SOFTENER_WARN.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)

    @property
    def is_on(self) -> bool | None:
        if not isinstance(self.coordinator.data, WashingMachineStatus):
            return None
        return self.coordinator.data.softener_warning


class CandyWashDetergentAutodoseBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_translation_key = "wash_detergent_autodose"
    _attr_name = "Auto-Dosierung Waschmittel"
    _attr_icon = "mdi:shampoo"

    def __init__(self, coordinator: DataUpdateCoordinator, config_entry: ConfigEntry):
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_DETERGENT_AUTODOSE.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)

    @property
    def is_on(self) -> bool | None:
        if not isinstance(self.coordinator.data, WashingMachineStatus):
            return None
        return self.coordinator.data.detergent_autodose


class CandyWashSoftenerAutodoseBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_translation_key = "wash_softener_autodose"
    _attr_name = "Auto-Dosierung Weichspüler"
    _attr_icon = "mdi:flower-tulip-outline"

    def __init__(self, coordinator: DataUpdateCoordinator, config_entry: ConfigEntry):
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_SOFTENER_AUTODOSE.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)

    @property
    def is_on(self) -> bool | None:
        if not isinstance(self.coordinator.data, WashingMachineStatus):
            return None
        return self.coordinator.data.softener_autodose

