"""Pure-Python, bounded, restart-safe model for Home Assistant error digests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Any

MAX_GROUPS = 200

# Home Assistant emits this standard notice for every third-party integration.
# It is not a fault in the named integration and should not trigger an alert.
_CUSTOM_INTEGRATION_NOTICE = re.compile(
    r"We found a custom integration [a-z0-9_]+ which has not been tested "
    r"by Home Assistant\. This component might cause stability problems, "
    r"be sure to disable it if you experience issues with Home Assistant"
)


def _is_standard_custom_integration_notice(level: str, logger: str, message: str) -> bool:
    """Ignore only the routine HA loader notice, never all loader warnings."""
    return (
        level == "WARNING"
        and logger == "homeassistant.loader"
        and _CUSTOM_INTEGRATION_NOTICE.fullmatch(message) is not None
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _short(value: Any, limit: int) -> str:
    if isinstance(value, (list, tuple)):
        value = " ".join(str(item) for item in value)
    return " ".join(str(value or "").split())[:limit]


def _last_exception_line(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        value = "\n".join(str(item) for item in value)
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    return _short(lines[-1] if lines else "", 350)


class ErrorDigestState:
    """Aggregate log events without one persistent write or action per error."""

    def __init__(self, stored: dict[str, Any] | None = None) -> None:
        stored = stored or {}
        self.groups: dict[str, dict] = dict(stored.get("groups", {}))
        # Migrate existing stored notices so old pending warnings cannot be
        # included in a later email after upgrading.
        excluded = [
            key for key, group in self.groups.items()
            if _is_standard_custom_integration_notice(
                group.get("level", ""), group.get("logger", ""), group.get("message", "")
            )
        ]
        for key in excluded:
            del self.groups[key]
        self.last_sent: str | None = stored.get("last_sent")
        self.retry_after: str | None = stored.get("retry_after")
        self.dirty = bool(excluded)
        self.revision = 1 if excluded else 0

    def snapshot(self) -> dict:
        return {
            "groups": self.groups,
            "last_sent": self.last_sent,
            "retry_after": self.retry_after,
        }

    def observe(self, event: dict, now: datetime) -> bool:
        """Observe native ERROR/WARNING entries; ignore this monitor's logs."""
        level = str(event.get("level", "")).upper()
        if level not in ("ERROR", "WARNING"):
            return False
        logger = _short(event.get("name"), 160)
        source = _short(event.get("source"), 180)
        if "log_error_digest" in logger or "log_error_digest" in source:
            return False
        message = _short(event.get("message"), 320)
        if _is_standard_custom_integration_notice(level, logger, message):
            return False
        exception = _last_exception_line(event.get("exception"))
        identity = "\x00".join((logger, source, message, exception))
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        if key not in self.groups and len(self.groups) >= MAX_GROUPS - 2:
            # Reserve a bounded overflow bucket if very many distinct errors occur.
            stale = [k for k, v in self.groups.items()
                     if not v.get("unreported") and not k.startswith("other_")]
            if stale:
                self.groups.pop(min(stale, key=lambda k: self.groups[k].get("last", "")))
            else:
                key = f"other_{level}"
                logger, source, message, exception = (
                    "Multiple integrations", "Various", f"Other distinct {level.lower()} messages (limit reached)", ""
                )
        ts = now.isoformat()
        if key not in self.groups:
            self.groups[key] = {
                "level": level,
                "logger": logger,
                "source": source,
                "message": message,
                "exception": exception,
                "first": ts,
                "last": ts,
                "total": 0,
                "unreported": 0,
                "pending_since": ts,
                "notified_at": None,
            }
        group = self.groups[key]
        group["last"] = ts
        group["total"] += 1
        group["unreported"] += 1
        if not group.get("pending_since"):
            group["pending_since"] = ts
        self.dirty = True
        self.revision += 1
        return True

    def ready(self, now: datetime, initial_delay: timedelta,
              min_interval: timedelta, repeat_after: timedelta,
              warning_delay: timedelta = timedelta(hours=24)) -> list[tuple[str, dict]]:
        """Urgent errors email quickly; warnings alone email at daily cadence."""
        if self.retry_after and now < parse(self.retry_after):
            return []
        eligible = [(k, v) for k, v in self.groups.items()
                    if v.get("unreported", 0) > 0 and (
                        not v.get("notified_at")
                        or now >= parse(v["notified_at"]) + repeat_after
                    )]
        if not eligible:
            return []
        if self.last_sent and now < parse(self.last_sent) + min_interval:
            return []
        due = any(now >= parse(g.get("pending_since") or g["first"]) + (
            warning_delay if g.get("level") == "WARNING" else initial_delay
        ) for _, g in eligible)
        if not due:
            return []
        return sorted(eligible, key=lambda item: (
            0 if item[1].get("level") == "ERROR" else 1,
            -item[1]["unreported"], item[0]
        ))

    def acknowledge(self, entries: list[tuple[str, dict]], now: datetime) -> None:
        """Only clear counts included in the successful email snapshot."""
        for key, reported in entries:
            group = self.groups.get(key)
            if not group:
                continue
            group["unreported"] = max(0, group["unreported"] - reported["unreported"])
            group["pending_since"] = now.isoformat() if group["unreported"] else None
            group["notified_at"] = now.isoformat()
        self.last_sent = now.isoformat()
        self.retry_after = None
        self.dirty = True
        self.revision += 1

    def mark_failed(self, now: datetime, minutes: int = 5) -> None:
        self.retry_after = (now + timedelta(minutes=minutes)).isoformat()
        self.dirty = True
        self.revision += 1

    def prune(self, now: datetime) -> None:
        cutoff = (now - timedelta(days=30)).isoformat()
        for key, group in list(self.groups.items()):
            if group.get("last", "") < cutoff and group.get("unreported", 0) == 0:
                del self.groups[key]
                self.dirty = True
                self.revision += 1


def summarize(entries: list[tuple[str, dict]]) -> tuple[str, str]:
    """Build a bounded email; full tracebacks remain in HA's own Logs UI."""
    count = sum(group["unreported"] for _, group in entries)
    errors = sum(g["unreported"] for _, g in entries if g.get("level") == "ERROR")
    warnings = count - errors
    headline = f"Home Assistant log digest: {errors} ERROR(s), {warnings} WARNING(s)"
    lines = [f"{len(entries)} distinct error types; {count} occurrences since their last alert.",
             "Repeated messages are subject to the configured suppression period.",
             "For full tracebacks open Settings > System > Logs.", ""]
    for i, (_, group) in enumerate(entries[:12], 1):
        lines.extend([
            f"{i}. [{group.get('level', 'ERROR')}] {group['logger']} ({group['source']})",
            f"   Count: {group['unreported']} (total recorded: {group['total']})",
            f"   Error: {group['message']}",
            f"   Exception: {group['exception'] or 'No traceback supplied'}",
            f"   First: {group['first']} | Last: {group['last']}",
            "",
        ])
    if len(entries) > 12:
        lines.append(f"... and {len(entries)-12} more distinct error types (see Home Assistant logs).")
    return headline, "\n".join(lines)
