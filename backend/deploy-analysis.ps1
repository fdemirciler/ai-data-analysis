# =========
# Settings (Analysis Stage Only)
# =========
# Script-relative paths
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$SRC_FN_SIGN = Join-Path $SCRIPT_DIR "functions\sign_upload_url"
$SRC_FN_ORCH = Join-Path $SCRIPT_DIR "functions\orchestrator"

# Export orchestrator env from backend/config.yaml
$EXPORTER = Join-Path $SCRIPT_DIR "scripts\build_envs.py"
$ENV_FILE = Join-Path $SCRIPT_DIR "env.orchestrator.yaml"
$FLAGS_JSON = Join-Path $SCRIPT_DIR "deploy.orchestrator.flags.json"
$OVERLAY = "prod"  # for production deploys

py -3 $EXPORTER --service orchestrator --overlay $OVERLAY

if (!(Test-Path $FLAGS_JSON)) {
  Write-Error "Failed to generate $FLAGS_JSON. Ensure PyYAML is installed (py -3 -m pip install pyyaml)."; exit 1
}

$flags = Get-Content $FLAGS_JSON | ConvertFrom-Json
$PROJECT_ID = $flags.GCP_PROJECT
$REGION = $flags.GCP_REGION
$SERVICE_ACCOUNT = $flags.RUNTIME_SERVICE_ACCOUNT
$MEMORY = $flags.MEMORY
$CPU = $flags.CPU
$ALLOWED_ORIGINS = $flags.ALLOWED_ORIGINS
$BUCKET = $flags.FILES_BUCKET

# Configure gcloud
gcloud config set project $PROJECT_ID | Out-Null

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
# Service Account (resolve and fallback)
# ===========================
# Prefer RUNTIME_SERVICE_ACCOUNT from config.yaml if provided and exists; otherwise use default Compute Engine SA
$PROJECT_NUMBER = gcloud projects describe $PROJECT_ID --format="value(projectNumber)"
$DEFAULT_SA = "$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

function Test-ServiceAccountExists([string]$sa) {
  if (-not $sa -or $sa.Trim() -eq "") { return $false }
  $exists = gcloud iam service-accounts describe $sa --format="value(email)" 2>$null
  return -not [string]::IsNullOrEmpty(($exists | Out-String).Trim())
}

if (-not (Test-ServiceAccountExists $SERVICE_ACCOUNT)) {
  Write-Host "Using default Compute Engine SA: $DEFAULT_SA"
  $SERVICE_ACCOUNT = $DEFAULT_SA
} else {
  Write-Host "Using configured Service Account: $SERVICE_ACCOUNT"
}

# ==============================
# Compose ALLOWED_ORIGINS string
# ==============================
if (-not $ALLOWED_ORIGINS -or $ALLOWED_ORIGINS -eq "") {
  $ALLOWED_ORIGINS = "http://localhost:5173,https://ai-data-analyser.web.app,https://ai-data-analyser.firebaseapp.com"
}

# Build YAML env files for Gen2
$SIGN_ENV_FILE = Join-Path $SCRIPT_DIR "env.sign-upload-url.yaml"

# Sign-upload-url env (YAML)
@"
FILES_BUCKET: "$BUCKET"
GCP_PROJECT: "$PROJECT_ID"
TTL_DAYS: "1"
RUNTIME_SERVICE_ACCOUNT: "$SERVICE_ACCOUNT"
ALLOWED_ORIGINS: "$ALLOWED_ORIGINS"
"@ | Out-File -Encoding ascii -FilePath $SIGN_ENV_FILE

# Orchestrator env is generated at $ENV_FILE by the exporter

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
  --memory=$MEMORY `
  --cpu=$CPU `
  --env-vars-file="$ENV_FILE" `
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
