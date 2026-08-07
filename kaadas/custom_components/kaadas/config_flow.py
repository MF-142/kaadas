from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_POLL_INTERVAL_EVENT,
    CONF_POLL_INTERVAL_INFO,
    CONF_TOKEN,
    CONF_UID,
    CONF_WIFI_SN,
    DEFAULT_EVENT_POLL,
    DEFAULT_INFO_POLL,
    DOMAIN,
)


class KaadasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_WIFI_SN])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_WIFI_SN], data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_TOKEN): str,
                vol.Required(CONF_WIFI_SN): str,
                vol.Required(CONF_UID): str,
                vol.Optional(CONF_POLL_INTERVAL_EVENT, default=DEFAULT_EVENT_POLL): int,
                vol.Optional(CONF_POLL_INTERVAL_INFO, default=DEFAULT_INFO_POLL): int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return KaadasOptionsFlowHandler(config_entry)


class KaadasOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(CONF_POLL_INTERVAL_EVENT, default=self.config_entry.options.get(CONF_POLL_INTERVAL_EVENT, DEFAULT_EVENT_POLL)): int,
                vol.Optional(CONF_POLL_INTERVAL_INFO, default=self.config_entry.options.get(CONF_POLL_INTERVAL_INFO, DEFAULT_INFO_POLL)): int,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
