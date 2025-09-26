# Config
$PROJECT_ID = "ai-data-analyser"
$REGION = "europe-west4"
$BUCKET = "ai-data-analyser-files"

$UID = "demo-uid"
$SID = "demo-sid"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$ROOT_DIR   = Split-Path -Parent $SCRIPT_DIR
$FILE = (Join-Path $ROOT_DIR "test_files\basic.csv")
$MIME = "text/csv"

# 1) Cloud Run health (service is public right now)
$PROJECT_NUMBER = (gcloud projects describe $PROJECT_ID --format "value(projectNumber)" | Out-String).Trim()

# Prefer URL reported by Cloud Run; fallback to canonical project-number URL
$RUN_URL_SVC = (gcloud run services describe preprocess-svc --region=$REGION --format "value(status.url)" | Out-String).Trim()
if ($RUN_URL_SVC -and ($RUN_URL_SVC -match '^https?://')) {
  $RUN_URL = $RUN_URL_SVC
} else {
  $RUN_URL = "https://preprocess-svc-$PROJECT_NUMBER.$REGION.run.app"
}
Write-Host "RUN_URL: $RUN_URL"

# Try health; if it fails, try alternate once, then continue without throwing
$healthOk = $false
try {
  $health = Invoke-RestMethod -Uri "$RUN_URL/healthz" -Method GET -TimeoutSec 10
  Write-Host "Health: $($health | ConvertTo-Json -Compress)"
  $healthOk = $true
} catch {
  Write-Host "Health check warning:" $_.Exception.Message
  # Pick alternate URL
  if ($RUN_URL -like "https://preprocess-svc-$PROJECT_NUMBER.$REGION.run.app") {
    $RUN_URL_ALT = $RUN_URL_SVC
  } else {
    $RUN_URL_ALT = "https://preprocess-svc-$PROJECT_NUMBER.$REGION.run.app"
  }
  if ($RUN_URL_ALT -and ($RUN_URL_ALT -match '^https?://') -and ($RUN_URL_ALT -ne $RUN_URL)) {
    Write-Host "Retrying health on alternate URL: $RUN_URL_ALT"
    try {
      $health2 = Invoke-RestMethod -Uri "$RUN_URL_ALT/healthz" -Method GET -TimeoutSec 10
      Write-Host "Health (alt): $($health2 | ConvertTo-Json -Compress)"
      $RUN_URL = $RUN_URL_ALT
      $healthOk = $true
    } catch {
      Write-Host "Health check warning (alt):" $_.Exception.Message
    }
  }
}
if (-not $healthOk) {
  Write-Host "Proceeding despite health probe warnings (likely local DNS/routing)."
}

# 2) Get signed URL (unchanged)
$SIGN_URL = (gcloud functions describe sign-upload-url --gen2 --region=$REGION --format "value(url)" | Out-String).Trim()
Write-Host "SIGN_URL: $SIGN_URL"
if (-not $SIGN_URL -or -not ($SIGN_URL -match '^https?://')) { throw "SIGN_URL invalid or empty" }

if (-not (Test-Path $FILE)) { throw "Test file not found at $FILE" }
$SIZE = (Get-Item $FILE).Length
$FILENAME = [System.IO.Path]::GetFileName($FILE)
$encName = [System.Uri]::EscapeDataString($FILENAME)
$encMime = [System.Uri]::EscapeDataString($MIME)
$reqUri = ("{0}?filename={1}&size={2}&type={3}" -f $SIGN_URL, $encName, $SIZE, $encMime)

$headers = @{
  "X-User-Id"    = $UID
  "X-Session-Id" = $SID
}
Write-Host "Signed URL request URI: $reqUri"
try {
  $resp = Invoke-RestMethod -Uri $reqUri -Headers $headers -Method GET
} catch {
  Write-Host "Signed URL request failed:" $_.Exception.Message
  throw
}

Write-Host "DatasetId: $($resp.datasetId)"
if (-not $resp.url) { throw "Signed URL missing in response" }

# 3) Upload
Invoke-WebRequest -Uri $resp.url -Method PUT -InFile $FILE -ContentType $MIME | Out-Null
Write-Host "Upload complete."

# 4) Wait and list artifacts
Start-Sleep -Seconds 30
gcloud storage ls "gs://$BUCKET/users/$UID/sessions/$SID/datasets/$($resp.datasetId)/**"

# 5) Fetch Firestore dataset status (best-effort)
try {
  $TOKEN = (gcloud auth print-access-token | Out-String).Trim()
  $docUrl = "https://firestore.googleapis.com/v1/projects/$PROJECT_ID/databases/(default)/documents/users/$UID/sessions/$SID/datasets/$($resp.datasetId)"
  $doc = Invoke-RestMethod -Uri $docUrl -Headers @{ Authorization = "Bearer $TOKEN" } -Method GET -TimeoutSec 10
  $status = $doc.fields.status.stringValue
  if ($status) {
    Write-Host "Firestore status: $status"
  } else {
    Write-Host "Firestore document retrieved (status field missing):"
    $doc | ConvertTo-Json -Depth 8
  }
} catch {
  Write-Host "Firestore read warning:" $_.Exception.Message
}

#test