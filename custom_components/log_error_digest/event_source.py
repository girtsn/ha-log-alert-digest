"""Enable native System Log events without requiring changes to configuration.yaml.

Home Assistant currently exposes a mutable fire_event attribute on its
system_log LogErrorHandler. This is an internal API: check its presence
explicitly and fail setup clearly if an HA release changes it.
"""
from __future__ import annotations

from typing import Any


def enable_system_log_events(hass: Any) -> tuple[Any, bool]:
    """Opt into native system_log_event broadcasts during this integration."""
    handler = hass.data.get("system_log")
    if handler is None or not hasattr(handler, "fire_event"):
        raise RuntimeError(
            "Home Assistant System Log handler does not expose fire_event; "
            "the Log Alert Digest monitor cannot start"
        )
    previous = bool(handler.fire_event)
    handler.fire_event = True
    return handler, previous


def restore_system_log_events(hass: Any, handler: Any, previous: bool) -> None:
    """Restore previous setting only if the handler instance is unchanged."""
    if hass.data.get("system_log") is handler and hasattr(handler, "fire_event"):
        handler.fire_event = previous
