"""Restart-safe ERROR/WARNING digests with Home Assistant UI configuration.

The system_log handler is switched to emit system_log_event messages for
this integration's lifetime, without requiring configuration.yaml changes.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.exceptions import ConfigEntryNotReady

from .event_source import enable_system_log_events, restore_system_log_events
from .model import ErrorDigestState, summarize, utcnow

DOMAIN = "log_error_digest"
LOGGER = logging.getLogger(__name__)

# Support old 0.1.0 YAML configurations by importing their settings into a
# config entry once. New installations are fully UI configured.
_LEGACY_SCHEMA = vol.Schema({
    vol.Required("notify_entity"): cv.entity_id,
    vol.Optional("initial_minutes", default=2): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
    vol.Optional("cooldown_minutes", default=60): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
    vol.Optional("repeat_hours", default=24): vol.All(vol.Coerce(int), vol.Range(min=1, max=720)),
    vol.Optional("include_warnings", default=True): cv.boolean,
    vol.Optional("warning_digest_hours", default=24): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
    vol.Optional("email_subject_prefix", default="[HASS]"): str,
})
CONFIG_SCHEMA = vol.Schema({vol.Optional(DOMAIN): _LEGACY_SCHEMA}, extra=vol.ALLOW_EXTRA)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the domain and migrate legacy YAML options when present."""
    if legacy := config.get(DOMAIN):
        await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "import"}, data=legacy
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Start one UI-managed log monitor; enable System Log events at runtime."""
    options = {**entry.data, **entry.options}
    monitor = LogErrorDigest(hass, options)
    await monitor.load()

    try:
        handler, previous = enable_system_log_events(hass)
    except RuntimeError as exc:
        raise ConfigEntryNotReady(str(exc)) from exc
    monitor._system_log_handler = handler
    monitor._previous_fire_event = previous
    monitor.started = True
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = monitor

    @callback
    def on_error(event: Event) -> None:
        if monitor.started:
            monitor.observe(event)

    @callback
    def on_timer(_: datetime) -> None:
        if monitor.started:
            hass.async_create_task(monitor.tick())

    @callback
    def on_stop(_: Event) -> None:
        if monitor.started:
            hass.async_create_task(monitor.persist())

    entry.async_on_unload(hass.bus.async_listen("system_log_event", on_error))
    entry.async_on_unload(
        async_track_time_interval(hass, on_timer, timedelta(seconds=30))
    )
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_stop))
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply changes from the Configure/Options UI."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Detach listeners and restore the initial System Log event setting."""
    monitor = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if monitor:
        monitor.started = False
    entry.async_unload_callbacks()
    if monitor:
        await monitor.persist()
        restore_system_log_events(
            hass, monitor._system_log_handler, monitor._previous_fire_event
        )
    return True


class LogErrorDigest:
    """Collect quickly; save/deliver from a serialized 30-second timer."""

    def __init__(self, hass: HomeAssistant, options: dict) -> None:
        self.hass = hass
        self.notify_entity = options["notify_entity"]
        self.prefix = options["email_subject_prefix"].strip()
        self.initial = timedelta(minutes=options["initial_minutes"])
        self.cooldown = timedelta(minutes=options["cooldown_minutes"])
        self.repeat = timedelta(hours=options["repeat_hours"])
        self.include_warnings = options["include_warnings"]
        self.warning_delay = timedelta(hours=options["warning_digest_hours"])
        self.store = Store(hass, 1, DOMAIN, private=True, atomic_writes=True)
        self.state = ErrorDigestState()
        self.lock = asyncio.Lock()

    async def load(self) -> None:
        self.state = ErrorDigestState(await self.store.async_load())

    def observe(self, event: Event) -> None:
        # Synchronous in-memory counting is deliberate: 9,000 identical log
        # events must not create 9,000 file writes or background tasks.
        if event.data.get("level") == "WARNING" and not self.include_warnings:
            return
        self.state.observe(event.data, utcnow())

    async def persist(self) -> None:
        async with self.lock:
            if self.state.dirty:
                revision = self.state.revision
                await self.store.async_save(deepcopy(self.state.snapshot()))
                if self.state.revision == revision:
                    self.state.dirty = False

    async def tick(self) -> None:
        async with self.lock:
            now = utcnow()
            self.state.prune(now)
            ready = self.state.ready(now, self.initial, self.cooldown, self.repeat, self.warning_delay)
            if ready or self.state.ignored_due(now, self.cooldown):
                # Capture both actionable and filtered counts; events arriving
                # during the await are kept for the following digest.
                batch = deepcopy(ready)
                ignored_batch = deepcopy(self.state.pending_ignored())
                title, message = summarize(batch, ignored_batch)
                title = f"{self.prefix} {title}".strip()
                # Keep one HA notification even if email delivery is down.
                # The fixed notification ID prevents a UI notification flood.
                try:
                    await self.hass.services.async_call(
                        "persistent_notification", "create",
                        {"title": title, "message": message,
                         "notification_id": "log_error_digest_summary"},
                        blocking=True,
                    )
                except Exception:
                    LOGGER.warning("Could not update persistent error digest notice", exc_info=True)
                try:
                    await self.hass.services.async_call(
                        "notify", "send_message",
                        {"title": title, "message": message},
                        target={"entity_id": self.notify_entity},
                        blocking=True,
                    )
                except Exception:
                    # Our own logger is excluded to avoid recursive notifications.
                    LOGGER.warning("Error digest delivery failed; retrying in 5 minutes", exc_info=True)
                    self.state.mark_failed(now)
                else:
                    if batch:
                        self.state.acknowledge(batch, now)
                    if ignored_batch:
                        # Suppressed-only daily emails do not reset the regular
                        # ERROR cooldown, so fresh real errors are not delayed.
                        self.state.acknowledge_ignored(ignored_batch, now)
            if self.state.dirty:
                revision = self.state.revision
                await self.store.async_save(deepcopy(self.state.snapshot()))
                if self.state.revision == revision:
                    self.state.dirty = False
