# Log Alert Digest v0.1.0

Initial public HACS/Marketplace release of the previously staged Log Alert Digest, with no functional changes.

- Monitor native Home Assistant ERROR and WARNING system-log events.
- Group repeated exceptions and preserve counters across restarts.
- Send grouped emails with configurable delays, hourly rate limiting and repeat suppression.
- Maintain a single persistent Home Assistant notification.
- Include regression tests for 9,539 identical exceptions, warning delays, throttling and restart persistence.

## Installation

Add `https://github.com/girtsn/ha-log-alert-digest` as a custom Integration repository in HACS/Marketplace, install the published `v0.1.0` release, configure `system_log: fire_event: true` plus `log_error_digest` with your notify entity in `configuration.yaml`, and restart Home Assistant.
