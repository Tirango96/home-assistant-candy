"""Config flow for Candy integration."""

from __future__ import annotations

import logging
from typing import Any

import async_timeout
from homeassistant import config_entries
from homeassistant.components.network import async_get_source_ip
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .client import CandyClient, detect_encryption, discover_devices
from .client.cloud import SimplyFiCloudError, fetch_appliance_data
from .client.decryption import Encryption
from .client.model import WashingMachineStatus
from .const import (
    CONF_INTEGRATION_TITLE,
    CONF_KEY_DEVICE_MODEL,
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    CONF_KEY_SERIAL_NUMBER,
    CONF_KEY_SHOW_SPECIAL_PROGRAMS,
    CONF_KEY_USE_ENCRYPTION,
    DOMAIN,
    MODE_FULL_CONTROL,
    MODE_READ_ONLY,
    PROGRAM_LANGUAGES,
)

_LOGGER = logging.getLogger(__name__)

STEP_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IP_ADDRESS): str,
    }
)

MODE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_KEY_MODE, default=MODE_READ_ONLY): vol.In(
            [MODE_READ_ONLY, MODE_FULL_CONTROL]
        ),
    }
)

CLOUD_SCHEMA = vol.Schema(
    {
        vol.Required("email"): str,
        vol.Required("password"): str,
    }
)

MANUAL_IP_OPTION = "manual"


def _language_schema(default_lang: str, default_show_special: bool) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_KEY_PROGRAM_LANGUAGE, default=default_lang
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=code, label=label)
                        for code, label in PROGRAM_LANGUAGES.items()
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_KEY_SHOW_SPECIAL_PROGRAMS, default=default_show_special
            ): BooleanSelector(),
        }
    )


def _get_local_subnet(hass_ip: str) -> str:
    """Return the /24 subnet string for the given IP (e.g. '192.168.1.1' → '192.168.1.0')."""
    parts = hass_ip.split(".")[:3]
    return ".".join(parts) + ".0"


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle the options flow for the COG icon."""

    def __init__(self) -> None:
        self._pending_data: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Branch based on current mode."""
        if self.config_entry.data.get(CONF_KEY_MODE) == MODE_FULL_CONTROL:
            if user_input is not None:
                if user_input["next_step"] == "switch_to_read_only":
                    return await self.async_step_switch_to_read_only()
                if user_input["next_step"] == "program_settings":
                    self._pending_data = dict(self.config_entry.data)
                    return await self.async_step_language()
                return await self.async_step_update_cloud_data()
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {
                        vol.Required("next_step"): SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    "program_settings",
                                    "update_cloud_data",
                                    "switch_to_read_only",
                                ],
                                mode=SelectSelectorMode.LIST,
                                translation_key="next_step",
                            )
                        )
                    }
                ),
            )
        return await self.async_step_update_cloud_data()

    async def async_step_update_cloud_data(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show Simply-Fi credentials form and upgrade/refresh Full Control on submit."""
        if user_input is None:
            return self.async_show_form(
                step_id="update_cloud_data", data_schema=CLOUD_SCHEMA
            )

        errors: dict[str, str] = {}
        try:
            async with async_timeout.timeout(30):
                appliance = await fetch_appliance_data(
                    session=async_get_clientsession(self.hass),
                    email=user_input["email"],
                    password=user_input["password"],
                    device_ip=self.config_entry.data[CONF_IP_ADDRESS],
                )
        except SimplyFiCloudError as err:
            _LOGGER.warning("Simply-Fi cloud fetch failed in options flow: %s", err)
            errors["base"] = "cloud_auth"
            return self.async_show_form(
                step_id="update_cloud_data", data_schema=CLOUD_SCHEMA, errors=errors
            )
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected error in options flow cloud fetch")
            errors["base"] = "cloud_auth"
            return self.async_show_form(
                step_id="update_cloud_data", data_schema=CLOUD_SCHEMA, errors=errors
            )

        new_data = dict(self.config_entry.data)
        new_data[CONF_KEY_MODE] = MODE_FULL_CONTROL
        if appliance.encryption_key:
            new_data[CONF_KEY_USE_ENCRYPTION] = True
            new_data[CONF_PASSWORD] = appliance.encryption_key
        if appliance.mac_address:
            new_data[CONF_KEY_MAC_ADDRESS] = appliance.mac_address
        if appliance.appliance_model:
            new_data[CONF_KEY_DEVICE_MODEL] = appliance.appliance_model
        if appliance.serial_number:
            new_data[CONF_KEY_SERIAL_NUMBER] = appliance.serial_number
        new_data[CONF_KEY_PROGRAMS] = appliance.programs

        self._pending_data = new_data
        return await self.async_step_language()

    async def async_step_language(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which language to use for program names."""
        if user_input is None:
            current_lang = self._pending_data.get(
                CONF_KEY_PROGRAM_LANGUAGE,
                self.config_entry.data.get(CONF_KEY_PROGRAM_LANGUAGE, "en"),
            )
            current_special = self._pending_data.get(
                CONF_KEY_SHOW_SPECIAL_PROGRAMS,
                self.config_entry.data.get(CONF_KEY_SHOW_SPECIAL_PROGRAMS, False),
            )
            return self.async_show_form(
                step_id="language",
                data_schema=_language_schema(current_lang, current_special),
            )

        self._pending_data[CONF_KEY_PROGRAM_LANGUAGE] = user_input[
            CONF_KEY_PROGRAM_LANGUAGE
        ]
        self._pending_data[CONF_KEY_SHOW_SPECIAL_PROGRAMS] = user_input[
            CONF_KEY_SHOW_SPECIAL_PROGRAMS
        ]
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=self._pending_data
        )
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self.config_entry.entry_id)
        )
        return self.async_create_entry(data={})

    async def async_step_switch_to_read_only(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Downgrade to Read-Only: remove write entities and clear cloud data."""
        if user_input is None:
            return self.async_show_form(
                step_id="switch_to_read_only", data_schema=vol.Schema({})
            )

        new_data = dict(self.config_entry.data)
        new_data[CONF_KEY_MODE] = MODE_READ_ONLY
        new_data.pop(CONF_KEY_PROGRAMS, None)

        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self.config_entry.entry_id)
        )
        return self.async_create_entry(data={})


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for Candy."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Return the options flow handler."""
        return OptionsFlowHandler()

    def __init__(self) -> None:
        """Initialise config flow."""
        self._discovered: dict[str, str] = {}  # ip -> device type label
        self._ip_address: str = ""
        self._config_data: dict[str, Any] = {}  # accumulated config entry data
        self._is_reconfigure: bool = False
        self._is_washing_machine: bool = False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — try auto-discovery first."""
        if user_input is None:
            try:
                session = async_get_clientsession(self.hass)
                source_ip = await async_get_source_ip(self.hass)
                if source_ip:
                    subnet = _get_local_subnet(source_ip)
                    async with async_timeout.timeout(15):
                        self._discovered = await discover_devices(session, subnet)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("LAN discovery failed, falling back to manual entry")
                self._discovered = {}

            if self._discovered:
                return await self.async_step_select()

        return await self._handle_manual_ip(user_input)

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a discovered device or choose manual entry."""
        if user_input is not None:
            selected = user_input[CONF_IP_ADDRESS]
            if selected == MANUAL_IP_OPTION:
                return self.async_show_form(
                    step_id="user", data_schema=STEP_DATA_SCHEMA
                )
            return await self._configure_local(selected)

        options = {ip: f"{ip} — {label}" for ip, label in self._discovered.items()}
        options[MANUAL_IP_OPTION] = "Enter IP address manually"

        select_schema = vol.Schema({vol.Required(CONF_IP_ADDRESS): vol.In(options)})
        return self.async_show_form(step_id="select", data_schema=select_schema)

    async def _handle_manual_ip(
        self, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Process a manually entered IP address."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_DATA_SCHEMA)

        errors: dict[str, str] = {}
        try:
            result = await self._configure_local(user_input[CONF_IP_ADDRESS])
        except Exception:  # pylint: disable=broad-except
            errors["base"] = "detect_encryption"
        else:
            return result

        return self.async_show_form(
            step_id="user", data_schema=STEP_DATA_SCHEMA, errors=errors
        )

    async def _configure_local(self, ip: str) -> ConfigFlowResult:
        """Detect encryption for the device and advance to mode selection."""
        errors: dict[str, str] = {}

        try:
            async with async_timeout.timeout(40):
                encryption_type, key = await detect_encryption(
                    session=async_get_clientsession(self.hass),
                    device_ip=ip,
                )
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Failed to detect encryption")
            errors["base"] = "detect_encryption"
            return self.async_show_form(
                step_id="user", data_schema=STEP_DATA_SCHEMA, errors=errors
            )

        self._ip_address = ip
        self._config_data = {CONF_IP_ADDRESS: ip}

        if encryption_type == Encryption.ENCRYPTION:
            self._config_data[CONF_KEY_USE_ENCRYPTION] = True
            self._config_data[CONF_PASSWORD] = key
        elif encryption_type == Encryption.NO_ENCRYPTION:
            self._config_data[CONF_KEY_USE_ENCRYPTION] = False
        elif encryption_type == Encryption.ENCRYPTION_WITHOUT_KEY:
            self._config_data[CONF_KEY_USE_ENCRYPTION] = True
            self._config_data[CONF_PASSWORD] = ""

        try:
            client = CandyClient(
                session=async_get_clientsession(self.hass),
                device_ip=ip,
                encryption_key=self._config_data.get(CONF_PASSWORD, "") or "",
                use_encryption=self._config_data.get(CONF_KEY_USE_ENCRYPTION, False),
            )
            async with async_timeout.timeout(10):
                status = await client.status()
            self._is_washing_machine = isinstance(status, WashingMachineStatus)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.debug("Device type probe failed, assuming non-washing-machine")
            self._is_washing_machine = False

        return await self.async_step_mode()

    async def async_step_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user whether they want Read-Only or Full Control mode."""
        if not self._is_washing_machine:
            self._config_data[CONF_KEY_MODE] = MODE_READ_ONLY
            return self.async_create_entry(
                title=CONF_INTEGRATION_TITLE, data=self._config_data
            )

        if user_input is None:
            return self.async_show_form(step_id="mode", data_schema=MODE_SCHEMA)

        mode = user_input[CONF_KEY_MODE]
        self._config_data[CONF_KEY_MODE] = mode

        if mode == MODE_FULL_CONTROL:
            return await self.async_step_cloud()

        # Read-only: create entry immediately
        return self.async_create_entry(
            title=CONF_INTEGRATION_TITLE, data=self._config_data
        )

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect Simply-Fi credentials and fetch appliance data from cloud."""
        if user_input is None:
            return self.async_show_form(step_id="cloud", data_schema=CLOUD_SCHEMA)

        errors: dict[str, str] = {}
        try:
            async with async_timeout.timeout(30):
                appliance = await fetch_appliance_data(
                    session=async_get_clientsession(self.hass),
                    email=user_input["email"],
                    password=user_input["password"],
                    device_ip=self._ip_address,
                )
        except SimplyFiCloudError as err:
            _LOGGER.warning("Simply-Fi cloud fetch failed: %s", err)
            errors["base"] = "cloud_auth"
            return self.async_show_form(
                step_id="cloud", data_schema=CLOUD_SCHEMA, errors=errors
            )
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected error during Simply-Fi cloud fetch")
            errors["base"] = "cloud_auth"
            return self.async_show_form(
                step_id="cloud", data_schema=CLOUD_SCHEMA, errors=errors
            )

        # Credentials are NOT stored — only the fetched appliance data
        if appliance.encryption_key:
            self._config_data[CONF_KEY_USE_ENCRYPTION] = True
            self._config_data[CONF_PASSWORD] = appliance.encryption_key
        if appliance.mac_address:
            self._config_data[CONF_KEY_MAC_ADDRESS] = appliance.mac_address
        if appliance.appliance_model:
            self._config_data[CONF_KEY_DEVICE_MODEL] = appliance.appliance_model
        if appliance.serial_number:
            self._config_data[CONF_KEY_SERIAL_NUMBER] = appliance.serial_number
        self._config_data[CONF_KEY_PROGRAMS] = appliance.programs

        return await self.async_step_language()

    async def async_step_language(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which language to use for program names."""
        if user_input is None:
            existing = self._config_data.get(CONF_KEY_PROGRAM_LANGUAGE)
            default_lang = existing or (
                self.hass.config.language
                if self.hass.config.language in PROGRAM_LANGUAGES
                else "en"
            )
            default_special = self._config_data.get(
                CONF_KEY_SHOW_SPECIAL_PROGRAMS, False
            )
            return self.async_show_form(
                step_id="language",
                data_schema=_language_schema(default_lang, default_special),
            )

        self._config_data[CONF_KEY_PROGRAM_LANGUAGE] = user_input[
            CONF_KEY_PROGRAM_LANGUAGE
        ]
        self._config_data[CONF_KEY_SHOW_SPECIAL_PROGRAMS] = user_input[
            CONF_KEY_SHOW_SPECIAL_PROGRAMS
        ]
        if self._is_reconfigure:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data=self._config_data
            )
        return self.async_create_entry(
            title=CONF_INTEGRATION_TITLE, data=self._config_data
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow upgrading Read-Only → Full Control without reinstalling.

        Shows the cloud credentials form directly, since IP + encryption are already
        stored in the config entry.
        """
        if user_input is None:
            return self.async_show_form(step_id="reconfigure", data_schema=CLOUD_SCHEMA)

        entry = self._get_reconfigure_entry()
        self._ip_address = entry.data[CONF_IP_ADDRESS]
        self._config_data = dict(entry.data)
        self._is_reconfigure = True

        errors: dict[str, str] = {}
        try:
            async with async_timeout.timeout(30):
                appliance = await fetch_appliance_data(
                    session=async_get_clientsession(self.hass),
                    email=user_input["email"],
                    password=user_input["password"],
                    device_ip=self._ip_address,
                )
        except SimplyFiCloudError as err:
            _LOGGER.warning("Simply-Fi cloud fetch failed during reconfigure: %s", err)
            errors["base"] = "cloud_auth"
            return self.async_show_form(
                step_id="reconfigure", data_schema=CLOUD_SCHEMA, errors=errors
            )
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected error during reconfigure cloud fetch")
            errors["base"] = "cloud_auth"
            return self.async_show_form(
                step_id="reconfigure", data_schema=CLOUD_SCHEMA, errors=errors
            )

        self._config_data[CONF_KEY_MODE] = MODE_FULL_CONTROL
        if appliance.encryption_key:
            self._config_data[CONF_KEY_USE_ENCRYPTION] = True
            self._config_data[CONF_PASSWORD] = appliance.encryption_key
        if appliance.mac_address:
            self._config_data[CONF_KEY_MAC_ADDRESS] = appliance.mac_address
        if appliance.appliance_model:
            self._config_data[CONF_KEY_DEVICE_MODEL] = appliance.appliance_model
        if appliance.serial_number:
            self._config_data[CONF_KEY_SERIAL_NUMBER] = appliance.serial_number
        self._config_data[CONF_KEY_PROGRAMS] = appliance.programs

        return await self.async_step_language()
