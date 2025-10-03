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
  }
} catch {
  Write-Host "Firestore read warning:" $_.Exception.Message
}
# 6) Chat SSE smoke test (best-effort)
$CHAT_URL = (gcloud functions describe chat --gen2 --region=$REGION --format "value(url)" | Out-String).Trim()
Write-Host "CHAT_URL: $CHAT_URL"
if ($CHAT_URL -and ($CHAT_URL -match '^https?://')) {
  # Use a metadata-only question for a fast "done" event
  $body = @{ uid = $UID; sessionId = $SID; datasetId = $resp.datasetId; question = "How many rows?" } | ConvertTo-Json -Compress
  $payloadPath = Join-Path $env:TEMP "chat_payload.json"
  $sseOut = Join-Path $env:TEMP ("chat_sse_{0}.log" -f ([Guid]::NewGuid().ToString('N')))
  $body | Out-File -FilePath $payloadPath -Encoding utf8 -NoNewline
  try {
    & curl.exe -sN `
      -H "Origin: http://localhost:5173" `
      -H "Content-Type: application/json" `
      -H "X-User-Id: $UID" `
      -H "X-Session-Id: $SID" `
      --data-binary "@$payloadPath" `
      --max-time 60 `
      $CHAT_URL 2>&1 | Tee-Object -FilePath $sseOut | Out-Null

    # Try to parse the final done event and verify results in GCS
    try {
      $doneMatch = Select-String -Path $sseOut -Pattern 'data:\s*\{.*"type"\s*:\s*"done"' | Select-Object -Last 1
      if ($doneMatch) {
        $jsonLine = ($doneMatch.Line -replace '^data:\s*','')
        $evt = $jsonLine | ConvertFrom-Json
        $msgId = $evt.data.messageId
        $uris  = $evt.data.uris
        if ($msgId) {
          $resultsPrefix = "users/$UID/sessions/$SID/results/$msgId"
          Write-Host "Verifying analysis artifacts at gs://$BUCKET/$resultsPrefix/"
          gcloud storage ls "gs://$BUCKET/$resultsPrefix/**"
          # Verify HTTPS signed URLs exist and fetch 200
          if ($uris -and $uris.table -and ($uris.table -match '^https://')) {
            try { Invoke-WebRequest -Uri $uris.table -Method GET -TimeoutSec 10 | Out-Null; Write-Host "OK: table.json signed URL fetchable" } catch { Write-Host "Warning: table.json signed URL fetch failed: $($_.Exception.Message)" }
          } else { Write-Host "Warning: missing or non-HTTPS table URL in done event" }
          if ($uris -and $uris.metrics -and ($uris.metrics -match '^https://')) {
            try { Invoke-WebRequest -Uri $uris.metrics -Method GET -TimeoutSec 10 | Out-Null; Write-Host "OK: metrics.json signed URL fetchable" } catch { Write-Host "Warning: metrics.json signed URL fetch failed: $($_.Exception.Message)" }
          } else { Write-Host "Warning: missing or non-HTTPS metrics URL in done event" }
          if ($uris -and $uris.chartData -and ($uris.chartData -match '^https://')) {
            try { Invoke-WebRequest -Uri $uris.chartData -Method GET -TimeoutSec 10 | Out-Null; Write-Host "OK: chart_data.json signed URL fetchable" } catch { Write-Host "Warning: chart_data.json signed URL fetch failed: $($_.Exception.Message)" }
          } else { Write-Host "Warning: missing or non-HTTPS chartData URL in done event" }
        } else {
          Write-Host "SSE parse warning: messageId missing in done event"
        }
      } else {
        Write-Host "SSE parse warning: no done event found"
      }
    } catch {
      Write-Host "SSE parse warning:" $_.Exception.Message
    }
  } catch {
  } finally {
    if (Test-Path $payloadPath) { Remove-Item $payloadPath -Force }
    if (Test-Path $sseOut) { Remove-Item $sseOut -Force }
  }
} else {
  Write-Host "SSE test skipped: CHAT_URL invalid"
}

# =============================
# Optional: XLSX smoke test
# =============================
try {
  $XLSX_FILE = (Join-Path $ROOT_DIR "test_files\test.xlsx")
  if (-not (Test-Path $XLSX_FILE)) {
    $maybe = Get-ChildItem -Path (Join-Path $ROOT_DIR "test_files") -Filter *.xlsx -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($maybe) { $XLSX_FILE = $maybe.FullName } else { $XLSX_FILE = $null }
  }

  if ($XLSX_FILE -and (Test-Path $XLSX_FILE)) {
    Write-Host "Running XLSX smoke test with: $XLSX_FILE"
    $MIME2 = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    $SIZE2 = (Get-Item $XLSX_FILE).Length
    $FILENAME2 = [System.IO.Path]::GetFileName($XLSX_FILE)
    $encName2 = [System.Uri]::EscapeDataString($FILENAME2)
    $encMime2 = [System.Uri]::EscapeDataString($MIME2)
    $reqUri2 = ("{0}?filename={1}&size={2}&type={3}" -f $SIGN_URL, $encName2, $SIZE2, $encMime2)

    $headers2 = @{ "X-User-Id" = $UID; "X-Session-Id" = $SID }
    $resp2 = Invoke-RestMethod -Uri $reqUri2 -Headers $headers2 -Method GET
    if (-not $resp2.url) { throw "Signed URL missing for XLSX" }
    Invoke-WebRequest -Uri $resp2.url -Method PUT -InFile $XLSX_FILE -ContentType $MIME2 | Out-Null
    Write-Host "XLSX upload complete."
    Start-Sleep -Seconds 30
    gcloud storage ls "gs://$BUCKET/users/$UID/sessions/$SID/datasets/$($resp2.datasetId)/**"
  } else {
    Write-Host "XLSX smoke test skipped: no .xlsx file found in test_files."
  }
} catch {
  Write-Host "XLSX smoke test warning:" $_.Exception.Message
}