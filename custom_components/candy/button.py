from __future__ import annotations

import asyncio
from typing import cast
from urllib.parse import urlencode

from homeassistant.components.button import ButtonEntity
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
    DATA_KEY_WRITE_PENDING,
    DEVICE_NAME_WASHING_MACHINE,
    DOMAIN,
    MODE_FULL_CONTROL,
    NFC_CLUSTER_TO_PROGRAM,
    SOIL_LABELS_REVERSE,
    SUGGESTED_AREA_BATHROOM,
    UNIQUE_ID_WASH_DELAY_NUMBER,
    UNIQUE_ID_WASH_NFC_SWITCH,
    UNIQUE_ID_WASH_PAUSE_BUTTON,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_SOIL_SELECT,
    UNIQUE_ID_WASH_SPIN_SELECT,
    UNIQUE_ID_WASH_START_BUTTON,
    UNIQUE_ID_WASH_STEAM_SWITCH,
    UNIQUE_ID_WASH_STOP_BUTTON,
    UNIQUE_ID_WASH_TEMP_SELECT,
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
    nfc_entries = _resolve_nfc_programs(load_nfc_programs(), programs)

    async_add_entities(
        [
            WashStartButton(coordinator, config_entry, client, programs, nfc_entries),
            WashPauseButton(coordinator, config_entry, client),
            WashStopButton(coordinator, config_entry, client),
        ]
    )


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
        if base is not None:
            nfc.duration = base.default_duration
            result.append((nfc, base))
    return result


class CandyWashButtonBase(CoordinatorEntity, ButtonEntity):
    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id
        self._client = client

    @property
    def available(self) -> bool:
        return not self.hass.data[DOMAIN][self.config_id].get(
            DATA_KEY_WRITE_PENDING, False
        )

    async def _post_command_refresh(self) -> None:
        self.hass.data[DOMAIN][self.config_id][DATA_KEY_WRITE_PENDING] = True
        self.coordinator.async_update_listeners()
        await asyncio.sleep(5)
        self.hass.data[DOMAIN][self.config_id][DATA_KEY_WRITE_PENDING] = False
        await self.coordinator.async_request_refresh()

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


class WashStartButton(CandyWashButtonBase):
    _attr_name = "Start wash"
    _attr_translation_key = "wash_start_button"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
        nfc_entries: list[tuple[NfcProgram, WashingMachineWashProgram]],
    ) -> None:
        super().__init__(coordinator, config_entry, client)
        self._programs = programs
        self._nfc_entries = nfc_entries

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_START_BUTTON.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:play-circle-outline"

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state == MachineState.IDLE

    async def async_press(self) -> None:
        registry = er.async_get(self.hass)

        def _get_state(unique_id_template: str) -> str | None:
            entity_id = registry.async_get_entity_id(
                "select", DOMAIN, unique_id_template.format(self.config_id)
            )
            if entity_id is None:
                return None
            state = self.hass.states.get(entity_id)
            return state.state if state else None

        def _get_number(unique_id_template: str) -> float:
            entity_id = registry.async_get_entity_id(
                "number", DOMAIN, unique_id_template.format(self.config_id)
            )
            if entity_id is None:
                return 0
            state = self.hass.states.get(entity_id)
            try:
                return float(state.state) if state else 0
            except (ValueError, TypeError):
                return 0

        program_name = _get_state(UNIQUE_ID_WASH_PROGRAM_SELECT)
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        program = next(
            (p for p in self._programs if p.localized_name(lang) == program_name),
            None,
        )

        if program is None:
            nfc_switch_id = registry.async_get_entity_id(
                "switch", DOMAIN, UNIQUE_ID_WASH_NFC_SWITCH.format(self.config_id)
            )
            nfc_switch_state = (
                self.hass.states.get(nfc_switch_id) if nfc_switch_id else None
            )
            nfc_active = nfc_switch_state is not None and nfc_switch_state.state == "on"
            nfc_match = next(
                (
                    (nfc, base)
                    for nfc, base in self._nfc_entries
                    if nfc_active and nfc.category_prefixed(lang) == program_name
                ),
                None,
            )
            if nfc_match is None:
                raise ValueError(
                    f"Cannot start: program '{program_name}' not found in catalog"
                )
            nfc, base = nfc_match
            delay = int(_get_number(UNIQUE_ID_WASH_DELAY_NUMBER))
            opt_mask = 0
            for bitmask, _translation_key, uid_suffix, _name in WASH_OPTIONS:
                switch_entity_id = registry.async_get_entity_id(
                    "switch", DOMAIN, f"{self.config_id}-{uid_suffix}"
                )
                switch_state = (
                    self.hass.states.get(switch_entity_id) if switch_entity_id else None
                )
                if switch_state and switch_state.state == "on":
                    opt_mask |= bitmask
            params = {
                "Write": 1,
                "StSt": 1,
                "DelVl": delay // 20,
                "PrNm": base.selector_position,
                "PrCode": base.pr_code,
                "PrStr": base.name,
                "TmpTgt": nfc.temperature,
                "SLevTgt": nfc.soil_level
                if nfc.soil_level > 0
                else base.default_soil_level,
                "SpdTgt": nfc.spin_speed // 100,
                "OptMsk1": nfc.avopt1 | opt_mask,
                "OptMsk2": 0,
                "Lang": 0,
                "Stm": 0,
                "Dry": 0,
                "ED": 0,
                "RecipeId": 0,
                "StartCheckUp": 0,
                "DispTestOn": 1,
            }
            await self._client.send_command(urlencode(params))
            await self._post_command_refresh()
            return

        temp_str = _get_state(UNIQUE_ID_WASH_TEMP_SELECT)
        spin_str = _get_state(UNIQUE_ID_WASH_SPIN_SELECT)
        soil_str = _get_state(UNIQUE_ID_WASH_SOIL_SELECT)
        delay = int(_get_number(UNIQUE_ID_WASH_DELAY_NUMBER))

        try:
            temp = (
                int(temp_str)
                if temp_str not in (None, "unavailable", "unknown")
                else program.default_temperature
            )
        except (ValueError, TypeError):
            temp = program.default_temperature

        try:
            spin = (
                int(spin_str)
                if spin_str not in (None, "unavailable", "unknown")
                else program.default_spin_speed
            )
        except (ValueError, TypeError):
            spin = program.default_spin_speed

        if program.min_soil_level < program.max_soil_level:
            try:
                soil = (
                    SOIL_LABELS_REVERSE[soil_str]
                    if soil_str not in (None, "unavailable", "unknown")
                    else program.default_soil_level
                )
            except KeyError:
                soil = program.default_soil_level
        else:
            soil = program.default_soil_level

        steam_entity_id = registry.async_get_entity_id(
            "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(self.config_id)
        )
        steam_state = self.hass.states.get(steam_entity_id) if steam_entity_id else None
        steam = steam_state.state == "on" if steam_state else False

        opt_mask = 0
        for bitmask, _translation_key, uid_suffix, _name in WASH_OPTIONS:
            switch_entity_id = registry.async_get_entity_id(
                "switch", DOMAIN, f"{self.config_id}-{uid_suffix}"
            )
            switch_state = (
                self.hass.states.get(switch_entity_id) if switch_entity_id else None
            )
            if switch_state and switch_state.state == "on":
                opt_mask |= bitmask

        params = {
            "Write": 1,
            "StSt": 1,
            "DelVl": delay // 20,  # device uses 20-min increments
            "PrNm": program.selector_position,
            "PrCode": program.pr_code,
            "PrStr": program.name,
            "TmpTgt": temp,
            "SLevTgt": soil,
            "SpdTgt": spin // 100,
            "OptMsk1": opt_mask,
            "OptMsk2": 0,
            "Lang": 0,
            "Stm": 1 if steam else 0,
            "Dry": 0,
            "ED": 0,
            "RecipeId": 0,
            "StartCheckUp": 0,
            "DispTestOn": 1,
        }
        await self._client.send_command(urlencode(params))
        await self._post_command_refresh()


class WashPauseButton(CandyWashButtonBase):
    _attr_name = "Pause wash"
    _attr_translation_key = "wash_pause_button"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_PAUSE_BUTTON.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:pause-circle-outline"

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state == MachineState.RUNNING

    async def async_press(self) -> None:
        await self._client.send_command("Pa=1")
        await self._post_command_refresh()


class WashStopButton(CandyWashButtonBase):
    _attr_name = "Stop wash"
    _attr_translation_key = "wash_stop_button"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_STOP_BUTTON.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:stop-circle-outline"

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state not in {MachineState.IDLE, MachineState.OFF}

    async def async_press(self) -> None:
        status = cast(WashingMachineStatus, self.coordinator.data)
        params = {
            "Write": 1,
            "StSt": 0,
            "PrNm": status.program,
            "DelVl": 0,
        }
        await self._client.send_command(urlencode(params))
        await self._post_command_refresh()
