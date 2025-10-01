**suggestion 1:
**

# Implementation Plan for Pipeline Speed Improvements


This document outlines a prioritized implementation plan for optimizing preprocessing and analysis performance.  
Each improvement contains a **problem definition**, **detailed suggested changes**, and the **expected outcome**.

---

## Tier 1 – Must Do (Core Bottlenecks, >50% Time Saved)

### 1. Eliminate Double Parquet Load in Analysis
**Problem:**  
Currently, the orchestrator downloads and reads `cleaned.parquet`, then the worker subprocess re-reads the same file. This duplicates I/O and deserialization, adding 3–6 seconds per query.

**Suggested Change:**  
- **Files:** `main.py` (orchestrator), `worker.py` (subprocess).  
- **Change:**  
  - In `main.py`, after downloading and loading parquet into a DataFrame, serialize it into Apache Arrow IPC format using `pyarrow.ipc`.  
  - Pass the IPC buffer to `worker.py` via stdin instead of a file path.  
  - Update `worker.py` to read from stdin and deserialize IPC back into a DataFrame.  

**Expected Outcome:**  
Removes redundant I/O and deserialization, cutting **3–6 seconds** from each analysis run.

---

### 2. Overhaul Preprocessing Engine (Polars or Optimized Pandas)
**Problem:**  
Preprocessing with Pandas uses the Python engine for CSVs, multiple sequential regex `.str.replace` calls, and type inference loops. This is CPU-bound and slow.

**Suggested Change:**  
- **Files:** `pipeline_adapter.py`  
- **Change:**  
  - Replace Pandas with **Polars** for file loading, normalization, and type inference.  
  - If Pandas must be retained:  
    - Use `pd.read_csv(..., engine="c", dtype_backend="pyarrow")`.  
    - Combine regex normalizations into a single `.replace` or vectorized `np.where`.  
    - Use fewer sample rows for type inference.  

**Expected Outcome:**  
Cuts preprocessing from **10–20s → 3–8s**, leveraging parallelized execution.

---

### 3. Process Data In-Memory (No /tmp Disk Writes)
**Problem:**  
Current flow downloads to `/tmp`, processes, writes intermediate files back to `/tmp`, then re-uploads to GCS. Disk I/O adds ~1–2 seconds and complicates cleanup.

**Suggested Change:**  
- **Files:** `preprocess_service.py`, `pipeline_adapter.py`.  
- **Change:**  
  - Use `blob.download_as_bytes()` → wrap in `io.BytesIO()` → feed directly to Pandas/Polars.  
  - Write cleaned parquet to another `io.BytesIO()` buffer.  
  - Upload to GCS using `upload_from_file()` with the buffer (no disk step).  

**Expected Outcome:**  
Saves **1–2 seconds** per preprocessing job and simplifies temporary file handling.

---

## Tier 2 – High Value (20–40% Time Saved)

### 4. Parallelize All GCS and Firestore Writes
**Problem:**  
Artifact uploads (cleaned parquet, payload.json, cleaning_report.json) and Firestore writes run sequentially, costing 1–3 seconds per stage.

**Suggested Change:**  
- **Files:** `preprocess_service.py`, `main.py`.  
- **Change:**  
  - Use `asyncio.gather()` or `ThreadPoolExecutor` to upload all artifacts in parallel.  
  - Batch Firestore writes using `firestore_client.batch()`.  

**Expected Outcome:**  
Reduces persistence overhead from **2–4s → <1s**.

---

### 5. Combine Gemini Calls (Codegen + Summary)
**Problem:**  
Two separate API calls are made to Gemini: one for Python code, one for summary. This doubles latency and token usage.

**Suggested Change:**  
- **Files:** `gemini_client.py`, `main.py`.  
- **Change:**  
  - Update the prompt format to request both **CODE** and **SUMMARY** in a single structured response.  
  - Parse the response into separate outputs.  

**Expected Outcome:**  
Saves **1–3s per query**, halves token costs, and reduces network latency.

---

## Tier 3 – Solid Optimizations (<20% Each)

### 6. Increase Cloud Run CPU Resources for Preprocessing
**Problem:**  
Preprocessing is CPU-bound and benefits from multiple cores.

**Suggested Change:**  
- **Files:** Deployment configuration (`cloudbuild.yaml`, `gcloud run deploy` commands).  
- **Change:**  
  - Deploy `preprocess-svc` with `--cpu=2 --memory=2Gi`.  
  - If Polars is used, it will automatically parallelize across cores.  

**Expected Outcome:**  
Improves preprocessing throughput, especially for larger datasets. Speedups vary (10–30%).

---

### 7. Lazy Load Parquet for Metadata Queries
**Problem:**  
Even for simple metadata questions, orchestrator downloads the full `cleaned.parquet` file.

**Suggested Change:**  
- **Files:** `main.py` (orchestrator).  
- **Change:**  
  - Always load `payload.json` first.  
  - Implement logic to detect if question can be answered from metadata alone.  
  - Skip downloading parquet for those queries.  

**Expected Outcome:**  
Makes simple queries feel **instantaneous** (saves 1–3s).

---

### 8. Cache Impersonated Credentials in sign-upload-url
**Problem:**  
`sign-upload-url` function re-creates impersonated credentials for every request, adding latency.

**Suggested Change:**  
- **Files:** `sign_upload_url.py`.  
- **Change:**  
  - Implement global `_cached_credentials` with TTL ~55 minutes (credentials valid 1h).  
  - Reuse cached credentials across requests.  

**Expected Outcome:**  
Saves ~50–100ms per signed URL request after the first one.

---

# 🎯 Expected Cumulative Outcomes
- **Preprocessing:** 10–20s → **3–7s**  
- **Analysis:** 8–15s → **4–7s**  
- **Total Pipeline:** ~18–35s → **7–14s** (≈60–70% faster overall).  
- **Additional Benefits:** Lower token usage, better free-tier utilization, simplified code paths, improved perceived latency.

**suggestion 2:
**

Implementation Plan: AI Data Analysis Pipeline OptimizationThis document provides a prioritized, actionable plan for significantly improving the performance of the AI Data Analysis pipeline. The changes are grouped into tiers based on their expected impact on overall processing speed.Executive SummaryThe current pipeline takes approximately 18-35 seconds from file upload to final analysis. By implementing the changes outlined below, we project a 50-70% reduction in processing time, bringing the total pipeline duration down to 7-15 seconds.Tier 1: Foundational Rearchitecture (High Impact)These three changes address the largest bottlenecks and will provide the most significant performance gains.1. Overhaul Preprocessing Engine with PolarsProblem Definition: The current preprocessing stage (pipeline_adapter.py) uses Pandas with a slow Python engine for CSVs and multiple, sequential, regex-heavy operations. This makes the data cleaning process CPU-bound and slow.Suggested Change:Update Dependencies: In backend/run-preprocess/requirements.txt, add polars and remove openpyxl if Polars' native Excel reader is sufficient.- pandas==2.2.2
- openpyxl==3.1.5
+ pandas==2.2.2 # Keep for compatibility if needed, but phase out
+ polars[xlsx]>=0.20.0
Rewrite Pipeline Logic: In backend/run-preprocess/pipeline_adapter.py, replace the core Pandas functions with their Polars equivalents. Polars can often chain multiple operations into a single, highly optimized pass.File Reading: Replace pd.read_csv and pd.read_excel with pl.read_csv and pl.read_excel. Polars' CSV reader is significantly faster.Normalization: Replace sequential .str.replace() calls with a single Polars select statement using chained .str.replace_all() expressions or the more powerful when/then/otherwise for conditional logic.# Example of chained expressions in Polars
# in normalize_numeric_series function replacement

df = df.with_columns(
    pl.col(numeric_column).str.strip_chars()
      .str.replace_all(CURRENCY_PATTERN, "")
      .str.replace_all(KMB_PATTERN, "")
      # ... other replacements ...
      .cast(pl.Float64, strict=False)
)
Expected Outcome: A 3-5x speedup in the preprocessing stage. Total preprocessing time will decrease from 10-20 seconds to 3-8 seconds.2. Eliminate Duplicate Parquet Read in Analysis StageProblem Definition: The orchestrator (main.py) downloads the Parquet file, and the worker subprocess (worker.py) reads that same file again from disk. This doubles the I/O and deserialization cost for the most expensive data asset.Suggested Change:Orchestrator (backend/functions/orchestrator/main.py):Read the Parquet file into a Pandas/Arrow object once.Serialize the DataFrame to the in-memory Apache Arrow IPC format.Pass this binary data directly to the worker process's stdin.# In main.py, inside _events function
import pyarrow as pa
import pandas as pd

df = pd.read_parquet(parquet_local)

# Serialize to Arrow IPC format
ipc_buffer = pa.BufferOutputStream()
with pa.ipc.new_stream(ipc_buffer, df.schema) as writer:
    writer.write_pandas(df)
ipc_bytes = ipc_buffer.getvalue().to_pybytes()

# Pass to subprocess stdin
proc = subprocess.run(
    [sys.executable, worker_path],
    input=ipc_bytes,  # Pass bytes to stdin
    capture_output=True,
    timeout=WORKER_TIMEOUT_SECONDS,
)
Worker (backend/functions/orchestrator/worker.py):Modify the worker to read from stdin instead of a file path.Deserialize the Arrow IPC data back into a DataFrame.# In worker.py, inside main function
import pyarrow as pa
import sys

# Read from stdin
ipc_bytes = sys.stdin.buffer.read()

# Deserialize from Arrow IPC format
with pa.ipc.open_stream(ipc_bytes) as reader:
    df = reader.read_pandas()

# The rest of the execution logic remains the same
Expected Outcome: Reduces analysis time by 2-5 seconds by eliminating redundant file I/O and processing.3. Fuse Gemini API CallsProblem Definition: The analysis stage makes two separate, sequential API calls to Gemini: one for code generation and another for the summary. This doubles the network latency associated with the LLM.Suggested Change:Update Prompt (backend/functions/orchestrator/gemini_client.py): Modify the prompt in generate_analysis_code to request both the code and a summary in a single, structured output.# New prompt structure
prompt = f"""
Analyze the data based on the question: "{question}"
Schema: {schema_snippet}

First, generate the Python code to perform the analysis.
Second, provide a brief, one-paragraph summary of the likely outcome.

Return the output in the following format, and nothing else:

[CODE_START]
```python
def run(df, ctx):
    # ... generated code ...
[CODE_END][SUMMARY_START]A brief summary of the analysis findings