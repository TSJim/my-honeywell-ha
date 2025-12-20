"""Config flow for My Honeywell integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_COOL_AWAY_TEMPERATURE,
    CONF_HEAT_AWAY_TEMPERATURE,
    DEFAULT_COOL_AWAY_TEMPERATURE,
    DEFAULT_HEAT_AWAY_TEMPERATURE,
    DOMAIN,
)
from .aiosomecomfort import (
    AIOSomeComfort,
    AuthError,
    APIRateLimited,
    ConnectionError as SomeComfortConnectionError,
    SomeComfortError,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class MyHoneywellConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for My Honeywell."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return MyHoneywellOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Test the credentials
            try:
                await self._test_credentials(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except AuthError:
                errors["base"] = "invalid_auth"
            except APIRateLimited:
                errors["base"] = "rate_limited"
            except SomeComfortConnectionError:
                errors["base"] = "cannot_connect"
            except SomeComfortError:
                errors["base"] = "unknown"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Check for existing entry with same username
                await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Honeywell ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def _test_credentials(self, username: str, password: str) -> None:
        """Test if the credentials are valid."""
        async with aiohttp.ClientSession() as session:
            client = AIOSomeComfort(
                username=username,
                password=password,
                session=session,
            )
            await client.login()
            await client.discover()

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle reauthorization."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm reauthorization."""
        errors: dict[str, str] = {}

        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
            if entry:
                try:
                    await self._test_credentials(
                        entry.data[CONF_USERNAME],
                        user_input[CONF_PASSWORD],
                    )
                except AuthError:
                    errors["base"] = "invalid_auth"
                except SomeComfortError:
                    errors["base"] = "unknown"
                else:
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )


class MyHoneywellOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for My Honeywell."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current values from options, falling back to data, then defaults
        cool_away = self.config_entry.options.get(
            CONF_COOL_AWAY_TEMPERATURE,
            self.config_entry.data.get(CONF_COOL_AWAY_TEMPERATURE, DEFAULT_COOL_AWAY_TEMPERATURE)
        )
        heat_away = self.config_entry.options.get(
            CONF_HEAT_AWAY_TEMPERATURE,
            self.config_entry.data.get(CONF_HEAT_AWAY_TEMPERATURE, DEFAULT_HEAT_AWAY_TEMPERATURE)
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_COOL_AWAY_TEMPERATURE, default=cool_away): int,
                    vol.Optional(CONF_HEAT_AWAY_TEMPERATURE, default=heat_away): int,
                }
            ),
        )
