# Log Alert Digest v0.2.2

- Recognize and aggregate the additional Fujitsu/Ayla EU cloud timeout signature for `/apiv1/properties/<numeric-id>/datapoints.json`, alongside the previously supported `/apiv1/dsns/<device-id>/properties.json`. Keep unrelated Fujitsu faults, endpoints, loggers and exceptions actionable.
- Aggregate the exact `FujitsuClimate` `current_temperature` deprecation warnings emitted by `fglair_heatpump_controller`. This suppresses notification noise, **not** Home Assistant's System Logs; the FGLair integration itself still needs to switch to `native_current_temperature` before Home Assistant 2027.11.
- Reclassify matching unsent legacy digest groups at integration startup; preserve ignored-event counters, daily known-noise summaries, email rate limits, and unrelated actionable alerts.
- Add regression tests based on the reported logger, source, full warning text and Ayla datapoints URL, plus tests verifying that nearby failures remain actionable.
- Home Assistant persistent notifications already displayed from earlier digests are not retroactively edited; dismiss an outdated notification once after updating and restarting.
