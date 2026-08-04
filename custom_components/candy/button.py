from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import cast
from urllib.parse import quote, urlencode

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .client import (
    CandyClient,
    NfcProgram,
    WashingMachineStatistics,
    WashingMachineStatus,
    WashingMachineWashProgram,
    load_nfc_programs,
    parse_wash_programs,
    resolve_nfc_programs,
)
from .client.model import MachineState
from .const import (
    CHECKUP_SCHEDULE_EVERY_CYCLE,
    CHECKUP_SCHEDULE_WEEKLY,
    CONF_KEY_CHECKUP_ENABLED,
    CONF_KEY_CHECKUP_LAST_DATE,
    CONF_KEY_CHECKUP_SCHEDULE,
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MAINTENANCE_FILTER_ENABLED,
    CONF_KEY_MAINTENANCE_LAST_FILTER,
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
    CONF_KEY_MAINTENANCE_LAST_SELFCLEAN,
    CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
    DATA_KEY_WRITE_PENDING,
    DOMAIN,
    MODE_FULL_CONTROL,
    NFC_CLUSTER_TO_PROGRAM,
    SOIL_LABELS_REVERSE,
    UNIQUE_ID_WASH_DELAY_NUMBER,
    UNIQUE_ID_WASH_MAINT_FILTER_BUTTON,
    UNIQUE_ID_WASH_MAINT_LIMESCALE_BUTTON,
    UNIQUE_ID_WASH_MAINT_SELFCLEAN_BUTTON,
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
from .helpers import wash_device_info


def _should_send_checkup(config_entry: ConfigEntry, now: datetime) -> int:
    """Return 1 if the automatic diagnostic should run with the next wash start, else 0."""
    if not config_entry.data.get(CONF_KEY_CHECKUP_ENABLED, False):
        return 0
    schedule = config_entry.data.get(
        CONF_KEY_CHECKUP_SCHEDULE, CHECKUP_SCHEDULE_EVERY_CYCLE
    )
    if schedule == CHECKUP_SCHEDULE_EVERY_CYCLE:
        return 1
    last_ts = config_entry.data.get(CONF_KEY_CHECKUP_LAST_DATE)
    if last_ts is None:
        return 1
    last = dt_util.utc_from_timestamp(last_ts)
    delta = timedelta(days=7 if schedule == CHECKUP_SCHEDULE_WEEKLY else 30)
    return 1 if (now - last) >= delta else 0


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
    nfc_entries = resolve_nfc_programs(
        load_nfc_programs(), programs, NFC_CLUSTER_TO_PROGRAM
    )

    interface_type = config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
    supports_pause = not interface_type.upper().startswith("BIANCA")

    buttons: list = [
        WashStartButton(coordinator, config_entry, client, programs, nfc_entries),
        WashStopButton(coordinator, config_entry, client),
    ]
    if supports_pause:
        buttons.append(WashPauseButton(coordinator, config_entry, client))
    async_add_entities(buttons)

    if config_entry.data.get(CONF_KEY_MAINTENANCE_ENABLED):
        stats_coordinator = hass.data[DOMAIN][config_id].get(DATA_KEY_STATS_COORDINATOR)
        if stats_coordinator is not None:
            buttons = [
                WashMaintResetButton(
                    coordinator,
                    config_entry,
                    stats_coordinator,
                    CONF_KEY_MAINTENANCE_LAST_SELFCLEAN,
                    UNIQUE_ID_WASH_MAINT_SELFCLEAN_BUTTON,
                    "Reset Auto-Clean Counter",
                    "wash_maint_selfclean_reset",
                    "mdi:washing-machine-alert",
                ),
            ]
            if config_entry.data.get(CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED, True):
                buttons.append(
                    WashMaintResetButton(
                        coordinator,
                        config_entry,
                        stats_coordinator,
                        CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
                        UNIQUE_ID_WASH_MAINT_LIMESCALE_BUTTON,
                        "Reset Limescale Counter",
                        "wash_maint_limescale_reset",
                        "mdi:water-remove",
                    )
                )
            if config_entry.data.get(CONF_KEY_MAINTENANCE_FILTER_ENABLED, True):
                buttons.append(
                    WashMaintResetButton(
                        coordinator,
                        config_entry,
                        stats_coordinator,
                        CONF_KEY_MAINTENANCE_LAST_FILTER,
                        UNIQUE_ID_WASH_MAINT_FILTER_BUTTON,
                        "Reset Filter Counter",
                        "wash_maint_filter_reset",
                        "mdi:filter-remove",
                    )
                )
            async_add_entities(buttons)


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
        return (
            self.hass.data[DOMAIN][self.config_id].get(DATA_KEY_WRITE_PENDING, 0) == 0
        )

    async def _send_command_and_refresh(self, query_string: str) -> None:
        data = self.hass.data[DOMAIN][self.config_id]
        data[DATA_KEY_WRITE_PENDING] = data.get(DATA_KEY_WRITE_PENDING, 0) + 1
        self.coordinator.async_update_listeners()
        try:
            await self._client.send_command(query_string)
        except Exception:
            await asyncio.sleep(5)
            raise
        finally:
            data[DATA_KEY_WRITE_PENDING] -= 1
            if data[DATA_KEY_WRITE_PENDING] == 0:
                await self.coordinator.async_request_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)


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
            steam_entity_id = registry.async_get_entity_id(
                "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(self.config_id)
            )
            steam_state = (
                self.hass.states.get(steam_entity_id) if steam_entity_id else None
            )
            steam = steam_state.state == "on" if steam_state else False
            params = {
                "Write": 1,
                "StSt": 1,
                "DelVl": delay // 30,
                "PrNm": base.selector_position,
                "PrCode": base.pr_code,
                "PrStr": nfc.display_name(lang),
                "TmpTgt": nfc.temperature,
                "SLevTgt": nfc.soil_level
                if nfc.soil_level > 0
                else base.default_soil_level,
                "SpdTgt": nfc.spin_speed // 100,
                "OptMsk1": nfc.avopt1 | opt_mask,
                "OptMsk2": 0,
                "Lang": 0,
                "Stm": 1 if steam else 0,
                "Dry": 0,
                "ED": 0,
                "RecipeId": 0,
                "StartCheckUp": _should_send_checkup(
                    self.config_entry, dt_util.utcnow()
                ),
                "DispTestOn": 1,
            }
            await self._send_command_and_refresh(urlencode(params, quote_via=quote))
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
            "DelVl": delay // 30,  # device uses 30-min increments
            "PrNm": program.selector_position,
            "PrCode": program.pr_code,
            "PrStr": program.localized_name(lang),
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
            "StartCheckUp": _should_send_checkup(self.config_entry, dt_util.utcnow()),
            "DispTestOn": 1,
        }
        await self._send_command_and_refresh(urlencode(params, quote_via=quote))


class WashMaintResetButton(CoordinatorEntity, ButtonEntity):
    """Reset a maintenance counter to its full threshold."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(  # noqa: PLR0917
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        stats_coordinator: DataUpdateCoordinator,
        conf_key: str,
        unique_id_template: str,
        name: str,
        translation_key: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id
        self._stats_coordinator = stats_coordinator
        self._conf_key = conf_key
        self._unique_id_template = unique_id_template
        self._attr_name = name
        self._attr_translation_key = translation_key
        self._attr_icon = icon

    @property
    def unique_id(self) -> str:
        return self._unique_id_template.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)

    async def async_press(self) -> None:
        total = 0
        if self._stats_coordinator.data is not None:
            total = cast(
                WashingMachineStatistics, self._stats_coordinator.data
            ).total_cycles
        new_data = dict(self.config_entry.data)
        new_data[self._conf_key] = total
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        self._stats_coordinator.async_update_listeners()


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
        await self._send_command_and_refresh("Pa=1")


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
        await self._send_command_and_refresh(urlencode(params, quote_via=quote))
