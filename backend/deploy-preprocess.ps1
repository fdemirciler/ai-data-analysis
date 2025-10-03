# =========
# Settings (Preprocess Stage Only)
# =========
$PROJECT_ID = "ai-data-analyser"
$REGION = "europe-west4"
$BUCKET = "ai-data-analyser-files"

gcloud config set project $PROJECT_ID | Out-Null

# Script-relative paths
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$ROOT_DIR   = Split-Path -Parent $SCRIPT_DIR
$SRC_RUN     = Join-Path $SCRIPT_DIR "run-preprocess"

# =====================
# Enable required APIs
# =====================
gcloud services enable `
  run.googleapis.com `
  eventarc.googleapis.com `
  cloudbuild.googleapis.com `
  artifactregistry.googleapis.com `
  firestore.googleapis.com `
  storage.googleapis.com `
  pubsub.googleapis.com

# ===========================
# Project number and SA vars
# ===========================
$PROJECT_NUMBER = gcloud projects describe $PROJECT_ID --format="value(projectNumber)"
$SERVICE_ACCOUNT = "$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

# ======================================================
# Deploy Cloud Run: preprocess-svc (from run-preprocess/)
# ======================================================
gcloud run deploy preprocess-svc `
  --region=$REGION `
  --source="$SRC_RUN" `
  --service-account="$SERVICE_ACCOUNT" `
  --set-build-env-vars="GOOGLE_PYTHON_VERSION=3.12" `
  --cpu=2 `
  --memory=2Gi `
  --concurrency=10 `
  --set-env-vars="FILES_BUCKET=$BUCKET,GCP_PROJECT=$PROJECT_ID,TTL_DAYS=1,PREPROCESS_ENGINE=polars" `
  --no-allow-unauthenticated

# ==================================================
# IAM: baseline access for preprocess + artifacts
# ==================================================
# Firestore (read/write)
gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$SERVICE_ACCOUNT" `
  --role="roles/datastore.user"

# Storage (read raw + write artifacts) - scoped to the bucket
gcloud storage buckets add-iam-policy-binding gs://$BUCKET `
  --member="serviceAccount:$SERVICE_ACCOUNT" `
  --role="roles/storage.objectAdmin"

# =============================
# GCS lifecycle: users/ → 1 day
# =============================
$lifecycleFile = Join-Path $env:TEMP "gcs_lifecycle_users.json"
@'
{
  "rule": [
    {
      "action": {"type": "Delete"},
      "condition": {"age": 1, "matchesPrefix": ["users/"]}
    }
  ]
}
'@ | Out-File -FilePath $lifecycleFile -Encoding ascii -NoNewline
try {
  gsutil lifecycle set $lifecycleFile gs://$BUCKET
  Write-Host "Applied GCS lifecycle rule: delete users/ after 1 day."
} catch {
  Write-Host "Warning: failed to set lifecycle:" $_.Exception.Message
} finally {
  if (Test-Path $lifecycleFile) { Remove-Item $lifecycleFile -Force }
}

# ==================================================
# Eventarc: permissions + trigger for GCS Object Finalize
# ==================================================
# Allow SA to receive events and invoke the service
gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$SERVICE_ACCOUNT" `
  --role="roles/eventarc.eventReceiver"

# Grant Pub/Sub Publisher to the Cloud Storage service account so GCS can
# publish CloudEvents to Pub/Sub in this project (required by Eventarc).
$GCS_SA = "service-$PROJECT_NUMBER@gs-project-accounts.iam.gserviceaccount.com"
gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$GCS_SA" `
  --role="roles/pubsub.publisher"

# Verify service exists before binding/creating trigger
$RUN_URL_CHECK = gcloud run services describe preprocess-svc --region=$REGION --format="value(status.url)"
if ($RUN_URL_CHECK) {
  gcloud run services add-iam-policy-binding preprocess-svc `
    --region=$REGION `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/run.invoker"

  # Ensure trigger (GCS -> Cloud Run) exists; update if present
  $TRIGGER_NAME = "preprocess-trigger"
  $TRIGGER_EXISTS = gcloud eventarc triggers describe $TRIGGER_NAME --location=$REGION --format="value(name)" 2>$null
  if ($TRIGGER_EXISTS) {
    gcloud eventarc triggers update $TRIGGER_NAME `
      --location=$REGION `
      --event-filters="type=google.cloud.storage.object.v1.finalized" `
      --event-filters="bucket=$BUCKET" `
      --destination-run-service="preprocess-svc" `
      --destination-run-path="/eventarc" `
      --destination-run-region=$REGION `
      --service-account="$SERVICE_ACCOUNT"
  } else {
    gcloud eventarc triggers create $TRIGGER_NAME `
      --location=$REGION `
      --event-filters="type=google.cloud.storage.object.v1.finalized" `
      --event-filters="bucket=$BUCKET" `
      --destination-run-service="preprocess-svc" `
      --destination-run-path="/eventarc" `
      --destination-run-region=$REGION `
      --service-account="$SERVICE_ACCOUNT"
  }

  # Verify trigger
  gcloud eventarc triggers describe $TRIGGER_NAME --location=$REGION
} else {
  Write-Host "Cloud Run service preprocess-svc not found; skipping Eventarc IAM/trigger setup."
}

# ====================
# Output service URL
# ====================
$RUN_URL  = gcloud run services describe preprocess-svc --region=$REGION --format="value(status.url)"
$RUN_URL  = ($RUN_URL  | Out-String).Trim()
Write-Host "preprocess-svc: $RUN_URL"
