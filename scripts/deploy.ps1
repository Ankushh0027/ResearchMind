# ==============================================================================
# ResearchMind — Automated Production Deployment Script (PowerShell)
# ==============================================================================
param (
    [Parameter(Mandatory=$false, Position=0)]
    [string]$ProjectId = $env:GCP_PROJECT_ID,

    [Parameter(Mandatory=$false, Position=1)]
    [string]$Region = "us-central1",

    [Parameter(Mandatory=$false, Position=2)]
    [string]$Environment = "production"
)

$ErrorActionPreference = "Stop"

Write-Host "=== ResearchMind Production Deployment (PowerShell) ===" -ForegroundColor Cyan

if (-not $ProjectId) {
    Write-Error "Error: ProjectId (or GCP_PROJECT_ID environment variable) is required."
    exit 1
}

Write-Host "Target Project: $ProjectId" -ForegroundColor Green
Write-Host "Target Region:  $Region" -ForegroundColor Green
Write-Host "Environment:    $Environment" -ForegroundColor Green

# 1. Check Prerequisites
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Error "Error: gcloud CLI is not installed."
    exit 1
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Error: docker is not installed."
    exit 1
}

# 2. Set gcloud configuration
Write-Host "`n--> Configuring gcloud project..." -ForegroundColor Cyan
gcloud config set project $ProjectId --quiet

# 3. Authenticate Docker
Write-Host "`n--> Authenticating Docker with GCR..." -ForegroundColor Cyan
gcloud auth configure-docker --quiet

# 4. Build and Push Container Image
$timestamp = Get-Date -Format "yyyyMMddHHmmss"
$imageTag = "gcr.io/$ProjectId/researchmind:${Environment}-$timestamp"
$imageLatest = "gcr.io/$ProjectId/researchmind:latest"

Write-Host "`n--> Building container image: $imageLatest..." -ForegroundColor Cyan
docker build -t $imageTag -t $imageLatest -f Dockerfile .

Write-Host "`n--> Pushing container images to GCR..." -ForegroundColor Cyan
docker push $imageTag
docker push $imageLatest

# 5. Terraform Infrastructure
if ((Get-Command terraform -ErrorAction SilentlyContinue) -and (Test-Path "infrastructure/terraform")) {
    Write-Host "`n--> Planning Terraform Infrastructure..." -ForegroundColor Cyan
    Push-Location "infrastructure/terraform"
    try {
        terraform init
        terraform plan `
            -var="project_id=$ProjectId" `
            -var="region=$Region" `
            -var="environment=$Environment" `
            -var="api_image=$imageLatest" `
            -var="worker_image=$imageLatest" `
            -out=tfplan

        $confirmation = Read-Host "Apply Terraform plan? [y/N]"
        if ($confirmation -match "^[yY]([eE][sS])?$") {
            terraform apply tfplan
        } else {
            Write-Host "Terraform apply skipped by user." -ForegroundColor Yellow
        }
    } finally {
        Pop-Location
    }
}

Write-Host "`n=== ResearchMind Deployment Completed Successfully ===" -ForegroundColor Green
