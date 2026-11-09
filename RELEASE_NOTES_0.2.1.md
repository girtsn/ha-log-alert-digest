# Log Alert Digest v0.2.1

- Ignore Home Assistant's routine `homeassistant.loader` warnings that a custom integration has not been tested. This applies to any custom integration, including `resmed_myair` and `ps3`.
- Keep all other loader warnings, unrelated warnings, and real errors eligible for alerting.
- Drop these previously stored notices from the digest history when loading the upgraded integration, avoiding repeat alerts from historical copies.
- Leave Home Assistant's own System Logs unchanged.
- Add regression tests for suppression, preserving actionable warnings, and history migration.
