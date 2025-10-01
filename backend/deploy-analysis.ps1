# =========
# Settings (Analysis Stage Only)
# =========
$PROJECT_ID = "ai-data-analyser"
$REGION = "europe-west4"
$BUCKET = "ai-data-analyser-files"

# Configure gcloud
gcloud config set project $PROJECT_ID | Out-Null

# Script-relative paths
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$SRC_FN_SIGN = Join-Path $SCRIPT_DIR "functions\sign_upload_url"
$SRC_FN_ORCH = Join-Path $SCRIPT_DIR "functions\orchestrator"

# =====================
# Enable required APIs
# =====================
gcloud services enable `
  cloudfunctions.googleapis.com `
  run.googleapis.com `
  artifactregistry.googleapis.com `
  storage.googleapis.com `
  firestore.googleapis.com `
  secretmanager.googleapis.com `
  iamcredentials.googleapis.com

# ===========================
# Project number and SA vars
# ===========================
$PROJECT_NUMBER = gcloud projects describe $PROJECT_ID --format="value(projectNumber)"
$SERVICE_ACCOUNT = "$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

# ======================================
# Secret Manager access for chat (Gemini)
# ======================================
gcloud secrets add-iam-policy-binding GEMINI_API_KEY `
  --member="serviceAccount:$SERVICE_ACCOUNT" `
  --role="roles/secretmanager.secretAccessor" `
  --project=$PROJECT_ID

# ============================================
# Deploy Functions Gen2: sign-upload-url (HTTP)
# ============================================
gcloud functions deploy sign-upload-url `
  --gen2 `
  --runtime=python312 `
  --region=$REGION `
  --source="$SRC_FN_SIGN" `
  --entry-point="sign_upload_url" `
  --trigger-http `
  --allow-unauthenticated `
  --service-account="$SERVICE_ACCOUNT" `
  --set-env-vars="FILES_BUCKET=$BUCKET,GCP_PROJECT=$PROJECT_ID,TTL_DAYS=1,RUNTIME_SERVICE_ACCOUNT=$SERVICE_ACCOUNT"

# ======================================
# Deploy Functions Gen2: chat (SSE HTTP)
# ======================================
gcloud functions deploy chat `
  --gen2 `
  --runtime=python312 `
  --region=$REGION `
  --source="$SRC_FN_ORCH" `
  --entry-point="chat" `
  --trigger-http `
  --allow-unauthenticated `
  --service-account="$SERVICE_ACCOUNT" `
  --memory=512Mi `
  --set-env-vars="FILES_BUCKET=$BUCKET,GCP_PROJECT=$PROJECT_ID,ORCH_IPC_MODE=base64,GEMINI_FUSED=1" `
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest"

# ====================
# Grab service URLs
# ====================
$SIGN_URL = gcloud functions describe sign-upload-url --gen2 --region=$REGION --format="value(url)"
$CHAT_URL = gcloud functions describe chat --gen2 --region=$REGION --format="value(url)"

# Trim URLs
$SIGN_URL = ($SIGN_URL | Out-String).Trim()
$CHAT_URL = ($CHAT_URL | Out-String).Trim()

Write-Host "sign-upload-url: $SIGN_URL"
Write-Host "chat (SSE):     $CHAT_URL"
