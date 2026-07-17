from abc import abstractmethod
from collections.abc import Mapping
import contextlib
from typing import Any, cast

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfFrequency,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .client import WashingMachineStatus, WashingMachineWashProgram, parse_wash_programs
from .client.model import (
    DishwasherState,
    DishwasherStatus,
    DryerProgramState,
    MachineState,
    OvenStatus,
    TumbleDryerStatus,
    WashingMachineStatistics,
)
from .const import (
    CONF_KEY_DEVICE_MODEL,
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    CONF_KEY_SERIAL_NUMBER,
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
    DEVICE_NAME_DISHWASHER,
    DEVICE_NAME_OVEN,
    DEVICE_NAME_TUMBLE_DRYER,
    DEVICE_NAME_WASHING_MACHINE,
    DOMAIN,
    MODE_FULL_CONTROL,
    SOIL_LABELS,
    SOIL_LABELS_REVERSE,
    SUGGESTED_AREA_BATHROOM,
    SUGGESTED_AREA_KITCHEN,
    UNIQUE_ID_DISHWASHER,
    UNIQUE_ID_DISHWASHER_PROGRAM,
    UNIQUE_ID_DISHWASHER_REMAINING_TIME,
    UNIQUE_ID_OVEN,
    UNIQUE_ID_OVEN_PROGRAM,
    UNIQUE_ID_OVEN_TEMP,
    UNIQUE_ID_TUMBLE_CYCLE_STATUS,
    UNIQUE_ID_TUMBLE_DRYER,
    UNIQUE_ID_TUMBLE_PROGRAM,
    UNIQUE_ID_TUMBLE_REMAINING_TIME,
    UNIQUE_ID_WASH_CHECK_UP,
    UNIQUE_ID_WASH_CYCLE_STATUS,
    UNIQUE_ID_WASH_DELAY,
    UNIQUE_ID_WASH_ERROR,
    UNIQUE_ID_WASH_ESTIMATED_DURATION,
    UNIQUE_ID_WASH_FILL_PERCENT,
    UNIQUE_ID_WASH_MOTOR_FREQ,
    UNIQUE_ID_WASH_NTC_DRUM,
    UNIQUE_ID_WASH_NTC_WATER,
    UNIQUE_ID_WASH_PROGRAM,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_REMAINING_TIME,
    UNIQUE_ID_WASH_SOIL_LEVEL,
    UNIQUE_ID_WASH_SOIL_SELECT,
    UNIQUE_ID_WASH_SPIN_SPEED,
    UNIQUE_ID_WASH_TEMPERATURE,
    UNIQUE_ID_WASH_TOTAL_CYCLES,
    UNIQUE_ID_WASHING_MACHINE,
)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
):
    """Set up the Candy sensors from config entry."""

    config_id = config_entry.entry_id
    coordinator = hass.data[DOMAIN][config_id][DATA_KEY_COORDINATOR]

    if isinstance(coordinator.data, WashingMachineStatus):
        status = coordinator.data
        entities: list[CandyBaseSensor] = [
            CandyWashingMachineSensor(coordinator, config_entry),
            CandyWashProgramSensor(coordinator, config_entry),
            CandyWashCycleStatusSensor(coordinator, config_entry),
            CandyWashRemainingTimeSensor(coordinator, config_entry),
            CandyWashTemperatureSensor(coordinator, config_entry),
            CandyWashSpinSpeedSensor(coordinator, config_entry),
            CandyWashErrorSensor(coordinator, config_entry),
        ]
        registry = er.async_get(hass)

        def _was_registered(unique_id_template: str) -> bool:
            return (
                registry.async_get_entity_id(
                    "sensor", DOMAIN, unique_id_template.format(config_id)
                )
                is not None
            )

        if status.fill_percent is not None or _was_registered(
            UNIQUE_ID_WASH_FILL_PERCENT
        ):
            entities.append(CandyWashFillPercentSensor(coordinator, config_entry))
        if status.delay_value is not None or _was_registered(UNIQUE_ID_WASH_DELAY):
            entities.append(CandyWashDelaySensor(coordinator, config_entry))
        if status.ntc_water is not None or _was_registered(UNIQUE_ID_WASH_NTC_WATER):
            entities.append(CandyWashNtcWaterSensor(coordinator, config_entry))
        if status.ntc_drum is not None or _was_registered(UNIQUE_ID_WASH_NTC_DRUM):
            entities.append(CandyWashNtcDrumSensor(coordinator, config_entry))
        if status.motor_speed_freq is not None or _was_registered(
            UNIQUE_ID_WASH_MOTOR_FREQ
        ):
            entities.append(CandyWashMotorFreqSensor(coordinator, config_entry))
        if status.check_up_state is not None or _was_registered(
            UNIQUE_ID_WASH_CHECK_UP
        ):
            entities.append(CandyWashCheckUpSensor(coordinator, config_entry))
        if status.soil_level is not None or _was_registered(UNIQUE_ID_WASH_SOIL_LEVEL):
            entities.append(CandyWashSoilLevelSensor(coordinator, config_entry))
        programs = parse_wash_programs(config_entry.data.get(CONF_KEY_PROGRAMS, []))
        if programs:
            entities.append(
                CandyWashEstimatedDurationSensor(coordinator, config_entry, programs)
            )
        stats_coordinator = hass.data[DOMAIN][config_id].get(DATA_KEY_STATS_COORDINATOR)
        if stats_coordinator is not None:
            entities.append(CandyWashTotalCyclesSensor(stats_coordinator, config_entry))
        async_add_entities(entities)
    elif isinstance(coordinator.data, TumbleDryerStatus):
        async_add_entities(
            [
                CandyTumbleDryerSensor(coordinator, config_entry),
                CandyTumbleProgramSensor(coordinator, config_entry),
                CandyTumbleStatusSensor(coordinator, config_entry),
                CandyTumbleRemainingTimeSensor(coordinator, config_entry),
            ]
        )
    elif isinstance(coordinator.data, OvenStatus):
        async_add_entities(
            [
                CandyOvenSensor(coordinator, config_entry),
                CandyOvenProgramSensor(coordinator, config_entry),
                CandyOvenTempSensor(coordinator, config_entry),
            ]
        )
    elif isinstance(coordinator.data, DishwasherStatus):
        async_add_entities(
            [
                CandyDishwasherSensor(coordinator, config_entry),
                CandyDishwasherProgramSensor(coordinator, config_entry),
                CandyDishwasherRemainingTimeSensor(coordinator, config_entry),
            ]
        )
    else:
        raise TypeError(f"Unable to determine machine type: {coordinator.data}")


class CandyBaseSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator: DataUpdateCoordinator, config_entry: ConfigEntry):
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id

    @property
    def device_info(self) -> DeviceInfo:
        info = DeviceInfo(
            identifiers={(DOMAIN, self.config_id)},
            name=self.device_name(),
            manufacturer="Candy",
            suggested_area=self.suggested_area(),
        )
        if self.config_entry.data.get(CONF_KEY_MAC_ADDRESS):
            info["connections"] = {
                (
                    dr.CONNECTION_NETWORK_MAC,
                    self.config_entry.data[CONF_KEY_MAC_ADDRESS],
                )
            }
        if self.config_entry.data.get(CONF_KEY_MODE) == MODE_FULL_CONTROL:
            if self.config_entry.data.get(CONF_KEY_DEVICE_MODEL):
                info["model"] = self.config_entry.data[CONF_KEY_DEVICE_MODEL]
            if self.config_entry.data.get(CONF_KEY_SERIAL_NUMBER):
                info["serial_number"] = self.config_entry.data[CONF_KEY_SERIAL_NUMBER]
        return info

    @abstractmethod
    def device_name(self) -> str:
        pass

    @abstractmethod
    def suggested_area(self) -> str:
        pass


class CandyWashingMachineSensor(CandyBaseSensor):
    _attr_translation_key = "washing_machine"
    _attr_name = "Washing machine"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASHING_MACHINE.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(WashingMachineStatus, self.coordinator.data)
        return str(status.machine_state)

    @property
    def icon(self) -> str:
        return "mdi:washing-machine"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        status = cast(WashingMachineStatus, self.coordinator.data)

        attributes = {
            "program": status.program,
            "temperature": status.temp,
            "spin_speed": status.spin_speed,
            "remaining_minutes": status.remaining_minutes
            if status.machine_state in [MachineState.RUNNING, MachineState.PAUSED]
            else 0,
            "remote_control": status.remote_control,
        }

        if status.fill_percent is not None:
            attributes["fill_percent"] = status.fill_percent

        if status.program_code is not None:
            attributes["program_code"] = status.program_code

        return attributes


class CandyWashProgramSensor(CandyBaseSensor):
    _attr_translation_key = "wash_program"
    _attr_name = "Wash program"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_PROGRAM.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(WashingMachineStatus, self.coordinator.data)
        raw = self.config_entry.data.get(CONF_KEY_PROGRAMS)
        if raw:
            programs = parse_wash_programs(raw)
            match = next(
                (p for p in programs if p.selector_position == status.program), None
            )
            if match is not None:
                lang = self.config_entry.data.get(
                    CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
                )
                return match.localized_name(lang)
        return status.program

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        status = cast(WashingMachineStatus, self.coordinator.data)
        if status.program_code is not None:
            return {"program_code": status.program_code}
        return {}

    @property
    def icon(self) -> str:
        return "mdi:washing-machine"


class CandyWashCycleStatusSensor(CandyBaseSensor):
    _attr_translation_key = "wash_cycle_status"
    _attr_name = "Wash cycle status"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_CYCLE_STATUS.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(WashingMachineStatus, self.coordinator.data)
        return str(status.program_state)

    @property
    def icon(self) -> str:
        return "mdi:washing-machine"


class CandyWashRemainingTimeSensor(CandyBaseSensor):
    _attr_translation_key = "wash_remaining_time"
    _attr_name = "Wash cycle remaining time"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_REMAINING_TIME.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(WashingMachineStatus, self.coordinator.data)
        if status.machine_state in [MachineState.RUNNING, MachineState.PAUSED]:
            return status.remaining_minutes
        return 0

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTime.MINUTES

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.DURATION

    @property
    def icon(self) -> str:
        return "mdi:progress-clock"


class CandyWashTemperatureSensor(CandyBaseSensor):
    """Set temperature selected on the washing machine."""

    _attr_translation_key = "wash_temperature"
    _attr_name = "Wash temperature"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_TEMPERATURE.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).temp

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTemperature.CELSIUS

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.TEMPERATURE

    @property
    def icon(self) -> str:
        return "mdi:thermometer"


class CandyWashSpinSpeedSensor(CandyBaseSensor):
    """Spin speed selected on the washing machine."""

    _attr_translation_key = "wash_spin_speed"
    _attr_name = "Wash spin speed"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_SPIN_SPEED.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).spin_speed

    @property
    def native_unit_of_measurement(self) -> str:
        return "rpm"

    @property
    def icon(self) -> str:
        return "mdi:rotate-right"


class CandyWashFillPercentSensor(CandyBaseSensor):
    """Water fill level in the drum (0-100%)."""

    _attr_translation_key = "wash_fill_level"
    _attr_name = "Wash fill level"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_FILL_PERCENT.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).fill_percent

    @property
    def native_unit_of_measurement(self) -> str:
        return PERCENTAGE

    @property
    def icon(self) -> str:
        return "mdi:water-percent"


class CandyWashErrorSensor(CandyBaseSensor):
    """Error code reported by the washing machine (0 = no error)."""

    _attr_translation_key = "wash_error_code"
    _attr_name = "Wash error code"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_ERROR.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).error

    @property
    def icon(self) -> str:
        return "mdi:alert-circle-outline"


class CandyWashDelaySensor(CandyBaseSensor):
    """Delay start value set on the washing machine."""

    _attr_translation_key = "wash_delay_start"
    _attr_name = "Wash delay start"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_DELAY.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).delay_value

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTime.MINUTES

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.DURATION

    @property
    def icon(self) -> str:
        return "mdi:timer-sand"


class CandyWashNtcWaterSensor(CandyBaseSensor):
    """Raw NTC water temperature sensor reading."""

    _attr_translation_key = "wash_ntc_water"
    _attr_name = "Wash NTC water"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_NTC_WATER.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).ntc_water

    @property
    def icon(self) -> str:
        return "mdi:thermometer-water"


class CandyWashNtcDrumSensor(CandyBaseSensor):
    """Raw NTC drum temperature sensor reading."""

    _attr_translation_key = "wash_ntc_drum"
    _attr_name = "Wash NTC drum"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_NTC_DRUM.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).ntc_drum

    @property
    def icon(self) -> str:
        return "mdi:thermometer"


class CandyWashMotorFreqSensor(CandyBaseSensor):
    """Motor APS frequency reported by the washing machine."""

    _attr_translation_key = "wash_motor_frequency"
    _attr_name = "Wash motor frequency"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_MOTOR_FREQ.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).motor_speed_freq

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfFrequency.HERTZ

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.FREQUENCY

    @property
    def icon(self) -> str:
        return "mdi:sine-wave"


class CandyWashCheckUpSensor(CandyBaseSensor, RestoreSensor):
    """Check-up state reported by the washing machine (0 = ok, non-zero = service due)."""

    _attr_translation_key = "wash_maintenance"
    _attr_name = "Wash maintenance"
    _restored_state: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            if last.native_value in ("Ok", "Service due"):
                self._restored_state = str(last.native_value)

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_CHECK_UP.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        state = cast(WashingMachineStatus, self.coordinator.data).check_up_state
        if state is not None:
            return str(state)
        return self._restored_state

    @property
    def icon(self) -> str:
        return "mdi:wrench-check"


class CandyWashSoilLevelSensor(CandyBaseSensor):
    """Current stain level reported by the washing machine."""

    _attr_translation_key = "wash_soil_level"
    _attr_name = "Wash stain level"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(SOIL_LABELS.values())

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_SOIL_LEVEL.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        level = cast(WashingMachineStatus, self.coordinator.data).soil_level
        return SOIL_LABELS.get(level) if level is not None else None

    @property
    def icon(self) -> str:
        return "mdi:water-opacity"


class CandyWashTotalCyclesSensor(CandyBaseSensor, RestoreSensor):
    """Total number of wash cycles completed by the washing machine."""

    _attr_translation_key = "wash_total_cycles"
    _attr_name = "Wash total cycles"
    _restored_cycles: int | None = None
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            with contextlib.suppress(TypeError, ValueError):
                self._restored_cycles = int(str(last.native_value))

    @property
    def available(self) -> bool:
        return super().available or self._restored_cycles is not None

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_TOTAL_CYCLES.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        if self.coordinator.data is not None:
            return cast(WashingMachineStatistics, self.coordinator.data).total_cycles
        return self._restored_cycles

    @property
    def icon(self) -> str:
        return "mdi:counter"


class CandyWashEstimatedDurationSensor(CandyBaseSensor):
    """Estimated cycle duration based on the selected program and soil level."""

    _attr_translation_key = "wash_estimated_duration"
    _attr_name = "Estimated cycle duration"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        programs: list[WashingMachineWashProgram],
    ) -> None:
        super().__init__(coordinator, config_entry)
        self._programs = programs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        registry = er.async_get(self.hass)
        watch_ids = []
        for uid in (UNIQUE_ID_WASH_PROGRAM_SELECT, UNIQUE_ID_WASH_SOIL_SELECT):
            eid = registry.async_get_entity_id(
                "select", DOMAIN, uid.format(self.config_id)
            )
            if eid:
                watch_ids.append(eid)
        if watch_ids:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, watch_ids, self._on_select_changed
                )
            )

    @callback
    def _on_select_changed(self, event) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state == MachineState.IDLE

    @property
    def native_value(self) -> StateType:
        registry = er.async_get(self.hass)

        prog_eid = registry.async_get_entity_id(
            "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(self.config_id)
        )
        prog_state = self.hass.states.get(prog_eid) if prog_eid else None
        if prog_state is not None and prog_state.state not in (
            "unavailable",
            "unknown",
        ):
            program = next(
                (
                    p
                    for p in self._programs
                    if p.localized_name(
                        self.config_entry.data.get(
                            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
                        )
                    )
                    == prog_state.state
                ),
                None,
            )
        else:
            status = cast(WashingMachineStatus, self.coordinator.data)
            program = next(
                (p for p in self._programs if p.selector_position == status.program),
                None,
            )

        if program is None:
            return None

        if program.min_soil_level < program.max_soil_level:
            soil_eid = registry.async_get_entity_id(
                "select", DOMAIN, UNIQUE_ID_WASH_SOIL_SELECT.format(self.config_id)
            )
            soil_state = self.hass.states.get(soil_eid) if soil_eid else None
            if soil_state is not None and soil_state.state not in (
                "unavailable",
                "unknown",
            ):
                try:
                    soil = SOIL_LABELS_REVERSE[soil_state.state]
                except KeyError:
                    soil = program.default_soil_level
            else:
                device_status = cast(WashingMachineStatus, self.coordinator.data)
                if (
                    device_status.soil_level is not None
                    and program.min_soil_level
                    <= device_status.soil_level
                    <= program.max_soil_level
                ):
                    soil = device_status.soil_level
                else:
                    soil = program.default_soil_level

            if soil <= 1:
                minutes = program.duration_soil_min
            elif soil == 2:
                minutes = program.duration_soil_medium
            else:
                minutes = program.duration_soil_max
        else:
            minutes = program.default_duration

        return minutes if minutes > 0 else None

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTime.MINUTES

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.DURATION

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_ESTIMATED_DURATION.format(self.config_id)

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def icon(self) -> str:
        return "mdi:timer-outline"


class CandyTumbleDryerSensor(CandyBaseSensor):
    _attr_translation_key = "tumble_dryer"
    _attr_name = "Tumble dryer"

    def device_name(self) -> str:
        return DEVICE_NAME_TUMBLE_DRYER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_DRYER.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(TumbleDryerStatus, self.coordinator.data)
        return str(status.machine_state)

    @property
    def icon(self) -> str:
        return "mdi:tumble-dryer"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        status = cast(TumbleDryerStatus, self.coordinator.data)

        attributes = {
            "program": status.program,
            "remaining_minutes": status.remaining_minutes,
            "remote_control": status.remote_control,
            "dry_level": status.dry_level,
            "dry_level_now": status.dry_level_selected,
            "refresh": status.refresh,
            "need_clean_filter": status.need_clean_filter,
            "water_tank_full": status.water_tank_full,
            "door_closed": status.door_closed,
        }

        return attributes


class CandyTumbleProgramSensor(CandyBaseSensor):
    _attr_translation_key = "tumble_program"
    _attr_name = "Dryer program"

    def device_name(self) -> str:
        return DEVICE_NAME_TUMBLE_DRYER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_PROGRAM.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(TumbleDryerStatus, self.coordinator.data)
        return status.program

    @property
    def icon(self) -> str:
        return "mdi:tumble-dryer"


class CandyTumbleStatusSensor(CandyBaseSensor):
    _attr_translation_key = "tumble_cycle_status"
    _attr_name = "Dryer cycle status"

    def device_name(self) -> str:
        return DEVICE_NAME_TUMBLE_DRYER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_CYCLE_STATUS.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(TumbleDryerStatus, self.coordinator.data)
        if status.program_state in [DryerProgramState.STOPPED]:
            return str(status.cycle_state)
        return str(status.program_state)

    @property
    def icon(self) -> str:
        return "mdi:tumble-dryer"


class CandyTumbleRemainingTimeSensor(CandyBaseSensor):
    _attr_translation_key = "tumble_remaining_time"
    _attr_name = "Dryer cycle remaining time"

    def device_name(self) -> str:
        return DEVICE_NAME_TUMBLE_DRYER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_REMAINING_TIME.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(TumbleDryerStatus, self.coordinator.data)
        if status.machine_state in [MachineState.RUNNING, MachineState.PAUSED]:
            return status.remaining_minutes
        return 0

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTime.MINUTES

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.DURATION

    @property
    def icon(self) -> str:
        return "mdi:progress-clock"


class CandyOvenSensor(CandyBaseSensor):
    _attr_translation_key = "oven"
    _attr_name = "Oven"

    def device_name(self) -> str:
        return DEVICE_NAME_OVEN

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_OVEN.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(OvenStatus, self.coordinator.data)
        return str(status.machine_state)

    @property
    def icon(self) -> str:
        return "mdi:stove"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        status = cast(OvenStatus, self.coordinator.data)

        attributes = {
            "program": status.program,
            "selection": status.selection,
            "temperature": status.temp,
            "temperature_reached": status.temp_reached,
            "remote_control": status.remote_control,
        }

        if status.program_length_minutes is not None:
            attributes["program_length_minutes"] = status.program_length_minutes

        return attributes


class CandyOvenProgramSensor(CandyBaseSensor):
    _attr_translation_key = "oven_program"
    _attr_name = "Oven program"

    def device_name(self) -> str:
        return DEVICE_NAME_OVEN

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_OVEN_PROGRAM.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(OvenStatus, self.coordinator.data)
        return status.program

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        status = cast(OvenStatus, self.coordinator.data)
        return {"selection": status.selection}

    @property
    def icon(self) -> str:
        return "mdi:stove"


class CandyOvenTempSensor(CandyBaseSensor):
    _attr_translation_key = "oven_temperature"
    _attr_name = "Oven temperature"

    def device_name(self) -> str:
        return DEVICE_NAME_OVEN

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_OVEN_TEMP.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(OvenStatus, self.coordinator.data)
        return status.temp

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTemperature.CELSIUS

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.TEMPERATURE

    @property
    def icon(self) -> str:
        return "mdi:thermometer"


class CandyDishwasherSensor(CandyBaseSensor):
    _attr_translation_key = "dishwasher"
    _attr_name = "Dishwasher"

    def device_name(self) -> str:
        return DEVICE_NAME_DISHWASHER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_DISHWASHER.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(DishwasherStatus, self.coordinator.data)
        return str(status.machine_state)

    @property
    def icon(self) -> str:
        return "mdi:glass-wine"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        status = cast(DishwasherStatus, self.coordinator.data)

        attributes = {
            "program": status.program,
            "remaining_minutes": 0
            if status.machine_state in [DishwasherState.IDLE, DishwasherState.FINISHED]
            else status.remaining_minutes,
            "remote_control": status.remote_control,
            "door_open": status.door_open,
            "eco_mode": status.eco_mode,
            "salt_empty": status.salt_empty,
            "rinse_aid_empty": status.rinse_aid_empty,
        }

        if status.door_open_allowed is not None:
            attributes["door_open_allowed"] = status.door_open_allowed

        if status.delayed_start_hours is not None:
            attributes["delayed_start_hours"] = status.delayed_start_hours

        return attributes


class CandyDishwasherProgramSensor(CandyBaseSensor):
    _attr_translation_key = "dishwasher_program"
    _attr_name = "Dishwasher program"

    def device_name(self) -> str:
        return DEVICE_NAME_DISHWASHER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_DISHWASHER_PROGRAM.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(DishwasherStatus, self.coordinator.data)
        return status.program

    @property
    def icon(self) -> str:
        return "mdi:glass-wine"


class CandyDishwasherRemainingTimeSensor(CandyBaseSensor):
    _attr_translation_key = "dishwasher_remaining_time"
    _attr_name = "Dishwasher remaining time"

    def device_name(self) -> str:
        return DEVICE_NAME_DISHWASHER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_DISHWASHER_REMAINING_TIME.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(DishwasherStatus, self.coordinator.data)
        if status.machine_state in [DishwasherState.IDLE, DishwasherState.FINISHED]:
            return 0
        return status.remaining_minutes

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTime.MINUTES

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.DURATION

    @property
    def icon(self) -> str:
        return "mdi:progress-clock"
