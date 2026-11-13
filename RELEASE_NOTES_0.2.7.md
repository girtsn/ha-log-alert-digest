# Log Alert Digest v0.2.7

- Recognize the exact Fujitsu/Ayla EU device-list DNS-resolution timeout:
  `Error fetching information from https://ads-field-eu.aylanetworks.com/apiv1/devices.json - Cannot connect to host ads-field-eu.aylanetworks.com:443 ssl:default [Timeout while contacting DNS servers]`.
- Track these errors under a **separate Fujitsu/Ayla DNS resolution timeouts** category rather than treating them as an Ayla service failure. Emit a standalone **daily** known-noise digest if no actionable errors occur, instead of an immediate urgent email for every occurrence.
- Retain each original log in Home Assistant System Logs; count suppressed and pending occurrences, including migration of historical actionable groups (only pending occurrences are moved).
- Correlate exact FGLair climate-update exceptions within 30 seconds of either an Ayla request failure or this DNS timeout; unexpected climate errors remain actionable.
- Leave DNS failures on other hosts, other endpoints and ports, other exceptions and actual device errors actionable.
- Add dedicated regression tests for exact matching, negatives, 24-hour reporting, migration and climate correlation.

A DNS timeout can indicate a problem with the configured resolver, network path or upstream DNS infrastructure; this release does not attempt to fix that cause.
