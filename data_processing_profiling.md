This file is a merged representation of the entire codebase, combined into a single document by Repomix.
The content has been processed where empty lines have been removed, content has been compressed (code blocks are separated by ⋮---- delimiter), security check has been disabled.

# File Summary

## Purpose
This file contains a packed representation of the entire repository's contents.
It is designed to be easily consumable by AI systems for analysis, code review,
or other automated processes.

## File Format
The content is organized as follows:
1. This summary section
2. Repository information
3. Directory structure
4. Repository files (if enabled)
5. Multiple file entries, each consisting of:
  a. A header with the file path (## File: path/to/file)
  b. The full contents of the file in a code block

## Usage Guidelines
- This file should be treated as read-only. Any changes should be made to the
  original repository files, not this packed version.
- When processing this file, use the file path to distinguish
  between different files in the repository.
- Be aware that this file may contain sensitive information. Handle it with
  the same level of security as you would the original repository.

## Notes
- Some files may have been excluded based on .gitignore rules and Repomix's configuration
- Binary files are not included in this packed representation. Please refer to the Repository Structure section for a complete list of file paths, including binary files
- Files matching patterns in .gitignore are excluded
- Files matching default ignore patterns are excluded
- Empty lines have been removed from all files
- Content has been compressed - code blocks are separated by ⋮---- delimiter
- Security check has been disabled - content may contain sensitive information
- Files are sorted by Git change count (files with more changes are at the bottom)

# Directory Structure
```
tests/
  test_pipeline_basic.py
__init__.py
cleaning_utils.py
cli.py
data_profiler.py
pipeline.py
pytest.ini
README.md
type_inference.py
```

# Files

## File: tests/test_pipeline_basic.py
````python
# Ensure project root (containing the 'data_processing' package directory) is on sys.path
_project_root = _P(__file__).resolve().parents[2]
⋮----
def test_pipeline_full_mode(tmp_path: Path)
⋮----
# Create a small mixed CSV
df = pd.DataFrame(
csv_path = tmp_path / "people.csv"
# Write without header to exercise header detection logic
⋮----
result = run_processing_pipeline(str(csv_path), mode="full")
payload = result["payload"]
# Basic structure assertions (header detection may treat first row as header -> 3 data rows)
⋮----
# Column summaries should exist for at least one numeric-ish column
cols = payload["columns"]
⋮----
# Metric list (singular key) should be present because first column renamed to 'Metric'
⋮----
def test_pipeline_schema_only(tmp_path: Path)
⋮----
df = pd.DataFrame({"A": [1, 2, 3], "B": ["x", "y", "z"]})
csv_path = tmp_path / "simple.csv"
⋮----
result = run_processing_pipeline(str(csv_path), mode="schema_only")
⋮----
# schema_only mode intentionally excludes sample_rows
⋮----
def test_percentage_and_numeric_normalization(tmp_path: Path)
⋮----
csv_path = tmp_path / "metrics.csv"
⋮----
# Use treat_first_row_as_data so percentage row isn't consumed as header candidate
result = run_processing_pipeline(
⋮----
# Revenue column should parse to large numbers (> 1000 for this fixture)
revenue_like = None
⋮----
stats = c.get("stats", {})
⋮----
if mx > 3000 and mn >= 1000:  # our revenue values 1200..3750
revenue_like = c
⋮----
# Users column with K suffix should scale to thousands and have integer-ish max of 3000
users_like = None
⋮----
# Users: 1200..3000 (3K becomes 3000)
⋮----
users_like = c
⋮----
def test_treat_first_row_as_data(tmp_path: Path)
⋮----
# First row should not be consumed as header when flag set
df = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]})
csv_path = tmp_path / "numbers.csv"
⋮----
result_default = run_processing_pipeline(str(csv_path), mode="full")
rows_default = result_default["payload"]["dataset"][
⋮----
]  # header may reduce rows
result_flag = run_processing_pipeline(
rows_flag = result_flag["payload"]["dataset"]["rows"]
# With the flag, we should retain all original rows
⋮----
# No 'Metric' column in this case -> top-level Metric list key absent
````

## File: __init__.py
````python
"""Data processing package providing cleaning, type inference, profiling and an orchestrated pipeline.
Public entry point:
    run_processing_pipeline(file_path: str, *, mode: str = "full", config: Optional[dict] = None)
Modes:
    full         -> full metadata + column summaries + sample rows
    schema_only  -> only dataset + column type schema (lightweight for LLM)
"""
⋮----
from .pipeline import run_processing_pipeline  # noqa: F401
__all__ = ["run_processing_pipeline"]
````

## File: cleaning_utils.py
````python
"""Minimal internal cleaning utilities extracted from original csv_excel_cleaner.
Only the pieces required by the pipeline are retained to reduce surface area:
  - Header detection (detect_header_row, build_headers)
  - Row/blank filtering (_drop_fully_blank_rows)
  - Numeric detection & normalization (is_numeric_candidate, normalize_numeric_series)
  - Basic text normalization helpers (_normalize_whitespace_and_minus)
This allows removal of the external csv_excel_cleaner package for a leaner codebase.
"""
⋮----
# -----------------------------
# Null tokens (lowercased set)
⋮----
NULL_TOKENS = {
_NULL_TOKENS_LOWER = {t.lower() for t in NULL_TOKENS}
CURRENCY_PATTERN = re.compile(
SEPARATORS_PATTERN = re.compile(r"[\u00A0\u2000-\u200B'\s]+")
KMB_SUFFIX_PATTERN = re.compile(r"\s*([kKmMbB])\s*$")
def _normalize_whitespace_and_minus(series: pd.Series) -> pd.Series
⋮----
s = series.astype(str)
s = s.str.replace("\u2212", "-", regex=False)
s = s.str.replace("\u00a0", " ", regex=False)
s = s.str.replace(r"[\u2000-\u200B]", " ", regex=True)
⋮----
def _drop_fully_blank_rows(df: pd.DataFrame) -> pd.DataFrame
⋮----
is_na = df.isna()
lowered = df.astype(str).apply(lambda s: s.str.strip().str.lower(), axis=0)
is_token_blank = lowered.isin(_NULL_TOKENS_LOWER)
is_blank = is_na | is_token_blank
keep_mask = ~is_blank.all(axis=1)
⋮----
def _handle_percent(series: pd.Series)
⋮----
s = series
mask = s.str.contains("%", na=False)
s = s.str.replace("%", "", regex=False)
⋮----
def _detect_negatives(series: pd.Series)
⋮----
mask_paren = s.str.match(r"^\(.*\)$", na=False)
s = s.mask(mask_paren, s.str.replace(r"^[\(](.*)[\)]$", r"\1", regex=True))
mask_trail = s.str.endswith("-", na=False)
s = s.mask(mask_trail, s.str[:-1])
negative = mask_paren | mask_trail
⋮----
def _extract_kmb_multiplier(series: pd.Series)
⋮----
matches = series.str.extract(KMB_SUFFIX_PATTERN.pattern)
suffix = matches[0].fillna("")
mult = pd.Series(1.0, index=series.index, dtype=float)
mult = mult.mask(suffix.str.lower() == "k", 1e3)
mult = mult.mask(suffix.str.lower() == "m", 1e6)
mult = mult.mask(suffix.str.lower() == "b", 1e9)
cleaned = series.str.replace(KMB_SUFFIX_PATTERN.pattern, "", regex=True)
⋮----
def _strip_currency_and_separators(series: pd.Series) -> pd.Series
⋮----
s = series.str.replace(CURRENCY_PATTERN.pattern, "", regex=True)
s = s.str.replace(SEPARATORS_PATTERN.pattern, "", regex=True)
⋮----
def _normalize_decimal_thousands(series: pd.Series) -> pd.Series
⋮----
has_dot = s.str.contains(r"\.", na=False)
has_comma = s.str.contains(",", na=False)
both = has_dot & has_comma
last_dot = s.str.rfind(".")
last_comma = s.str.rfind(",")
decimal_is_dot = both & (last_dot > last_comma)
decimal_is_comma = both & (last_comma > last_dot)
out = s.copy()
mask = decimal_is_dot
out = out.mask(mask, out.where(~mask, out.str.replace(",", "", regex=False)))
mask = decimal_is_comma
tmp = out.where(~mask, out.str.replace(".", "", regex=False))
tmp = tmp.where(~mask, tmp.str.replace(",", ".", regex=False))
out = out.mask(mask, tmp)
only_comma = has_comma & (~has_dot)
looks_decimal_comma = only_comma & s.str.contains(r",\d{1,2}$", na=False)
out = out.mask(
mask = only_comma & (~looks_decimal_comma)
⋮----
only_dot = has_dot & (~has_comma)
looks_decimal_dot = only_dot & s.str.contains(r"\.\d+$", na=False)
mask = only_dot & (~looks_decimal_dot)
out = out.mask(mask, out.where(~mask, out.str.replace(".", "", regex=False)))
⋮----
def normalize_numeric_series(series: pd.Series) -> pd.Series
⋮----
s = series.astype(object)
s = s.where(~s.isna(), None)
s = _normalize_whitespace_and_minus(s).str.strip()
lower = s.str.lower()
s = s.mask(lower.isin(_NULL_TOKENS_LOWER), np.nan)
s = s.fillna("")
⋮----
s = _strip_currency_and_separators(s)
s = _normalize_decimal_thousands(s)
nums = pd.to_numeric(s, errors="coerce")
nums = nums * kmb_multiplier
nums = nums.mask(negative_mask, -nums)
nums = nums.mask(percent_mask, nums / 100.0)
nums = nums.replace([np.inf, -np.inf], np.nan)
⋮----
s = series.dropna()
⋮----
s_str = _normalize_whitespace_and_minus(s.astype(str)).str.strip()
s_str = s_str.mask(s_str.str.lower().isin(_NULL_TOKENS_LOWER), np.nan).dropna()
⋮----
s_str = s_str.sample(sample_n, random_state=42)
parsed = normalize_numeric_series(s_str)
⋮----
def _is_year_like(cell: object) -> bool
⋮----
s = str(cell).strip()
⋮----
y = int(s)
⋮----
def _non_empty_mask(series: pd.Series) -> pd.Series
⋮----
s = series.astype(str).str.strip()
⋮----
def _row_non_empty_ratio(df: pd.DataFrame, row_idx: int) -> float
⋮----
row = df.iloc[row_idx]
mask = _non_empty_mask(row)
⋮----
def _row_year_signal(df: pd.DataFrame, row_idx: int)
⋮----
years = []
⋮----
inc = all(x < y for x, y in zip(years, years[1:])) if len(years) >= 2 else False
⋮----
start = header_row + 1
end = min(df.shape[0], start + lookahead)
⋮----
body = df.iloc[start:end]
⋮----
score = 0.0
col0 = body.iloc[:, 0].astype(str).str.strip()
has_alpha = col0.str.contains(r"[A-Za-z]", regex=True, na=False)
not_numeric = normalize_numeric_series(col0).isna()
⋮----
numeric_cols = []
⋮----
ser = body.iloc[:, j]
parsed = normalize_numeric_series(ser)
⋮----
top_n = min(top_n, df.shape[0])
best_idx = 0
best_score = float("-inf")
⋮----
density = _row_non_empty_ratio(df, r)
⋮----
type_score = _type_consistency_score(df, r, lookahead)
penalty = (1.0 - density) * 0.5
score = (
⋮----
best_score = score
best_idx = r
⋮----
def _dedupe_headers(headers: List[str]) -> List[str]
⋮----
seen: Dict[str, int] = {}
out: List[str] = []
⋮----
def build_headers(df: pd.DataFrame, header_row: int, verbose: bool = False)
⋮----
row = df.iloc[header_row].tolist()
headers: List[str] = []
⋮----
s = re.sub(r"\s+", " ", str(val).strip())
⋮----
next_row_raw = df.iloc[header_row + 1]
# Handle NaN values properly before converting to string
next_row = next_row_raw.fillna("").astype(str).str.strip()
# Filter out empty strings and "nan" strings that come from NaN conversion
non_empty_mask = (next_row != "") & (next_row.str.lower() != "nan")
non_empty_ratio = non_empty_mask.mean() if len(next_row) else 0.0
alpha_ratio = next_row.str.contains(r"[A-Za-z]", regex=True, na=False).mean()
year_count = sum(_is_year_like(x) for x in next_row.iloc[1:])
⋮----
flat = []
⋮----
n_clean = re.sub(r"\s+", " ", n) if n else ""
⋮----
headers = flat
⋮----
headers = _dedupe_headers(headers)
⋮----
__all__ = [
````

## File: cli.py
````python
"""Command-line interface for the unified data processing pipeline.
Usage (examples):
    python -m data_processing.cli path/to/file.csv
    python -m data_processing.cli path/to/file.xlsx --mode schema_only
    python -m data_processing.cli path/to/file.csv --json --output result.json
The CLI prints a concise human-readable summary by default; use --json for full payload.
"""
⋮----
def _summarize(payload: Dict[str, Any]) -> str
⋮----
dataset = payload.get("dataset", {})
cols = dataset.get("column_names", [])
preview_cols = cols[:8]
more = "" if len(cols) <= 8 else f" (+{len(cols)-8} more)"
lines = [
⋮----
col_summaries = payload.get("columns", {})
sample_keys = list(col_summaries.keys())[:3]
⋮----
c = col_summaries[k]
⋮----
def main() -> None
⋮----
parser = argparse.ArgumentParser(
⋮----
args = parser.parse_args()
path = Path(args.file)
⋮----
# Target common noisy warnings we expect
⋮----
config = {
result = run_processing_pipeline(str(path), mode=args.mode, config=config)
payload = result["payload"]
⋮----
out_path = Path(args.output)
⋮----
if __name__ == "__main__":  # pragma: no cover
````

## File: data_profiler.py
````python
class DataProfiler
⋮----
"""Profiling engine producing per-column stats and quality metrics."""
⋮----
"""Generate comprehensive profile for dataframe."""
profile = {
⋮----
def _get_dataset_info(self, df: pd.DataFrame) -> Dict[str, Any]
⋮----
"""Get basic dataset information."""
⋮----
"""Generate detailed profile for single column."""
⋮----
# Type-specific statistics
detected_type = type_info.get("detected_type", "unknown")
⋮----
"""Get most frequent values in series."""
value_counts = series.value_counts()
⋮----
def _calculate_uniqueness_score(self, series: pd.Series) -> float
⋮----
"""Calculate uniqueness score for series."""
unique_ratio = series.nunique() / len(series)
# Score based on uniqueness ratio
⋮----
return 100.0  # Perfectly unique
⋮----
return unique_ratio * 100  # Scale lower values
def _get_numeric_statistics(self, series: pd.Series) -> Dict[str, Any]
⋮----
"""Get numeric statistics for series."""
clean_series = series.dropna()
⋮----
stats = {
⋮----
def _get_date_statistics(self, series: pd.Series) -> Dict[str, Any]
⋮----
"""Get date statistics for series."""
⋮----
# Ensure datetime dtype; attempt conversion if necessary
⋮----
converted = pd.to_datetime(clean_series, errors="coerce")
converted = converted.dropna()
⋮----
clean_series = converted
min_v = clean_series.min()
max_v = clean_series.max()
⋮----
range_days = int((max_v - min_v).days)
⋮----
range_days = None
⋮----
def _get_categorical_statistics(self, series: pd.Series) -> Dict[str, Any]
⋮----
"""Get categorical statistics for series."""
⋮----
value_counts = clean_series.value_counts()
⋮----
def _get_text_statistics(self, series: pd.Series) -> Dict[str, Any]
⋮----
"""Get text statistics for series."""
⋮----
# Text analysis
text_lengths = clean_series.astype(str).str.len()
⋮----
"""Calculate comprehensive quality metrics."""
metrics = {
# Completeness score
total_cells = df.size
null_cells = df.isnull().sum().sum()
⋮----
# Uniqueness score
uniqueness_scores = []
⋮----
# Validity score (based on type detection confidence)
validity_scores = []
⋮----
confidence = type_data.get("confidence_score", 0.5)
⋮----
# Consistency score (based on data consistency)
⋮----
# Overall score (weighted average)
weights = {
overall_score = (
⋮----
def _calculate_consistency_score(self, df: pd.DataFrame) -> float
⋮----
"""Calculate data consistency score."""
consistency_issues = 0
total_checks = 0
# Check for consistent data types across columns
⋮----
# Check for mixed data types
⋮----
types = {type(v) for v in df[column].dropna().tolist()}
⋮----
consistency_score = max(
⋮----
# Removed correlation/outlier detection and aggregate quality scoring for simplicity.
````

## File: pipeline.py
````python
# Reuse cleaning logic
⋮----
# ---------------------------------------------------------------------------
# Internal helpers for structured cleaning report (augment existing cleaners)
⋮----
def _load_raw(file_path: str) -> Tuple[pd.DataFrame, str]
⋮----
ext = Path(file_path).suffix.lower()
⋮----
# Only first sheet per requirements
df_raw = pd.read_excel(file_path, sheet_name=0, header=None, dtype=object)
⋮----
# Load raw with no header for structural normalization
df_raw = pd.read_csv(file_path, header=None, dtype=object, engine="python")
⋮----
"""Perform structural + cell-level cleaning and build a report.
    We replicate core logic from existing cleaners to capture a cleaning report.
    """
report: Dict[str, Any] = {
⋮----
df_work = _drop_fully_blank_rows(df_raw)
# Optional: treat first row as data (no header row in file)
⋮----
headers = [f"Column_{i+1}" for i in range(df_work.shape[1])]
body = df_work.reset_index(drop=True)
⋮----
# Header detection
header_row = detect_header_row(df_work, verbose=False)
⋮----
# build_headers returns start_row = header_row + (1 or 2) already
body = df_work.iloc[start_row:].reset_index(drop=True)
⋮----
cleaned = pd.DataFrame(columns=headers)
⋮----
# Remove possible repeated header lines
# (Using simple heuristic: rows fully matching headers are dropped)
def _norm_row(row)
⋮----
hdr_norm = [str(h).strip() for h in headers]
keep_mask = []
⋮----
body = body.loc[keep_mask].reset_index(drop=True)
df = body.copy()
⋮----
# First column rename heuristic
⋮----
first_col = df.columns[0]
col0_text_ratio = (
⋮----
other_numeric = [is_numeric_candidate(df[c]) for c in df.columns[1:]]
⋮----
# Identify numeric columns
numeric_cols = []
⋮----
# Normalize numeric columns
⋮----
# Text cols + null token mapping counts
null_token_counts: Dict[str, int] = {}
⋮----
s = _normalize_whitespace_and_minus(df[c].astype(object)).str.strip()
lower = s.str.lower()
mask = lower.isin(_NULL_TOKENS_LOWER)
⋮----
# Final drop of fully blank rows
df = _drop_fully_blank_rows(df)
⋮----
dataset_info = profile.get("dataset_info", {})
columns_profile = profile.get("columns", {})
# Extract full ordered list of metric labels (first column) if it was renamed to 'Metric'.
metrics_list = None
⋮----
raw_metrics = df["Metric"].dropna().astype(str).map(lambda s: s.strip())
# Keep duplicates / ordering exactly as appears in cleaned data.
⋮----
metrics_list = raw_metrics.tolist()
⋮----
payload: Dict[str, Any] = {
⋮----
# Top-level placeholder for metric list will be inserted just after dataset (insertion order) if available.
⋮----
# Insert immediately after dataset by reconstructing ordered dict (Python 3.7+ preserves insertion order)
ordered: Dict[str, Any] = {}
⋮----
# Use singular 'Metric' to align with column name conveying it's the content of that column
⋮----
# Remainder
⋮----
# Full mode
sample_size = int(config.get("sample_size", 10))
sample_rows = (
# Assemble compact column summaries
col_summaries = {}
⋮----
stats = cprof.get("statistics", {}) or {}
# Minimal numeric stats subset
minimal_stats_keys = [
slim_stats = {k: stats[k] for k in minimal_stats_keys if k in stats}
top_vals = cprof.get("most_frequent_values", [])[:5]
⋮----
# Metric list will be inserted after dataset if present.
⋮----
payload = ordered
⋮----
"""Primary orchestrator: load -> clean -> infer types -> profile -> build payload.
    Parameters
    ----------
    file_path : str
        Path to CSV or Excel file (first sheet only for Excel).
    mode : str
        'full' or 'schema_only'.
    config : dict, optional
        Additional configuration (sample_size, etc.).
    Returns
    -------
    dict with keys: cleaned_df, payload, cleaning_report, profile, type_info
    """
⋮----
cfg = config or {}
⋮----
# Type inference after cleaning
type_inferencer = TypeInferencer()
type_info = type_inferencer.infer_types(cleaned_df) if not cleaned_df.empty else {}
# Profile (using existing profiler, but expects type_info)
profiler = DataProfiler()
profile = (
payload = _build_llm_payload(
````

## File: pytest.ini
````
[pytest]
filterwarnings =
    ignore:Could not infer format:UserWarning
    ignore:Parsing dates involving a day of month:DeprecationWarning
````

## File: README.md
````markdown
# Unified Data Processing Pipeline

Unified, LLM-friendly ingestion pipeline that loads a raw CSV / Excel file, applies light cleaning, infers types, profiles data quality, and returns both JSON metadata for LLMs and cleaned datasets for analysis scripts.

## What It Does

* **Load**: CSV (no header assumption) or first sheet of Excel
* **Clean**: header detection (or synthesize), blank row removal, numeric normalization (%, K/M/B, currency), null token mapping, first-column heuristic rename to `Metric`
* **Infer**: currency, percentage, date, id, integer/float, categorical, text (confidence-ordered)
* **Profile**: per-column stats + quality metrics (completeness, uniqueness, validity, consistency + overall)
* **Return**: Three outputs for LLM-orchestrator workflows

## Pipeline Outputs

The pipeline returns a dictionary with **three key components**:

1. **`cleaned_df`** *(pandas.DataFrame)* - Full cleaned dataset for analysis scripts
2. **`payload`** *(dict)* - JSON-serializable metadata + samples for LLM consumption  
3. **`cleaning_report`** *(dict)* - Transparency on transformations applied

### Intended Workflow
```
1. Pipeline processes file → {cleaned_df, payload, cleaning_report, ...}
2. LLM receives payload JSON → writes analysis script based on metadata/samples
3. Orchestrator executes script on cleaned_df → captures results
4. LLM interprets results → provides final answer to user
```

### Programmatic vs CLI Usage
- **Programmatic**: Returns all components including cleaned DataFrame
- **CLI**: Outputs only JSON payload (for LLM integration)

## Key Entry Points

**Programmatic API:**
```python
from data_processing import run_processing_pipeline

result = run_processing_pipeline('data.csv', mode='full')
# result['cleaned_df']      → pandas DataFrame for analysis scripts  
# result['payload']         → JSON metadata + samples for LLM
# result['cleaning_report'] → transformation details
```

**Command Line Interface:**
```powershell
python -m data_processing.cli <file> [--mode full|schema_only] [--json] [--output out.json] [--sample-size N] [--treat-first-row-as-data] [--suppress-warnings]
```

## Examples

### CLI Usage
```powershell
python -m data_processing.cli .\BS.csv --mode full --json --output payload.json
```

### Programmatic Usage
```python
from data_processing import run_processing_pipeline

# Process file and get all outputs
result = run_processing_pipeline('BS.csv', mode='full')

# For LLM: JSON metadata + samples
llm_input = result['payload']

# For analysis script: cleaned DataFrame  
cleaned_data = result['cleaned_df']
print(f"Dataset shape: {cleaned_data.shape}")
print(f"Columns: {list(cleaned_data.columns)}")
```

Sample summary output:
```
Rows: 120  Columns: 8
Columns: id, date, revenue, margin, region, segment, users, notes
Mode: full  Version: 1.0.0
  - revenue: type=float null%=0.00 unique%=95.83
  - margin: type=float null%=1.67 unique%=42.50
  - region: type=categorical null%=0.00 unique%=12.50
```

## JSON Payload Structure (full mode)

Actual key order may vary slightly; below reflects current implementation (Python 3.7+ preserves insertion order as built).

```jsonc
{
  "dataset": {
    "rows": 120,
    "columns": 8,
    "column_names": ["id", "date", "revenue", "margin", "region", "segment", "users", "notes"],
    "dtypes": { "id": "int64", "date": "object", "revenue": "float64", "margin": "float64", "users": "float64" }
  },
  "Metric": [
    "Assets", "Cash & Equivalents", "Short-Term Investments", "..." // present only if a first-column rename to Metric occurred
  ],
  "columns": {
    "revenue": {
      "type": "float",
      "null_pct": 0.0,
      "unique_pct": 95.83,
      "top_values": [ { "value": "123.45", "count": 1, "percentage": 0.83 } ],
      "stats": { "min": 12.5, "max": 9983.2, "mean": 182.7, "median": 120.4, "std": 55.3 }
    },
    "date": {
      "type": "date",
      "null_pct": 0.0,
      "unique_pct": 100.0,
      "top_values": [],
      "stats": { "min_date": "2024-01-01", "max_date": "2024-04-05", "date_range_days": 95 }
    }
  },
  "quality": {
    "completeness_score": 99.2,
    "uniqueness_score": 88.5,
    "validity_score": 97.0,
    "consistency_score": 100.0,
    "overall_score": 96.3
  },
  "sample_rows": [ { "id": 1, "date": "2024-01-01", "revenue": 123.45, "margin": 0.32, "users": 1200 } ],
  "cleaning_report": {
    "header_row": 0,
    "renamed_columns": { "Column_1": "Metric" },
    "numeric_columns": ["revenue", "margin", "users"],
    "rows_before": 121,
    "rows_after": 120,
    "null_token_mappings": {},
    "file_kind": "csv"
  },
  "mode": "full",
  "version": "v1"
}
```

### Key Notes
* `Metric` (singular) is an optional top-level list mirroring the cleaned first column values when that column was heuristically renamed to `Metric`. Duplicates & order are preserved exactly as in the cleaned dataframe.
* `columns` -> per-column summary: detected type, null & unique percentages, up to 5 top values, and a minimal stats subset (varies by type).
* `quality` -> dataset-level quality metrics (lightweight heuristics, bounded 0–100).
* `cleaning_report` -> transparency on structural transformations (header row index, renames, numeric columns detected, null token replacements, row counts).
* `version` -> current payload schema version (`v1`).

### schema_only Mode
Returns a trimmed payload:

```jsonc
{
  "dataset": { "rows": 120, "columns": 8, "column_names": ["id", "date", ...] },
  "Metric": ["Assets", "Cash & Equivalents", "..."] // optional as above
  "columns": { "id": { "type": "integer" }, "date": { "type": "date" }, ... },
  "mode": "schema_only",
  "version": "v1"
}
```

Omitted: detailed stats, quality, sample_rows, cleaning_report.

## Configuration Flags

| Flag                        | Description                                                                |
| --------------------------- | -------------------------------------------------------------------------- |
| `--mode`                    | `full` (default) or `schema_only`                                          |
| `--sample-size N`           | Max sample rows in `sample_rows` (full mode)                               |
| `--treat-first-row-as-data` | Bypass header detection; generate `Column_1..n`; disables rename heuristic |
| `--suppress-warnings`       | Suppress pandas/date parsing warnings                                      |
| `--json`                    | Print JSON payload to stdout                                               |
| `--output path`             | Write JSON payload to file                                                 |

## Cleaning Logic (Summary)

Implemented in `data_processing/cleaning_utils.py`:
* Header detection: heuristic scoring of candidate rows (alpha density, blanks)
* Renaming heuristic: if first column is text-dominant and others are mostly numeric → rename to `Metric`
* Synthetic headers: if `--treat-first-row-as-data` set
* Numeric normalization: `%` to 0–1 float, currency symbols & commas stripped, `K/M/B` scaled, dash/minus normalization
* Null token mapping: common tokens (e.g. `na`, `n/a`, `null`, `-`, empty) converted to `NaN`

## Type Inference

`TypeInferencer` applies prioritized detectors (currency -> percentage -> date -> id -> numeric -> categorical -> text) with confidence thresholds.

## Profiling

`DataProfiler` generates:
* Per-column: detected type, null %, unique %, most frequent values (value/count/percentage), minimal statistics subset per type.
* Dataset-level quality: completeness (non-null ratio), uniqueness (average distinct proportion), validity (simple rule-of-thumb checks by type), consistency (light heuristic), overall weighted score.

## Testing

Run tests:
```powershell
pytest -q
```
````

## File: type_inference.py
````python
class TypeInferencer
⋮----
"""Type inference with confidence scoring for currency, percentage, date, id, numeric, categorical, and text."""
def infer_types(self, df: pd.DataFrame) -> Dict[str, Any]
⋮----
"""Infer types for all columns in dataframe."""
type_info = {}
⋮----
column_data = df[column]
⋮----
def _infer_column_type(self, series: pd.Series, column_name: str) -> Dict[str, Any]
⋮----
"""Infer type for a single column with confidence scoring."""
# Remove null values for type detection
clean_series = series.dropna()
⋮----
null_percentage = (len(series) - len(clean_series)) / len(series) * 100
# Try different type detectors in order of specificity
type_detectors = [
⋮----
result = detector(clean_series, column_name)
if result["confidence_score"] > 0.7:  # High confidence threshold
⋮----
# Fallback to text type
⋮----
def _detect_currency(self, series: pd.Series, column_name: str) -> Dict[str, Any]
⋮----
"""Detect currency values."""
patterns = [
currency_keywords = [
matches = 0
total = len(series)
⋮----
value_str = str(value).strip()
⋮----
confidence = matches / total if total > 0 else 0
# Boost confidence if column name suggests currency
name_lower = column_name.lower()
⋮----
confidence = min(confidence + 0.2, 1.0)
⋮----
def _detect_percentage(self, series: pd.Series, column_name: str) -> Dict[str, Any]
⋮----
"""Detect percentage values."""
⋮----
percentage_keywords = [
⋮----
# Boost confidence if column name suggests percentage
⋮----
def _detect_date(self, series: pd.Series, column_name: str) -> Dict[str, Any]
⋮----
"""Detect date/datetime values."""
date_keywords = [
# Try pandas to_datetime
⋮----
# Reject if all values look like plain numbers (avoid misclassifying numeric metrics)
⋮----
parsed_dates = pd.to_datetime(series, errors="coerce")
valid_dates = parsed_dates.notna()
if valid_dates.sum() > len(series) * 0.8:  # 80% success rate
date_format = self._detect_date_format(series)
⋮----
"timezone": "UTC",  # Default assumption
⋮----
# Check for common date patterns
date_patterns = [
⋮----
r"^\d{4}-\d{2}-\d{2}$",  # YYYY-MM-DD
r"^\d{2}/\d{2}/\d{4}$",  # MM/DD/YYYY
r"^\d{2}-\d{2}-\d{4}$",  # MM-DD-YYYY
r"^\d{2}\.\d{2}\.\d{4}$",  # MM.DD.YYYY
r"^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$",  # DD Mon YYYY
r"^[A-Za-z]{3}\s+\d{1,2},\s+\d{4}$",  # Mon DD, YYYY
⋮----
confidence = matches / len(series) if len(series) > 0 else 0
# Boost confidence if column name suggests date
⋮----
confidence = min(confidence + 0.3, 1.0)
⋮----
def _detect_id(self, series: pd.Series, column_name: str) -> Dict[str, Any]
⋮----
"""Detect ID columns (unique identifiers)."""
id_keywords = ["id", "key", "code", "identifier", "uuid", "index", "number"]
# Check if values are unique
unique_ratio = len(series.unique()) / len(series)
# Check format patterns
is_numeric = pd.api.types.is_numeric_dtype(series)
is_string = pd.api.types.is_object_dtype(series)
# Common ID patterns
id_patterns = [
⋮----
r"^\d+$",  # Numeric ID
r"^[A-Z0-9]+$",  # Alphanumeric uppercase
r"^[a-z0-9]+$",  # Alphanumeric lowercase
r"^[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12}$",  # UUID
r"^\d{4}-\d{4}-\d{4}-\d{4}$",  # Credit card format
⋮----
confidence = 0.0
# High confidence for unique numeric/string columns with ID keywords
⋮----
confidence = 0.9
⋮----
confidence = 0.8
⋮----
confidence = 0.7
⋮----
def _detect_numeric(self, series: pd.Series, column_name: str) -> Dict[str, Any]
⋮----
"""Detect numeric values."""
⋮----
# Try to convert to numeric
numeric_series = pd.to_numeric(series, errors="coerce")
valid_numeric = numeric_series.notna()
if valid_numeric.sum() > len(series) * 0.8:  # 80% success rate
# Check for integer vs float
is_integer = (
⋮----
"""Detect categorical values."""
⋮----
# Categorical if unique values are limited compared to total
⋮----
def _detect_text(self, series: pd.Series, column_name: str) -> Dict[str, Any]
⋮----
"""Detect text/string values (fallback)."""
⋮----
"confidence_score": 0.8,  # Default fallback confidence
⋮----
def _extract_currency_symbol(self, series: pd.Series) -> str
⋮----
"""Extract currency symbol from series."""
currency_symbols = ["$", "€", "£", "¥", "₹", "₽", "₩", "₪"]
⋮----
return "$"  # Default fallback
def _detect_date_format(self, series: pd.Series) -> str
⋮----
"""Detect date format pattern."""
date_formats = [
⋮----
def _get_validation_rules(self, detected_type: str) -> List[str]
⋮----
"""Get validation rules based on detected type."""
rules_map = {
````
