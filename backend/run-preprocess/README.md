# Preprocess Service (Cloud Run)

Region: `europe-west4`  •  Project: `ai-data-analyser`  •  Bucket: `ai-data-analyser-files`

This service is the HTTP target of an Eventarc trigger for `google.cloud.storage.object.v1.finalized` events. When a raw file is uploaded under the `users/{uid}/sessions/{sid}/datasets/{datasetId}/raw/` prefix, it:

1. Downloads the raw CSV/XLSX bytes into memory (no `/tmp` in the happy path).
2. Runs the pipeline adapter (Polars CSV by default; Excel via pandas) to clean + profile.
3. Writes:
   - `cleaned/cleaned.parquet`
   - `metadata/payload.json`
   - `reports/cleaning_report.json`
4. Updates Firestore dataset doc with URIs, rows, columns, `status=ready`, and `ttlAt`.

## Run locally

```bash
pip install -r requirements.txt
export FILES_BUCKET=ai-data-analyser-files
export GCP_PROJECT=ai-data-analyser
uvicorn main:app --reload --port 8080
```

Health check:
```
curl http://localhost:8080/healthz
```

## Deploy (sketch)

From the repository root, you can deploy just this service via:

```
./backend/deploy-preprocess.ps1
```

The script enables required APIs (once), deploys Cloud Run `preprocess-svc`, and ensures the Eventarc trigger. After deployment, run `./backend/test.ps1` for a quick smoke test.

If you prefer a unified flow for all backend components, use `./backend/deploy.ps1`.

## Notes

- Excel policy: first sheet only; payload includes `excelInfo`.
- No column renames; instead flag potential dimensions in the payload.
- Deterministic sample of 50 rows for payload; truncate long strings.
- Parquet written with `pyarrow` and compression.

### Engine selection

- Default engine for CSV is Polars. Set via env var `PREPROCESS_ENGINE=polars|pandas` (default: `polars`).
- Excel files are handled by pandas (first sheet) regardless of engine.
- Core cleaning/payload logic is centralized in `pipeline_adapter.process_df_to_artifacts()` and shared by both adapters.

---

## Operational Runbook

### Verify Cloud Run health

1) Get service URL

```
gcloud run services describe preprocess-svc \
  --region=europe-west4 --format="value(status.url)"
```

2) Health check endpoint

```
curl -s "$(gcloud run services describe preprocess-svc \
  --region=europe-west4 --format='value(status.url)')/healthz"
```

### Verify Eventarc trigger

```
gcloud eventarc triggers describe preprocess-trigger \
  --location=europe-west4
```

Confirm:

- `eventFilters`: `type=google.cloud.storage.object.v1.finalized`, `bucket=ai-data-analyser-files`
- `destination`: run service `preprocess-svc`, path `/eventarc`, region `europe-west4`

### End-to-end smoke test

Prereqs: `functions/sign-upload-url` deployed and publicly reachable.

1) Request signed URL (replace values as needed)

```
SIGN_URL=$(gcloud functions describe sign-upload-url \
  --gen2 --region=europe-west4 --format='value(url)')

UID=demo-uid
SID=demo-sid
FILE=test_files/basic.csv
MIME=text/csv

FILENAME=$(basename "$FILE")
curl -s -H "X-User-Id: $UID" -H "X-Session-Id: $SID" \
  "$SIGN_URL?filename=$(python -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$FILENAME")&size=$(stat -c%s "$FILE")&type=$(python -c "import urllib.parse;print(urllib.parse.quote('$MIME'))")" \
  | tee /tmp/sign_resp.json

DATASET=$(jq -r .datasetId </tmp/sign_resp.json)
PUT_URL=$(jq -r .url </tmp/sign_resp.json)
```

2) Upload file to signed URL

```
curl -X PUT -H "Content-Type: $MIME" --data-binary @"$FILE" "$PUT_URL"
```

3) Wait and list artifacts

```
sleep 8
gcloud storage ls \
  "gs://ai-data-analyser-files/users/$UID/sessions/$SID/datasets/$DATASET/**"
```

4) Inspect Firestore doc (from Console or gcloud) at:

`users/{uid}/sessions/{sid}/datasets/{datasetId}`

### Troubleshooting

- Container failed to start (PORT): ensure the service is launched with a PORT-aware entrypoint.
  - We use `GOOGLE_ENTRYPOINT=python main.py` and `main.py` starts uvicorn honoring `$PORT`.
- Build fails compiling `pyarrow`: ensure Python 3.12 wheels are used.
  - `project.toml` sets `GOOGLE_PYTHON_VERSION=3.12` and `deploy.ps1` passes the same build env var.
