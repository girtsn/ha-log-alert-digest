# Log Alert Digest

Home Assistant custom integration for grouped ERROR/WARNING system-log alerts, rate limiting, restart persistence and a single updating persistent notification.

[Releases](https://github.com/girtsn/ha-log-alert-digest/releases) · [Issues](https://github.com/girtsn/ha-log-alert-digest/issues)

## Behaviour (unchanged from original v0.1.0)

- **ERROR:** eligible for a digest after two minutes by default.
- **WARNING:** eligible after 24 hours by default, or bundled with an earlier ERROR digest.
- **Duplicate entries:** grouped by logger, source, message and final exception line, with counters.
- **Email:** sends one grouped email at most every 60 minutes, suppressing repeats of already notified error signatures for 24 hours.
- **Home Assistant:** creates/updates one persistent notification (`log_error_digest_summary`) per digest, rather than per error.
- **Storage:** restart-persistent bounded history of up to 200 groups, saved locally in Home Assistant's `.storage`, with 30-day pruning.
- **Resilience:** five-minute retry after failed email delivery, with protection against self-notification loops.

**Both notification outputs remain enabled.** A working `notify.*` entity is required even if you normally use the Home Assistant notification bell. This release deliberately keeps the original functionality; no configuration flow or optional-email change has been introduced.

## Install with HACS / Marketplace

1. Add this repository as a **custom Integration repository**: `https://github.com/girtsn/ha-log-alert-digest`.
2. Install the **published v0.1.0 GitHub Release** in HACS/Marketplace.
3. In `/config/configuration.yaml`, enable native log events and configure the integration (merge any existing `system_log:` block):

~~~yaml
system_log:
  fire_event: true

log_error_digest:
  notify_entity: notify.my_email
  initial_minutes: 2
  cooldown_minutes: 60
  repeat_hours: 24
  include_warnings: true
  warning_digest_hours: 24
  email_subject_prefix: "[HASS]"
~~~

4. Replace `notify.my_email` with your working notification entity.
5. Validate Home Assistant configuration and **restart Home Assistant**. This integration is configured using YAML, not the Add Integration UI.

To install without HACS, copy `custom_components/log_error_digest/` into `/config/custom_components/log_error_digest/` and restart.

## Test

In **Developer Tools → Actions**, use `system_log.write` with level `error` and a unique non-sensitive message. With a working notify provider, a digest should appear in the notification bell and by email after around two minutes. A WARNING-only test may take up to 24 hours before its first digest.

Use **Settings → System → Logs** for complete tracebacks and Home Assistant's own repeat counts.

## Scope and limitations

The monitor observes ERROR and WARNING messages emitted through Home Assistant's native `system_log_event` stream **after startup**. It does not detect silent errors, logs emitted while HA is shut down, or add-on/host errors that do not reach Home Assistant's system log. The persistent notification is updated per digest, not per individual occurrence.

Events are batched in memory and saved approximately every 30 seconds and on graceful HA shutdown; a crash can lose unsaved recent events. Email bodies can include exception contents from other integrations; use a private notification target.

## Development and HACS releases

Run the pure-Python tests:

~~~bash
python -m compileall -q custom_components tests
python -m unittest discover -s tests -p 'test_*.py' -v
~~~

The release workflow runs when **Validate** succeeds on a push to the current `main` commit. It publishes the version in `custom_components/log_error_digest/manifest.json` as a **GitHub Release tagged `vX.Y.Z`** and uses `RELEASE_NOTES_X.Y.Z.md`.

**Important:** HACS uses the latest published GitHub Release tag as the available version. A Git tag alone is insufficient, and without published releases HACS can display a commit hash. For each future update, bump the manifest version, add release notes, validate, and publish the matching GitHub Release.
