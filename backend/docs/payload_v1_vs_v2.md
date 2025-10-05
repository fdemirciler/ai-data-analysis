# Payload examples: v1 (baseline) vs v2 (additive)

Below are minimal examples illustrating the additive v2 fields. The schema at `backend/docs/payload_schema.json` validates v1 only; v2 fields are optional and ignored by v1 validators.

## v1 (current schema)
```json
{
  "dataset": { "rows": 123, "columns": 4, "column_names": ["Metric", "2023", "2024", "2025"], "dtypes": {"Metric": "string", "2023": "float64", "2024": "float64", "2025": "float64"} },
  "columns": {
    "Metric": { "type": "text", "null_pct": 0.0, "unique_pct": 100.0, "top_values": [] },
    "2023": { "type": "float", "null_pct": 0.0, "unique_pct": 95.0, "top_values": [] }
  },
  "sample_rows": [ { "Metric": "Cash", "2023": 1990.0, "2024": 3389.0 } ],
  "cleaning_report": { "header_row": 1, "renamed_columns": {}, "numeric_columns": ["2023", "2024"], "rows_before": 130, "rows_after": 123, "file_kind": "csv" },
  "mode": "full",
  "version": "1"
}
```

## v2 (additive, compact)
```json
{
  "dataset": { "rows": 123, "columns": 4, "column_names": ["Metric", "2023", "2024", "2025"], "dtypes": {"Metric": "string", "2023": "float64", "2024": "float64", "2025": "float64"} },
  "columns": {
    "Metric": { "type": "text", "null_pct": 0.0, "unique_pct": 100.0, "top_values": [] },
    "2023": { "type": "float", "null_pct": 0.0, "unique_pct": 95.0, "top_values": [] }
  },
  "sample_rows": [ { "Metric": "Cash", "2023": 1990.0, "2024": 3389.0 } ],
  "cleaning_report": { "header_row": 1, "renamed_columns": {}, "numeric_columns": ["2023", "2024"], "rows_before": 130, "rows_after": 123, "file_kind": "csv" },
  "mode": "full",
  "version": "1",

  "schema_version": "2.0",
  "header_info": {
    "method": "auto_detected",
    "header_row_index": 1,
    "confidence": 0.78,
    "original_headers": ["Metric", "2023", "2024", "2025"],
    "final_headers": ["Metric", "2023", "2024", "2025"],
    "is_transposed": false
  },
  "analysis_hints": {
    "detected_header_row": 1,
    "header_confidence": 0.78,
    "pct_missing_total": 0.02,
    "first_column_type": "dimension",
    "likely_pivoted": true,
    "temporal_columns": [1, 2, 3],
    "numeric_columns": [1, 2, 3]
  },
  "dataset_summary": "Dataset has 123 rows and 4 columns. Header row 1 detected (confidence 0.78). Structure: first column dimension, pivoted=true."
}
```
