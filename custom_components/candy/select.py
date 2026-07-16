from __future__ import annotations

from typing import cast

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .client import (
    CandyClient,
    WashingMachineStatus,
    WashingMachineWashProgram,
    parse_wash_programs,
)
from .client.model import MachineState
from .const import (
    CONF_KEY_DEVICE_MODEL,
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAMS,
    CONF_KEY_SERIAL_NUMBER,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DEVICE_NAME_WASHING_MACHINE,
    DOMAIN,
    MODE_FULL_CONTROL,
    SUGGESTED_AREA_BATHROOM,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_SOIL_SELECT,
    UNIQUE_ID_WASH_SPIN_SELECT,
    UNIQUE_ID_WASH_TEMP_SELECT,
)

_TEMP_STEPS = [0, 20, 30, 40, 60, 90]
_SPIN_STEPS = [0, 400, 600, 800, 1000, 1200, 1400]


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
) -> None:
    config_id = config_entry.entry_id

    if config_entry.data.get(CONF_KEY_MODE) != MODE_FULL_CONTROL:
        return

    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][config_id][
        DATA_KEY_COORDINATOR
    ]
    if not isinstance(coordinator.data, WashingMachineStatus):
        return

    client: CandyClient = hass.data[DOMAIN][config_id][DATA_KEY_CLIENT]
    programs = parse_wash_programs(config_entry.data.get(CONF_KEY_PROGRAMS, []))

    temp_select = WashTempSelect(coordinator, config_entry, client, programs)
    spin_select = WashSpinSelect(coordinator, config_entry, client, programs)
    soil_select = WashSoilSelect(coordinator, config_entry, client, programs)
    program_select = WashProgramSelect(
        coordinator,
        config_entry,
        client,
        programs,
        temp_select,
        spin_select,
        soil_select,
    )

    async_add_entities([program_select, temp_select, spin_select, soil_select])


class CandyWashSelectBase(CoordinatorEntity, SelectEntity):
    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id
        self._client = client
        self._programs = programs

    @property
    def device_info(self) -> DeviceInfo:
        info = DeviceInfo(
            identifiers={(DOMAIN, self.config_id)},
            name=DEVICE_NAME_WASHING_MACHINE,
            manufacturer="Candy",
            suggested_area=SUGGESTED_AREA_BATHROOM,
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

    def _current_program(self) -> WashingMachineWashProgram | None:
        status = cast(WashingMachineStatus, self.coordinator.data)
        for p in self._programs:
            if p.position == status.program:
                return p
        return None

    def _machine_is_idle(self) -> bool:
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state in {MachineState.IDLE, MachineState.OFF}


class WashProgramSelect(CandyWashSelectBase):
    _attr_translation_key = "wash_program_select"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
        temp_select: WashTempSelect,
        spin_select: WashSpinSelect,
        soil_select: WashSoilSelect,
    ) -> None:
        super().__init__(coordinator, config_entry, client, programs)
        self._temp_select = temp_select
        self._spin_select = spin_select
        self._soil_select = soil_select
        self._current_option: str | None = None

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_PROGRAM_SELECT.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:washing-machine"

    @property
    def available(self) -> bool:
        return super().available and self._machine_is_idle()

    @property
    def options(self) -> list[str]:
        return [p.name for p in self._programs]

    @property
    def current_option(self) -> str | None:
        if self._current_option is not None:
            return self._current_option
        prog = self._current_program()
        return prog.name if prog else None

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        selected = next((p for p in self._programs if p.name == option), None)
        if selected is None:
            return
        self._temp_select.update_for_program(selected)
        self._spin_select.update_for_program(selected)
        self._soil_select.update_for_program(selected)
        self.async_write_ha_state()
        self._temp_select.async_write_ha_state()
        self._spin_select.async_write_ha_state()
        self._soil_select.async_write_ha_state()


class WashTempSelect(CandyWashSelectBase):
    _attr_translation_key = "wash_temp_select"
    _current_option: str | None = None
    _current_program: WashingMachineWashProgram | None = None  # type: ignore[assignment]

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_TEMP_SELECT.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:thermometer"

    @property
    def available(self) -> bool:
        prog = self._active_program()
        return (
            super().available
            and self._machine_is_idle()
            and prog is not None
            and prog.max_temperature != 255
        )

    @property
    def options(self) -> list[str]:
        prog = self._active_program()
        if prog is None or prog.max_temperature == 255:
            return []
        return [str(t) for t in _TEMP_STEPS if t <= prog.max_temperature]

    @property
    def current_option(self) -> str | None:
        if self._current_option is not None:
            return self._current_option
        prog = self._active_program()
        if prog is None or prog.max_temperature == 255:
            return None
        status = cast(WashingMachineStatus, self.coordinator.data)
        return str(status.temp)

    def update_for_program(self, program: WashingMachineWashProgram) -> None:
        self._current_program = program
        self._current_option = str(program.default_temperature)

    def _active_program(self) -> WashingMachineWashProgram | None:
        if self._current_program is not None:
            return self._current_program
        status = cast(WashingMachineStatus, self.coordinator.data)
        for p in self._programs:
            if p.position == status.program:
                return p
        return None

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        self.async_write_ha_state()


class WashSpinSelect(CandyWashSelectBase):
    _attr_translation_key = "wash_spin_select"
    _current_option: str | None = None
    _current_program: WashingMachineWashProgram | None = None  # type: ignore[assignment]

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_SPIN_SELECT.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:rotate-right"

    @property
    def available(self) -> bool:
        prog = self._active_program()
        return (
            super().available
            and self._machine_is_idle()
            and prog is not None
            and prog.max_spin_speed != 255
        )

    @property
    def options(self) -> list[str]:
        prog = self._active_program()
        if prog is None or prog.max_spin_speed == 255:
            return []
        return [str(s) for s in _SPIN_STEPS if s <= prog.max_spin_speed]

    @property
    def current_option(self) -> str | None:
        if self._current_option is not None:
            return self._current_option
        prog = self._active_program()
        if prog is None or prog.max_spin_speed == 255:
            return None
        status = cast(WashingMachineStatus, self.coordinator.data)
        return str(status.spin_speed)

    def update_for_program(self, program: WashingMachineWashProgram) -> None:
        self._current_program = program
        self._current_option = str(program.default_spin_speed)

    def _active_program(self) -> WashingMachineWashProgram | None:
        if self._current_program is not None:
            return self._current_program
        status = cast(WashingMachineStatus, self.coordinator.data)
        for p in self._programs:
            if p.position == status.program:
                return p
        return None

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        self.async_write_ha_state()


class WashSoilSelect(CandyWashSelectBase):
    _attr_translation_key = "wash_soil_select"
    _current_option: str | None = None
    _current_program: WashingMachineWashProgram | None = None  # type: ignore[assignment]

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_SOIL_SELECT.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:water-opacity"

    @property
    def available(self) -> bool:
        prog = self._active_program()
        if prog is None:
            return False
        return (
            super().available
            and self._machine_is_idle()
            and prog.min_soil_level < prog.max_soil_level
        )

    @property
    def options(self) -> list[str]:
        prog = self._active_program()
        if prog is None or prog.min_soil_level >= prog.max_soil_level:
            return []
        return [str(i) for i in range(prog.min_soil_level, prog.max_soil_level + 1)]

    @property
    def current_option(self) -> str | None:
        if self._current_option is not None:
            return self._current_option
        prog = self._active_program()
        if prog is None or prog.min_soil_level >= prog.max_soil_level:
            return None
        status = cast(WashingMachineStatus, self.coordinator.data)
        if (
            status.soil_level is not None
            and prog.min_soil_level <= status.soil_level <= prog.max_soil_level
        ):
            return str(status.soil_level)
        return str(prog.default_soil_level)

    def update_for_program(self, program: WashingMachineWashProgram) -> None:
        self._current_program = program
        if program.min_soil_level < program.max_soil_level:
            self._current_option = str(program.default_soil_level)
        else:
            self._current_option = None

    def _active_program(self) -> WashingMachineWashProgram | None:
        if self._current_program is not None:
            return self._current_program
        status = cast(WashingMachineStatus, self.coordinator.data)
        for p in self._programs:
            if p.position == status.program:
                return p
        return None

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        self.async_write_ha_state()
