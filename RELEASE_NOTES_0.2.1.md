# Log Alert Digest v0.2.1

- Suppress the standard Home Assistant `homeassistant.loader` warning that custom integrations have not been tested (including `resmed_myair` and `ps3`), while leaving other loader issues visible.
- Suppress only `pyfujitsugeneral` ERROR entries from the FGLair heat-pump controller matching the specific Ayla EU cloud `properties.json` fetch-timeout pattern. Other Fujitsu errors, timeouts elsewhere, and exceptions with tracebacks remain actionable.
- Count filtered messages by fixed category (WARNING or ERROR) without storing or repeating device identifiers and cloud request URLs in digests.
- Append filtered category totals to actionable emails and the actionable Home Assistant persistent notification. Ignored-only daily summaries use a separate, stable notification ID so they do not overwrite actionable alerts. When there are only filtered events, deliver a single category summary after 24 hours, with subsequent filtered-only summaries limited to daily cadence.
- Preserve ignored-message counters across restarts, migrate previously pending messages from older stored digest groups, and preserve new events arriving during email delivery.
- Keep Home Assistant's own System Logs intact; no global logging suppression.
- Expand regression tests for exact pattern matching, non-matching errors, daily cadence, and restart-safe counting.
