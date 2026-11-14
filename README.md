# Log Alert Digest

Home Assistant custom integration for grouped ERROR/WARNING log alerts, rate limiting, restart persistence and a single updating persistent notification.

[Releases](https://github.com/girtsn/ha-log-alert-digest/releases) · [Issues](https://github.com/girtsn/ha-log-alert-digest/issues)

## Behaviour

- **ERROR:** eligible for a digest after 2 minutes by default.
- **WARNING:** eligible after 24 hours by default, or bundled with an earlier ERROR digest.
- **Duplicate entries:** grouped by logger, source, message and final exception line, with counters.
- **Known noise categories** include routine untested-custom-integration notices and 10-second slow updates for `climate.fjac_*` entities. Count-only categories cover exact Fujitsu/FGLair automatic retry warnings for attempts 1 and 2 of 3 (with the observed FGLairBaseException, leaving exhausted retries and other failures actionable), plus Ayla property, device-list and sign-in timeouts, property HTTP 500 errors, and the matching `climate.fjac_*` update exception only when it follows one of those cloud failures within 30 seconds. Exact Fujitsu/Ayla `devices.json` DNS resolver timeouts are tracked separately and included in a daily summary after 24 hours, because they may indicate a recurring local or upstream DNS problem. A correlated `climate.fjac_*` update failure still counts as known fallout. They also cover the three FGLair `FujitsuClimate` temperature deprecations, the Withings port 443 webhook warning, same-identity replacements for seven known SMA sensors, and the Zeroconf `Errno 1` warning on the IPv6 mDNS wildcard socket (`[::]:5353`).
- **Ignored-event counts** track filtered WARNINGs and ERRORs per category across restarts. The next actionable digest includes a compact breakdown. Only the untested-integration and slow-update categories can trigger a standalone daily summary. The original messages remain visible in Home Assistant's System Logs.
- **Delivery safeguards:** filtered-only summaries never reset the urgent error cooldown; failed email sends do not acknowledge the tracked counts.
- **Email:** sends one grouped email at most every 60 minutes, suppressing repeats of already notified error signatures for 24 hours.
- **Home Assistant** uses the stable notification ID `log_error_digest_summary` for actionable digests and `log_error_digest_ignored_summary` for standalone daily summaries.
- **Storage:** restart-persistent bounded history of up to 200 groups, saved locally in Home Assistant's `.storage`, with 30-day pruning. Ignored category counters are stored separately and do not consume the 200-group limit.
- **Resilience:** retries after failed email delivery, with protection against self-notification loops.

Both email and persistent notifications remain enabled, just as in v0.1.0. **v0.2.0 moves configuration into the Home Assistant UI and enables system-log events automatically**, so no YAML is needed for new installations.

## Install with HACS / Marketplace

1. Add `https://github.com/girtsn/ha-log-alert-digest` as a custom **Integration** repository in HACS / Marketplace.
2. Install the **latest published GitHub Release** (not a commit snapshot) and restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → Log Alert Digest**.
4. Review the automatically suggested `notify.*` entity (prefers one containing `email`), subject prefix and notification timings. Save.

That's it. No `configuration.yaml` changes, `system_log: fire_event: true`, or manual notification automation are required. The integration switches the already-loaded Home Assistant System Log's event output on at runtime, and restores the previous state when unloaded.

**Compatibility note:** This uses Home Assistant's internal `system_log` handler `fire_event` attribute. The integration explicitly detects when the attribute is unavailable instead of silently missing errors. This API is not officially guaranteed stable by Home Assistant, so future Home Assistant upgrades may require an adaptation.

For manual installation, copy `custom_components/log_error_digest/` into `/config/custom_components/log_error_digest/`, restart, then add the integration through the UI.

## Configure and test

Use **Settings → Devices & services → Log Alert Digest → Configure** to change:

- Notification entity and email subject prefix (same `notify.send_message` action and UI convention as Device Availability Digest).
- ERROR delay, global email cooldown, repeat suppression interval.
- Whether WARNING events are monitored, and WARNING-only digest delay.

To test, invoke **Developer Tools → Actions → system_log.write** with level `error` and a distinctive non-sensitive message. A digest should appear in the Home Assistant notification bell and be sent to the configured `notify.*` entity after approximately two minutes.

Use **Settings → System → Logs** for complete tracebacks and Home Assistant's own repeat counts. Errors occurring before setup or while HA is stopped cannot be reconstructed.

## Upgrading from v0.1.0 (YAML)

Existing `log_error_digest:` YAML settings are **automatically imported once** into a Home Assistant config entry when you restart after updating. Existing notification choices and intervals are preserved. After confirming the integration appears in **Settings → Devices & services**, remove the obsolete `log_error_digest:` YAML block; it is no longer required.

If you previously added `system_log: fire_event: true`, you may remove that setting too (or retain it if other automations need system-log events). If `system_log:` has other settings, keep those.

Never configure the same monitor both by an old manual automation and the new integration; the new integration provides its own deduplication and cooldown.

## Development and releases

~~~bash
python -m compileall -q custom_components tests
python -m unittest discover -s tests -p 'test_*.py' -v
~~~

Each push to `main` runs automated validation. On success for the current commit, the release workflow publishes a **GitHub Release tagged `vX.Y.Z`**, matching the version in `custom_components/log_error_digest/manifest.json` and `RELEASE_NOTES_X.Y.Z.md`. HACS displays this published version, not a commit ID.

For future updates, always increment the version and publish a matching GitHub Release after validation.
