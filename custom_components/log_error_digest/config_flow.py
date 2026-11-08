"""UI configuration for the standalone Log Alert Digest integration.

Matches the notification target discovery and options-flow pattern used by
Device Availability Digest. Configuration is stored in a Home Assistant
ConfigEntry, not in YAML or the public repository.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback

DOMAIN = "log_error_digest"
DEFAULTS = {
    "notify_entity": "",
    "email_subject_prefix": "[HASS]",
    "initial_minutes": 2,
    "cooldown_minutes": 60,
    "repeat_hours": 24,
    "include_warnings": True,
    "warning_digest_hours": 24,
}


def discover_defaults(hass: HomeAssistant) -> dict[str, Any]:
    """Prefill email notifier as Device Availability Digest does."""
    candidates = sorted(
        state.entity_id for state in hass.states.async_all()
        if state.entity_id.startswith("notify.")
    )
    email = next((eid for eid in candidates if "email" in eid.lower()), None)
    return {**DEFAULTS, "notify_entity": email or (candidates[0] if candidates else "")}


def _schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required("notify_entity", default=values.get("notify_entity", "")): str,
        vol.Required(
            "email_subject_prefix",
            default=values.get("email_subject_prefix", "[HASS]"),
        ): vol.All(str, vol.Length(max=80)),
        vol.Required(
            "initial_minutes", default=values.get("initial_minutes", 2)
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
        vol.Required(
            "cooldown_minutes", default=values.get("cooldown_minutes", 60)
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
        vol.Required(
            "repeat_hours", default=values.get("repeat_hours", 24)
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=720)),
        vol.Required(
            "include_warnings", default=values.get("include_warnings", True)
        ): bool,
        vol.Required(
            "warning_digest_hours", default=values.get("warning_digest_hours", 24)
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
    })


def _validate(values: dict[str, Any]) -> dict[str, str]:
    if not str(values.get("notify_entity", "")).startswith("notify."):
        return {"notify_entity": "invalid_notify"}
    return {}


class LogErrorDigestConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Allow a single instance, with detected email notification defaults."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        defaults = discover_defaults(self.hass)
        if user_input is not None:
            if errors := _validate(user_input):
                return self.async_show_form(
                    step_id="user", data_schema=_schema({**defaults, **user_input}),
                    errors=errors,
                )
            return self.async_create_entry(title="Log Alert Digest", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema(defaults))

    async def async_step_import(self, user_input: dict):
        """Import settings from v0.1.0 configuration.yaml exactly once."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if errors := _validate(user_input):
            return self.async_abort(reason="invalid_notify")
        return self.async_create_entry(
            title="Log Alert Digest", data={**DEFAULTS, **user_input}
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return LogErrorDigestOptionsFlow()


class LogErrorDigestOptionsFlow(config_entries.OptionsFlow):
    """Edit email target and digest settings in the Configure UI."""

    async def async_step_init(self, user_input: dict | None = None):
        values = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            if errors := _validate(user_input):
                return self.async_show_form(
                    step_id="init", data_schema=_schema({**values, **user_input}),
                    errors=errors,
                )
            return self.async_create_entry(data={**values, **user_input})
        return self.async_show_form(step_id="init", data_schema=_schema(values))
