# Runtime Flags (Firestore: `config/runtime_flags`)

Default document:
```json
{
  "allowComplex": true,
  "perHourLimit": 10,
  "perDayLimit": 60,
  "sampleRowsForLLM": 50,
  "metricRenameHeuristic": false,
  "maxCharts": 3
}
```

Notes:
- `allowComplex` is toggled by the Scheduler-driven `usage-watcher` function.
- `metricRenameHeuristic=false` preserves original column names; the pipeline emits `is_potential_dimension` flags instead.
- `sampleRowsForLLM` sets payload sample size and the `ctx.limits.sampleRowsForDisplay` hint.
