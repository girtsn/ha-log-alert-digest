# Log Alert Digest v0.2.6

- Count-only handling for the exact Fujitsu/Ayla EU device-list timeout:
  `pyfujitsugeneral` from `custom_components/fglair_heatpump_controller/`
  reporting `Timeout error fetching information from https://ads-field-eu.aylanetworks.com/apiv1/devices.json -`.
- Reuse the existing `fujitsu_ayla_timeout` ignored-error counter. Known cloud failures can also correlate with the exact `FGLairGeneralException` from a climate update when it follows within 30 seconds.
- Other `/devices.json` errors, HTTP 500s, authorization problems, unrecognized endpoints, and unrelated integration failures remain actionable.
- On upgrade, move only pending historical occurrences into the ignored count; previously reported historical occurrences are not re-added.
- Add regression tests covering the observed `__init__.py:80` source, nonmatching events, correlations and restart migration.

The Google Assistant status 204 and iOS websocket heartbeat warnings have not been reclassified in this release.
