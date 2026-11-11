# Log Alert Digest v0.2.4

- Include same-identity SMA `pv_total_power_b` replacements in the existing sensor replacement count.
- Count the specific Zeroconf `PermissionError: [Errno 1] Operation not permitted` warning for the IPv6 mDNS wildcard socket (`[::]:5353`). Its total appears only in a digest triggered by an actionable log.
- Move matching pending entries into their counters on restart.
