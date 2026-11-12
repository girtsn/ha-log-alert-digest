# Log Alert Digest v0.2.5

- Count the known Fujitsu/Ayla `user-field-eu` sign-in timeout and `ads-field-eu` property HTTP 500 Internal Server Error alongside existing property timeouts, instead of treating each as an actionable alert.
- Count `Update for climate.fjac_* fails` with the exact `FGLairGeneralException` last traceback line only when a recognized Ayla failure was observed within the preceding 30 seconds. Other climate update failures remain actionable.
- Preserve the fixed-category counts across restarts and migrate previously pending matching events where their stored timestamps permit correlation.
- Leave unrelated endpoints, authentication rejections, other HTTP status codes and unexpected exceptions actionable.
- Add regression tests for both real log samples, nonmatches, correlation boundaries and storage migration.
