# Log Alert Digest v0.2.9

## Deduplicate Fujitsu FGLair coordinator update failures

- Recognize the exact coordinator WARNING from `custom_components.fglair_heatpump_controller` in `custom_components/fglair_heatpump_controller/__init__.py`:
  `Failed to update coordinator data: FGLairBaseException has been raised`.
- Recognize the associated Home Assistant coordinator ERROR from `helpers/update_coordinator.py`:
  `Error fetching fglair_heatpump_controller data:`.
- When both happen within **30 seconds** and there is no independently identified Ayla request failure, **keep the ERROR actionable** but count the duplicate WARNING without generating a second alert. A lone WARNING or ERROR remains actionable.
- When a known Ayla request timeout, HTTP 500, or DNS-resolution timeout was recorded in the preceding **30 seconds**, count the two coordinator messages as associated known-noise occurrences instead. They appear in the suppressed counts alongside the next actionable digest; they do not independently trigger an email. This correlation is conservative: a generic `FGLairBaseException` alone is never taken as proof of connectivity failure.
- On upgrade, reclassify **pending** saved occurrences of these exact messages; never replay previously notified counts, and preserve unrelated failures.
- Add regression coverage for original source formats, microsecond-separated pairs, out-of-order delivery, near-miss exceptions and sources, expired correlation, persisted groups and restart.

Persistent or unexplained coordinator errors remain actionable unless they are associated with an explicitly logged known Ayla request failure. These rules reduce duplicate log digest alerts; they do not modify the Fujitsu integration or its cloud connection. Original events remain visible in Home Assistant **Settings → System → Logs**.

## Upgrade

Update the custom integration via HACS and restart Home Assistant. The notification summary will continue to count known/noisy events without hiding unexpected failures.
