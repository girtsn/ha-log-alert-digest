"""Independent Home Assistant system-log ERROR/WARNING monitor with bounded notifications.

Enable system_log: {fire_event: true} in configuration.yaml. Nothing in
this component depends on Device Availability Digest or its alert state.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import logging

import voluptuous as vol

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .model import ErrorDigestState, summarize, utcnow

DOMAIN = "log_error_digest"
LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({
    vol.Optional(DOMAIN): vol.Schema({
        vol.Required("notify_entity"): cv.entity_id,
        vol.Optional("initial_minutes", default=2): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
        vol.Optional("cooldown_minutes", default=60): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
        vol.Optional("repeat_hours", default=24): vol.All(vol.Coerce(int), vol.Range(min=1, max=720)),
        vol.Optional("include_warnings", default=True): cv.boolean,
        vol.Optional("warning_digest_hours", default=24): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
        vol.Optional("email_subject_prefix", default="[HASS]"): str,
    }),
}, extra=vol.ALLOW_EXTRA)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Start the independent error handler only when opted into YAML config."""
    if DOMAIN not in config:
        return True
    if not (config.get("system_log") or {}).get("fire_event", False):
        LOGGER.warning("Set system_log: fire_event: true in configuration.yaml; "
                       "without it log_error_digest will receive no log events")
    monitor = LogErrorDigest(hass, config[DOMAIN])
    await monitor.load()
    hass.data[DOMAIN] = monitor

    @callback
    def on_error(event: Event) -> None:
        monitor.observe(event)

    @callback
    def on_timer(now: datetime) -> None:
        hass.async_create_task(monitor.tick())

    async def on_stop(_: Event) -> None:
        await monitor.persist()

    hass.bus.async_listen("system_log_event", on_error)
    async_track_time_interval(hass, on_timer, timedelta(seconds=30))
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_stop)
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
            if ready:
                # Deep-copy counts to avoid losing events that arrive while
                # the awaited notify service processes an outgoing email.
                batch = deepcopy(ready)
                title, message = summarize(batch)
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
                    self.state.acknowledge(batch, now)
            if self.state.dirty:
                revision = self.state.revision
                await self.store.async_save(deepcopy(self.state.snapshot()))
                if self.state.revision == revision:
                    self.state.dirty = False
