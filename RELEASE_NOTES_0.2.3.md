# Log Alert Digest v0.2.3

- Count the known Fujitsu/Ayla property-fetch timeouts, the `FujitsuClimate` deprecations for `current_temperature`, `target_temperature` and `temperature_unit`, the Withings port 443 webhook warning, and the six known SMA sensor replacement warnings.
- Show these events as category totals only when an actionable log digest is sent. Standalone daily summaries cover only routine untested-integration notices and Fujitsu slow-update warnings.
- Move matching pending entries into the counters on restart, including SMA messages previously truncated in saved digests. Home Assistant's System Logs retain the original messages.
- After installing the update and restarting, dismiss any outdated persistent digest that Home Assistant still displays.
