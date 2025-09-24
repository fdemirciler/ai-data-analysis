# Ops Checklist (GCS, Eventarc, Firestore TTL)

Project: `ai-data-analyser`  •  Region: `europe-west4`  •  Bucket: `ai-data-analyser-files`

## 1) GCS CORS for signed URL uploads

Create `cors.json` locally:
```json
[
  {
    "origin": ["http://localhost:3000"],
    "method": ["PUT", "GET", "HEAD"],
    "responseHeader": ["Content-Type", "Authorization", "x-goog-meta-*"],
    "maxAgeSeconds": 3600
  }
]
```

Apply CORS:
```bash
gsutil cors set cors.json gs://ai-data-analyser-files
gsutil cors get gs://ai-data-analyser-files
```

## 2) GCS lifecycle: prefix-scoped 1-day TTL

Create `lifecycle.json`:
```json
{
  "rule": [
    {
      "action": {"type": "Delete"},
      "condition": {"age": 1, "matchesPrefix": ["users/"]}
    }
  ]
}
```

Apply lifecycle:
```bash
gsutil lifecycle set lifecycle.json gs://ai-data-analyser-files
gsutil lifecycle get gs://ai-data-analyser-files
```

## 3) Eventarc trigger → Cloud Run preprocess

Example (adjust service account as needed):
```bash
gcloud eventarc triggers create preprocess-trigger \
  --location=europe-west4 \
  --event-filters="type=google.cloud.storage.object.v1.finalized" \
  --event-filters="bucket=ai-data-analyser-files" \
  --destination-run-service=preprocess-svc \
  --destination-run-region=europe-west4 \
  --service-account=preprocess-svc@ai-data-analyser.iam.gserviceaccount.com
```

Verify trigger:
```bash
gcloud eventarc triggers describe preprocess-trigger --location=europe-west4
```

## 4) Firestore TTL (1 day)

Enable TTL on the following collection groups via Console (recommended) or API:
- `users/*/sessions/*`  → field: `ttlAt`
- `users/*/sessions/*/datasets/*`  → field: `ttlAt`
- `users/*/sessions/*/messages/*`  → field: `ttlAt`

Write policy:
- On session creation, set `ttlAt = createdAt + 1 day`.
- On session close, set `ttlAt = now` before deletion (belt-and-suspenders).

## 5) Secret Manager: Gemini API key

Create or update:
```bash
gcloud secrets versions add GEMINI_API_KEY --data-file=gemini_key.txt \
  --project=ai-data-analyser
```

Grant access to service accounts (orchestrator, executors):
```bash
gcloud secrets add-iam-policy-binding GEMINI_API_KEY \
  --member=serviceAccount:orchestrator-func@ai-data-analyser.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor \
  --project=ai-data-analyser
```

## 6) Budget alerts and Monitoring (high level)

- Set a budget in Cloud Billing with alerts at 70% and 90%.
- Create dashboards for:
  - Error rates by stage (preprocess, classify, validate, run)
  - p95 latencies
  - Complex-path ratio and failover counts

## 7) Scheduler → usage-watcher Function

Create scheduler job (every 10 minutes):
```bash
gcloud scheduler jobs create http usage-watcher \
  --schedule="*/10 * * * *" \
  --uri="https://<cloudfunctions-url>/usage-watcher" \
  --http-method=POST \
  --oauth-service-account-email=usage-watcher-func@ai-data-analyser.iam.gserviceaccount.com \
  --location=europe-west4
```
