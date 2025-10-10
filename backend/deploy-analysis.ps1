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

# ==============================
# Compose ALLOWED_ORIGINS string
# ==============================
$ALLOWED_ORIGINS = "http://localhost:5173,https://ai-data-analyser.web.app,https://ai-data-analyser.firebaseapp.com"

# Build YAML env files for Gen2
$SIGN_ENV_FILE = Join-Path $SCRIPT_DIR "env.sign-upload-url.yaml"
$CHAT_ENV_FILE = Join-Path $SCRIPT_DIR "env.chat.yaml"

# Sign-upload-url env (YAML)
@"
FILES_BUCKET: "$BUCKET"
GCP_PROJECT: "$PROJECT_ID"
TTL_DAYS: "1"
RUNTIME_SERVICE_ACCOUNT: "$SERVICE_ACCOUNT"
ALLOWED_ORIGINS: "$ALLOWED_ORIGINS"
"@ | Out-File -Encoding ascii -FilePath $SIGN_ENV_FILE

# Chat env (YAML)
@"
FILES_BUCKET: "$BUCKET"
GCP_PROJECT: "$PROJECT_ID"
ORCH_IPC_MODE: "base64"
GEMINI_FUSED: "1"
RUNTIME_SERVICE_ACCOUNT: "$SERVICE_ACCOUNT"
ALLOWED_ORIGINS: "$ALLOWED_ORIGINS"
FASTPATH_ENABLED: "1"
FALLBACK_ENABLED: "1"
CODE_RECONSTRUCT_ENABLED: "1"
MIN_FASTPATH_CONFIDENCE: "0.55"
CLASSIFIER_TIMEOUT_SECONDS: "12"
MAX_FASTPATH_ROWS: "50000"
FORCE_FALLBACK_MIN_ROWS: "500000"
MAX_CHART_POINTS: "500"
TOOLKIT_VERSION: "2"
SSE_PING_INTERVAL_SECONDS: "22"
CHAT_HARD_TIMEOUT_SECONDS: "60"
CHAT_REPAIR_TIMEOUT_SECONDS: "30"
CODEGEN_TIMEOUT_SECONDS: "30"
MIRROR_COMMAND_TO_FIRESTORE: "0"
# Set to "1" on staging to emit SSE classification_result debug events
LOG_CLASSIFIER_RESPONSE: "1"
"@ | Out-File -Encoding ascii -FilePath $CHAT_ENV_FILE

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
# Auth flag (set ALLOW_UNAUTHENTICATED=1 in env for dev convenience)
$AUTH_FLAG = if ($env:ALLOW_UNAUTHENTICATED -eq "1") { "--allow-unauthenticated" } else { "" }

gcloud functions deploy sign-upload-url `
  --gen2 `
  --runtime=python312 `
  --region=$REGION `
  --source="$SRC_FN_SIGN" `
  --entry-point="sign_upload_url" `
  --trigger-http `
  $AUTH_FLAG `
  --service-account="$SERVICE_ACCOUNT" `
  --env-vars-file="$SIGN_ENV_FILE"

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
  $AUTH_FLAG `
  --service-account="$SERVICE_ACCOUNT" `
  --memory=512Mi `
  --env-vars-file="$CHAT_ENV_FILE" `
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
