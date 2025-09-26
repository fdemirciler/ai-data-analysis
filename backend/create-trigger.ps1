<#
Creates or updates a Cloud Build GitHub trigger for the unified backend pipeline
and grants required IAM roles to the Cloud Build service account.

Usage examples (PowerShell):
  # Minimal
  ./create-trigger.ps1 -ProjectId ai-data-analyser -RepoOwner fdemirciler -RepoName ai-data-analysis

  # Customizations
  ./create-trigger.ps1 -ProjectId ai-data-analyser -Region europe-west4 -Bucket ai-data-analyser-files `
    -RepoOwner fdemirciler -RepoName ai-data-analysis -BranchPattern "^main$" -TriggerName backend-ci

Notes:
- Requires that the Google Cloud Build GitHub App is installed on your GitHub org/repo.
- If the app is not installed, the trigger creation will fail with guidance to install it.
- This script is idempotent: it will update the trigger if it already exists.
#>
[CmdletBinding()] Param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [Parameter()][string]$Region = "europe-west4",
  [Parameter()][string]$Bucket = "ai-data-analyser-files",
  [Parameter(Mandatory=$true)][string]$RepoOwner,
  [Parameter(Mandatory=$true)][string]$RepoName,
  [Parameter()][string]$BranchPattern = "^main$",
  [Parameter()][string]$TriggerName = "backend-ci"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-Gcloud {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
  Write-Host "gcloud $($Args -join ' ')" -ForegroundColor Cyan
  & gcloud @Args
}

function Ensure-Project {
  param([string]$Project)
  Invoke-Gcloud -Args @('config','set','project', $Project) | Out-Null
}

function Ensure-APIs {
  # Safe to re-run
  $apis = @(
    'run.googleapis.com',
    'eventarc.googleapis.com',
    'cloudbuild.googleapis.com',
    'artifactregistry.googleapis.com',
    'cloudfunctions.googleapis.com',
    'firestore.googleapis.com',
    'storage.googleapis.com',
    'iamcredentials.googleapis.com',
    'pubsub.googleapis.com'
  )
  Invoke-Gcloud -Args (@('services','enable') + $apis) | Out-Null
}

function Get-ProjectNumber {
  param([string]$Project)
  (Invoke-Gcloud -Args @('projects','describe', $Project, '--format=value(projectNumber)') | Out-String).Trim()
}

function Ensure-ProjectRole {
  param([string]$Project,[string]$Member,[string]$Role)
  try {
    Invoke-Gcloud -Args @('projects','add-iam-policy-binding', $Project, '--member', $Member, '--role', $Role) | Out-Null
  } catch {
    if ($_.Exception.Message -notmatch 'already.*binding|ALREADY_EXISTS') { throw }
  }
}

function Ensure-SA-Role {
  param([string]$ServiceAccountEmail,[string]$Member,[string]$Role)
  try {
    Invoke-Gcloud -Args @('iam','service-accounts','add-iam-policy-binding', $ServiceAccountEmail, '--member', $Member, '--role', $Role) | Out-Null
  } catch {
    if ($_.Exception.Message -notmatch 'already.*binding|ALREADY_EXISTS') { throw }
  }
}

function Trigger-Exists {
  param([string]$Name)
  try {
    $res = Invoke-Gcloud -Args @('builds','triggers','describe', $Name)
    return $true
  } catch {
    return $false
  }
}

Write-Host "==> Configuring project" -ForegroundColor Green
Ensure-Project -Project $ProjectId

Write-Host "==> Enabling required APIs (idempotent)" -ForegroundColor Green
Ensure-APIs

Write-Host "==> Resolving service accounts" -ForegroundColor Green
$ProjectNumber = Get-ProjectNumber -Project $ProjectId
if (-not $ProjectNumber) { throw "Failed to resolve project number for $ProjectId" }
$CloudBuildSA = "$ProjectNumber@cloudbuild.gserviceaccount.com"
$RuntimeSA    = "$ProjectNumber-compute@developer.gserviceaccount.com"

Write-Host "==> Granting IAM roles to Cloud Build SA: $CloudBuildSA" -ForegroundColor Green
Ensure-ProjectRole -Project $ProjectId -Member "serviceAccount:$CloudBuildSA" -Role 'roles/run.admin'
Ensure-ProjectRole -Project $ProjectId -Member "serviceAccount:$CloudBuildSA" -Role 'roles/cloudfunctions.developer'
Ensure-ProjectRole -Project $ProjectId -Member "serviceAccount:$CloudBuildSA" -Role 'roles/eventarc.admin'
Ensure-ProjectRole -Project $ProjectId -Member "serviceAccount:$CloudBuildSA" -Role 'roles/pubsub.admin'
Ensure-ProjectRole -Project $ProjectId -Member "serviceAccount:$CloudBuildSA" -Role 'roles/storage.admin'

# Allow Cloud Build SA to act-as the runtime SA used by our services
Ensure-SA-Role -ServiceAccountEmail $RuntimeSA -Member "serviceAccount:$CloudBuildSA" -Role 'roles/iam.serviceAccountUser'

Write-Host "==> Creating or updating Cloud Build trigger '$TriggerName' for $RepoOwner/$RepoName" -ForegroundColor Green
$Subs = "_PROJECT_ID=$ProjectId,_REGION=$Region,_BUCKET=$Bucket"
if (Trigger-Exists -Name $TriggerName) {
  try {
    # Use beta update for richer flags; falls back to delete+create if necessary
    Invoke-Gcloud -Args @('beta','builds','triggers','update', $TriggerName,
      '--build-config=backend/cloudbuild.yaml',
      "--branch-pattern=$BranchPattern",
      "--included-files=backend/**",
      "--substitutions=$Subs")
  } catch {
    Write-Warning "Update failed; attempting delete + create. Error: $($_.Exception.Message)"
    Invoke-Gcloud -Args @('builds','triggers','delete', $TriggerName, '--quiet')
    Invoke-Gcloud -Args @('builds','triggers','create','github',
      "--name=$TriggerName",
      "--repo-owner=$RepoOwner",
      "--repo-name=$RepoName",
      "--branch-pattern=$BranchPattern",
      '--build-config=backend/cloudbuild.yaml',
      "--included-files=backend/**",
      "--substitutions=$Subs")
  }
} else {
  try {
    Invoke-Gcloud -Args @('builds','triggers','create','github',
      "--name=$TriggerName",
      "--repo-owner=$RepoOwner",
      "--repo-name=$RepoName",
      "--branch-pattern=$BranchPattern",
      '--build-config=backend/cloudbuild.yaml',
      "--included-files=backend/**",
      "--substitutions=$Subs")
  } catch {
    Write-Error "Trigger creation failed. If the error mentions the GitHub App, install the 'Google Cloud Build' GitHub App for $RepoOwner/$RepoName and grant repo access, then re-run. Error: $($_.Exception.Message)"
    throw
  }
}

Write-Host "==> Trigger details" -ForegroundColor Green
Invoke-Gcloud -Args @('builds','triggers','describe', $TriggerName) | Out-String | Write-Host

Write-Host "==> Done. Commits matching '$BranchPattern' that change files under 'backend/**' will run backend/cloudbuild.yaml." -ForegroundColor Green
