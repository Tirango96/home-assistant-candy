from __future__ import annotations

from typing import cast

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .client import (
    CandyClient,
    NfcProgram,
    WashingMachineStatus,
    WashingMachineWashProgram,
    load_nfc_programs,
    parse_wash_programs,
)
from .client.model import MachineState
from .const import (
    CONF_KEY_DEVICE_MODEL,
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    CONF_KEY_SERIAL_NUMBER,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DEVICE_NAME_WASHING_MACHINE,
    DOMAIN,
    MODE_FULL_CONTROL,
    NFC_CLUSTER_TO_PROGRAM,
    SOIL_LABELS,
    SUGGESTED_AREA_BATHROOM,
    UNIQUE_ID_WASH_NFC_SWITCH,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_SOIL_SELECT,
    UNIQUE_ID_WASH_SPIN_SELECT,
    UNIQUE_ID_WASH_TEMP_SELECT,
)

_TEMP_STEPS = [0, 20, 30, 40, 60, 90]
_SPIN_STEPS = [0, 400, 600, 800, 1000, 1200, 1400]


def _resolve_nfc_programs(
    nfc_list: list[NfcProgram],
    standard_programs: list[WashingMachineWashProgram],
) -> list[tuple[NfcProgram, WashingMachineWashProgram]]:
    result = []
    for nfc in nfc_list:
        patterns = NFC_CLUSTER_TO_PROGRAM.get(nfc.output_cluster, [])
        base = next(
            (p for pattern in patterns for p in standard_programs if pattern in p.name),
            None,
        )
        if base is not None and base.default_duration > 0:
            nfc.duration = base.default_duration
            result.append((nfc, base))
    return result


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

    nfc_entries = _resolve_nfc_programs(load_nfc_programs(), programs)

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
        nfc_entries,
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

    def _program_name(self, program: WashingMachineWashProgram) -> str:
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        return program.localized_name(lang)

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
            if p.selector_position == status.program:
                return p
        return None

    def _machine_is_idle(self) -> bool:
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state in {MachineState.IDLE, MachineState.OFF}


class WashProgramSelect(CandyWashSelectBase):
    _attr_name = "Wash program"
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
        nfc_entries: list[tuple[NfcProgram, WashingMachineWashProgram]],
    ) -> None:
        super().__init__(coordinator, config_entry, client, programs)
        self._temp_select = temp_select
        self._spin_select = spin_select
        self._soil_select = soil_select
        self._nfc_entries = nfc_entries
        self._current_option: str | None = None

    def _nfc_enabled(self) -> bool:
        registry = er.async_get(self.hass)
        nfc_switch_id = registry.async_get_entity_id(
            "switch", DOMAIN, UNIQUE_ID_WASH_NFC_SWITCH.format(self.config_id)
        )
        if nfc_switch_id is None:
            return False
        state = self.hass.states.get(nfc_switch_id)
        return state is not None and state.state == "on"

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
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        standard = [self._program_name(p) for p in self._programs]
        if not self._nfc_enabled():
            return standard
        nfc = [nfc.category_prefixed(lang) for nfc, _ in self._nfc_entries]
        return standard + nfc

    @property
    def current_option(self) -> str | None:
        if self._current_option is not None:
            return self._current_option
        prog = self._current_program()
        return self._program_name(prog) if prog else None

    @property
    def extra_state_attributes(self) -> dict | None:
        option = self.current_option
        if option is None:
            return None
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        nfc_match = next(
            (
                nfc
                for nfc, _ in self._nfc_entries
                if nfc.category_prefixed(lang) == option
            ),
            None,
        )
        if nfc_match is not None and nfc_match.duration:
            return {"duration_minutes": nfc_match.duration}
        return None

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        nfc_match = next(
            (
                nfc
                for nfc, _ in self._nfc_entries
                if nfc.category_prefixed(lang) == option
            ),
            None,
        )
        if nfc_match is not None:
            self._temp_select.update_for_program(None)
            self._spin_select.update_for_program(None)
            self._soil_select.update_for_program(None)
        else:
            selected = next(
                (p for p in self._programs if self._program_name(p) == option), None
            )
            if selected is not None:
                self._temp_select.update_for_program(selected)
                self._spin_select.update_for_program(selected)
                self._soil_select.update_for_program(selected)
        self.async_write_ha_state()
        self._temp_select.async_write_ha_state()
        self._spin_select.async_write_ha_state()
        self._soil_select.async_write_ha_state()


class WashTempSelect(CandyWashSelectBase):
    _attr_name = "Wash temperature"
    _attr_translation_key = "wash_temp_select"
    _current_option: str | None = None
    _current_program: WashingMachineWashProgram | None = None  # type: ignore[assignment]
    _nfc_active: bool = False

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_TEMP_SELECT.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:thermometer"

    @property
    def available(self) -> bool:
        if self._nfc_active:
            return False
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

    def update_for_program(self, program: WashingMachineWashProgram | None) -> None:
        self._nfc_active = program is None
        self._current_program = program
        self._current_option = (
            str(program.default_temperature) if program is not None else None
        )

    def _active_program(self) -> WashingMachineWashProgram | None:
        if self._current_program is not None:
            return self._current_program
        status = cast(WashingMachineStatus, self.coordinator.data)
        for p in self._programs:
            if p.selector_position == status.program:
                return p
        return None

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        self.async_write_ha_state()


class WashSpinSelect(CandyWashSelectBase):
    _attr_name = "Wash spin speed"
    _attr_translation_key = "wash_spin_select"
    _current_option: str | None = None
    _current_program: WashingMachineWashProgram | None = None  # type: ignore[assignment]
    _nfc_active: bool = False

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_SPIN_SELECT.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:rotate-right"

    @property
    def available(self) -> bool:
        if self._nfc_active:
            return False
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

    def update_for_program(self, program: WashingMachineWashProgram | None) -> None:
        self._nfc_active = program is None
        self._current_program = program
        self._current_option = (
            str(program.default_spin_speed) if program is not None else None
        )

    def _active_program(self) -> WashingMachineWashProgram | None:
        if self._current_program is not None:
            return self._current_program
        status = cast(WashingMachineStatus, self.coordinator.data)
        for p in self._programs:
            if p.selector_position == status.program:
                return p
        return None

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        self.async_write_ha_state()


class WashSoilSelect(CandyWashSelectBase):
    _attr_name = "Wash stain level"
    _attr_translation_key = "wash_soil_select"
    _current_option: str | None = None
    _current_program: WashingMachineWashProgram | None = None  # type: ignore[assignment]
    _nfc_active: bool = False

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_SOIL_SELECT.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:water-opacity"

    @property
    def available(self) -> bool:
        if self._nfc_active:
            return False
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
        return [
            SOIL_LABELS[i]
            for i in range(prog.min_soil_level, prog.max_soil_level + 1)
            if i in SOIL_LABELS
        ]

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
            return SOIL_LABELS.get(status.soil_level)
        return SOIL_LABELS.get(prog.default_soil_level)

    def update_for_program(self, program: WashingMachineWashProgram | None) -> None:
        self._nfc_active = program is None
        self._current_program = program
        if program is not None and program.min_soil_level < program.max_soil_level:
            self._current_option = SOIL_LABELS.get(program.default_soil_level)
        else:
            self._current_option = None

    def _active_program(self) -> WashingMachineWashProgram | None:
        if self._current_program is not None:
            return self._current_program
        status = cast(WashingMachineStatus, self.coordinator.data)
        for p in self._programs:
            if p.selector_position == status.program:
                return p
        return None

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        self.async_write_ha_state()
