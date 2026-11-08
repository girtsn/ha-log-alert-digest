# Log Alert Digest v0.2.0 — automatic System Log events and UI setup

## Added

- Enable native `system_log_event` delivery automatically through the Home Assistant System Log handler when Log Alert Digest is configured. Restore the prior setting on unload. No separate `system_log: fire_event: true` YAML entry is needed.
- **UI setup and Configure/Options flow**, following the same experience as Device Availability Digest:
  - Automatically suggest a `notify.*` entity, preferring an email notification target.
  - Configure subject prefix, ERROR delay, global cooldown, repeat interval, WARNING monitoring and WARNING-only digest interval.
- Import existing v0.1.0 YAML configuration into a config entry, preserving settings for existing installations.
- Regression tests for automatic event activation, failure when the Home Assistant API is missing, and restoration on unload.

## Unchanged

- Grouping and deduplication model, email via `notify.send_message`, one persistent notification, suppressions, counts, restart-safe storage, and the existing error/warning notification policy.

## Technical note

Home Assistant currently exposes a mutable `fire_event` setting on its built-in System Log handler. The setting is internal, so the integration checks availability explicitly. A future Home Assistant update could require an adaptation.

## Install

Update from HACS/Marketplace to the **published v0.2.0 GitHub Release**, restart Home Assistant, and add **Log Alert Digest** in **Settings → Devices & services**. No YAML required for new installations.
