# =========
# Settings
# =========
$PROJECT_ID = "ai-data-analyser"
$REGION = "europe-west4"
$BUCKET = "ai-data-analyser-files"

gcloud config set project $PROJECT_ID | Out-Null

# =====================
# Enable required APIs
# =====================
gcloud services enable `
  run.googleapis.com `
  eventarc.googleapis.com `
  cloudbuild.googleapis.com `
  artifactregistry.googleapis.com `
  cloudfunctions.googleapis.com `
  firestore.googleapis.com `
  storage.googleapis.com `
  secretmanager.googleapis.com `
  pubsub.googleapis.com

# ===========================
# Project number and SA vars
# ===========================
$PROJECT_NUMBER = gcloud projects describe $PROJECT_ID --format="value(projectNumber)"
$SERVICE_ACCOUNT = "$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
# ======================================================
# Deploy Cloud Run: preprocess-svc (from run-preprocess/)
# - Uses buildpacks; run app via `python main.py` (uvicorn started in __main__)
# ======================================================
gcloud run deploy preprocess-svc `
  --region=$REGION `
  --source="run-preprocess" `
  --service-account="$SERVICE_ACCOUNT" `
  --set-build-env-vars="GOOGLE_PYTHON_VERSION=3.12" `
  --set-env-vars="FILES_BUCKET=$BUCKET,GCP_PROJECT=$PROJECT_ID,TTL_DAYS=1" `
  --no-allow-unauthenticated

# ==================================================
# IAM: allow the runtime SA to access Firestore/GCS
# ==================================================
# Firestore (read/write)
gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$SERVICE_ACCOUNT" `
  --role="roles/datastore.user"

# Storage (read raw + write artifacts) - scoped to the bucket
gcloud storage buckets add-iam-policy-binding gs://$BUCKET `
  --member="serviceAccount:$SERVICE_ACCOUNT" `
  --role="roles/storage.objectAdmin"

# =======================================================
# Eventarc: permissions + trigger for GCS Object Finalize
# =======================================================
# Allow SA to receive events and invoke the service
gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$SERVICE_ACCOUNT" `
  --role="roles/eventarc.eventReceiver"

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

# ============================================
# Deploy Functions Gen2: sign-upload-url (HTTP)
# ============================================
gcloud functions deploy sign-upload-url `
  --gen2 `
  --runtime=python312 `
  --region=$REGION `
  --source="functions/sign_upload_url" `
  --entry-point="sign_upload_url" `
  --trigger-http `
  --allow-unauthenticated `
  --service-account="$SERVICE_ACCOUNT" `
  --set-env-vars="FILES_BUCKET=$BUCKET,GCP_PROJECT=$PROJECT_ID,TTL_DAYS=1"

# ======================================
# Deploy Functions Gen2: chat (SSE HTTP)
# ======================================
gcloud functions deploy chat `
  --gen2 `
  --runtime=python312 `
  --region=$REGION `
  --source="functions/orchestrator" `
  --entry-point="chat" `
  --trigger-http `
  --allow-unauthenticated `
  --service-account="$SERVICE_ACCOUNT"

# ====================
# Grab service URLs
# ====================
$SIGN_URL = gcloud functions describe sign-upload-url --gen2 --region=$REGION --format="value(url)"
$CHAT_URL = gcloud functions describe chat --gen2 --region=$REGION --format="value(url)"
$RUN_URL  = gcloud run services describe preprocess-svc --region=$REGION --format="value(status.url)"

# Trim URLs to avoid stray whitespace/newlines
$SIGN_URL = ($SIGN_URL | Out-String).Trim()
$CHAT_URL = ($CHAT_URL | Out-String).Trim()
$RUN_URL  = ($RUN_URL  | Out-String).Trim()

Write-Host "sign-upload-url: $SIGN_URL"
Write-Host "chat (SSE):     $CHAT_URL"
Write-Host "preprocess-svc: $RUN_URL"

# ======================
# Quick health check
# ======================
if ($RUN_URL) {
  try {
    Invoke-RestMethod -Uri "$RUN_URL/healthz" -Method GET
  } catch {
    Write-Host "Health check failed:" $_.Exception.Message
  }
} else {
  Write-Host "Health check skipped: Cloud Run URL empty"
}

# ======================
# Smoke test (optional)
# ======================
# Update these paths if needed
$FILE = "test_files\basic.csv"
$MIME = "text/csv"
$UID = "demo-uid"
$SID = "demo-sid"

if (Test-Path $FILE) {
  $SIZE = (Get-Item $FILE).Length
  $FILENAME = [System.IO.Path]::GetFileName($FILE)
  $headers = @{
    "X-User-Id"    = $UID
    "X-Session-Id" = $SID
  }

  if (-not $SIGN_URL -or -not ($SIGN_URL -match '^https?://')) {
    Write-Host "Smoke test skipped: SIGN_URL unavailable or invalid"
  } else {
    # 1) Get signed URL + datasetId
    $encName = [System.Uri]::EscapeDataString($FILENAME)
    $encMime = [System.Uri]::EscapeDataString($MIME)
    $reqUri = "$SIGN_URL?filename=$encName&size=$SIZE&type=$encMime"
    Write-Host "Signed URL request URI: $reqUri"
    try {
      $resp = Invoke-RestMethod -Uri $reqUri -Headers $headers -Method GET
    } catch {
      Write-Host "Signed URL request failed:" $_.Exception.Message
      $resp = $null
    }
    if ($resp) { Write-Host "DatasetId: $($resp.datasetId)" } else { Write-Host "DatasetId: (unavailable)" }

    # 2) Upload the file with PUT to the signed URL
    if ($resp.url) {
      Invoke-WebRequest -Uri $resp.url -Method PUT -InFile $FILE -ContentType $MIME | Out-Null
      Write-Host "Upload complete."
    } else {
      Write-Host "Upload skipped: signed URL missing in response"
    }

    # 3) Wait a few seconds for Eventarc -> preprocess-svc
    Start-Sleep -Seconds 8

    # 4) List artifacts
    if ($resp.datasetId) {
      gcloud storage ls "gs://$BUCKET/users/$UID/sessions/$SID/datasets/$($resp.datasetId)/**"
    }
  }
} else {
  Write-Host "Smoke test skipped: file not found at $FILE"
}