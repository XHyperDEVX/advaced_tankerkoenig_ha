"""One API account per installation; subsequent add flows only ask for UUIDs."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import CONF_API_KEY, CONF_STATIONS, DOMAIN, MAX_STATIONS, NAME
from .helpers import UUID_RE, parse_stations

KEY_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
STATION_SELECTOR = TextSelector(TextSelectorConfig(multiline=True))


class AdvancedTankerkoenigConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        # Check BEFORE displaying an API-key field, not after submitting it.
        if self._async_current_entries():
            return await self.async_step_add_station(user_input)
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors = {}
        if user_input is not None:
            try:
                stations = parse_stations(user_input[CONF_STATIONS])
            except ValueError:
                errors[CONF_STATIONS] = "invalid_stations"
            key = user_input.get(CONF_API_KEY, "").strip()
            if not UUID_RE.fullmatch(key):
                errors[CONF_API_KEY] = "invalid_api_key"
            if not errors:
                return self.async_create_entry(
                    title=NAME,
                    data={CONF_API_KEY: key, CONF_STATIONS: stations},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): KEY_SELECTOR,
                vol.Required(CONF_STATIONS): STATION_SELECTOR,
            }),
            errors=errors,
        )

    async def async_step_add_station(self, user_input=None):
        entries = self._async_current_entries()
        if not entries:
            return self.async_abort(reason="not_configured")
        entry = entries[0]
        stations = list(entry.options.get(CONF_STATIONS, entry.data[CONF_STATIONS]))
        if len(stations) >= MAX_STATIONS:
            return self.async_abort(reason="station_limit")
        errors = {}
        if user_input is not None:
            try:
                additions = parse_stations(user_input[CONF_STATIONS])
            except ValueError:
                errors[CONF_STATIONS] = "invalid_stations"
            else:
                if set(additions) & set(stations):
                    errors[CONF_STATIONS] = "duplicate_station"
                elif len(stations) + len(additions) > MAX_STATIONS:
                    errors[CONF_STATIONS] = "station_limit"
                else:
                    # No second ConfigEntry, API key, poller or overview device.
                    self.hass.config_entries.async_update_entry(
                        entry, options={**entry.options, CONF_STATIONS: stations + additions}
                    )
                    return self.async_abort(reason="stations_added")
        return self.async_show_form(
            step_id="add_station",
            data_schema=vol.Schema({vol.Required(CONF_STATIONS): STATION_SELECTOR}),
            errors=errors,
            description_placeholders={"remaining": str(MAX_STATIONS - len(stations))},
        )

    async def async_step_reconfigure(self, user_input=None):
        """Explicitly replace the one stored key, without adding another account."""
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            if not UUID_RE.fullmatch(key):
                errors[CONF_API_KEY] = "invalid_api_key"
            else:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_API_KEY: key})
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): KEY_SELECTOR}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AdvancedTankerkoenigOptionsFlow()


class AdvancedTankerkoenigOptionsFlow(config_entries.OptionsFlow):
    """The base class supplies config_entry; it is read-only in modern HA."""

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                stations = parse_stations(user_input[CONF_STATIONS])
            except ValueError:
                errors[CONF_STATIONS] = "invalid_stations"
            else:
                return self.async_create_entry(
                    title="", data={**self.config_entry.options, CONF_STATIONS: stations}
                )
        stations = self.config_entry.options.get(CONF_STATIONS, self.config_entry.data[CONF_STATIONS])
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_STATIONS, default="\n".join(stations)): STATION_SELECTOR,
            }),
            errors=errors,
        )
