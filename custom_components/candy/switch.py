from __future__ import annotations

import functools
import operator
from typing import cast

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
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
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    CONF_KEY_SERIAL_NUMBER,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DEVICE_NAME_WASHING_MACHINE,
    DOMAIN,
    MODE_FULL_CONTROL,
    SUGGESTED_AREA_BATHROOM,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_STEAM_SWITCH,
    WASH_OPTIONS,
)


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

    entities: list[_WashSwitchBase] = []

    if any(p.steam for p in programs):
        entities.append(WashSteamSwitch(coordinator, config_entry, client, programs))

    appliance_options = functools.reduce(
        operator.or_, (p.available_options for p in programs), 0
    )
    for bitmask, translation_key, uid_suffix in WASH_OPTIONS:
        if appliance_options & bitmask:
            entities.append(
                WashOptionSwitch(
                    coordinator,
                    config_entry,
                    client,
                    programs,
                    bitmask,
                    translation_key,
                    uid_suffix,
                )
            )

    async_add_entities(entities)


class _WashSwitchBase(CoordinatorEntity, SwitchEntity):
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

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(
            "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(self.config_id)
        )
        if entity_id is not None:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [entity_id], self._on_program_changed
                )
            )

    @callback
    def _on_program_changed(self, event) -> None:
        self.async_write_ha_state()

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

    def _active_program(self) -> WashingMachineWashProgram | None:
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(
            "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(self.config_id)
        )
        if entity_id is not None:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state not in ("unavailable", "unknown"):
                return next(
                    (
                        p
                        for p in self._programs
                        if p.localized_name(
                            self.config_entry.data.get(
                                CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
                            )
                        )
                        == state.state
                    ),
                    None,
                )
        status = cast(WashingMachineStatus, self.coordinator.data)
        for p in self._programs:
            if p.selector_position == status.program:
                return p
        return None


class WashSteamSwitch(_WashSwitchBase):
    _attr_name = "Wash steam"
    _attr_translation_key = "wash_steam_switch"
    _attr_icon = "mdi:weather-fog"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
    ) -> None:
        super().__init__(coordinator, config_entry, client, programs)
        self._steam_on: bool = False

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_STEAM_SWITCH.format(self.config_id)

    @callback
    def _on_program_changed(self, event) -> None:
        self._steam_on = False
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        if status.machine_state not in {MachineState.IDLE, MachineState.OFF}:
            return False
        prog = self._active_program()
        return prog is not None and prog.steam

    @property
    def is_on(self) -> bool:
        return self._steam_on

    async def async_turn_on(self, **kwargs) -> None:
        self._steam_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._steam_on = False
        self.async_write_ha_state()


class WashOptionSwitch(_WashSwitchBase):
    _attr_icon = "mdi:washing-machine"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
        bitmask: int,
        translation_key: str,
        uid_suffix: str,
    ) -> None:
        super().__init__(coordinator, config_entry, client, programs)
        self._bitmask = bitmask
        self._attr_translation_key = translation_key
        self._uid_suffix = uid_suffix
        self._is_on: bool = False

    @property
    def unique_id(self) -> str:
        return f"{self.config_id}-{self._uid_suffix}"

    @callback
    def _on_program_changed(self, event) -> None:
        self._is_on = False
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        if status.machine_state not in {MachineState.IDLE, MachineState.OFF}:
            return False
        prog = self._active_program()
        return prog is not None and bool(prog.available_options & self._bitmask)

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        self.async_write_ha_state()
