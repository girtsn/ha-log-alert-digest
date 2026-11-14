# Log Alert Digest v0.2.8

- Recognize the exact warning pattern from `custom_components.fglair_heatpump_controller.climate` during intermediate automatic API retries:
  `API call failed (attempt 1/3): FGLairBaseException has been raised. Retrying in 1.0s...`
  and the corresponding `attempt 2/3` retry message.
- Treat these non-final warnings as count-only known log noise: they appear as a category total alongside a future actionable digest but do not independently trigger a daily notification.
- Keep exhausted retries (`attempt 3/3`), differing exceptions, unrecognized messages, and unrelated logger/source errors actionable.
- Reclassify pending occurrences from existing saved log groups on startup, without replaying already reported historical messages. For the supplied example this would migrate the 1 pending occurrence, not all 21 historically recorded.
- Add regression tests for both intermediate retry warnings, strict boundaries, historical migration, and persistence.

The retry notice does not guarantee a successful retry; separate final failures and actual climate-update exceptions are not suppressed by this new rule. Original events remain visible in Home Assistant System Logs.
