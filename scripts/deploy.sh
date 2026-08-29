#!/usr/bin/env bash
# ==============================================================================
# ResearchMind — Automated Production Deployment Script
# ==============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== ResearchMind Production Deployment ===${NC}"

# 1. Validate Environment
GCP_PROJECT_ID="${GCP_PROJECT_ID:-${1:-}}"
GCP_REGION="${GCP_REGION:-us-central1}"
ENVIRONMENT="${ENVIRONMENT:-production}"

if [ -z "$GCP_PROJECT_ID" ]; then
    echo -e "${RED}Error: GCP_PROJECT_ID is required.${NC}"
    echo "Usage: ./scripts/deploy.sh <GCP_PROJECT_ID> [GCP_REGION]"
    exit 1
fi

echo -e "Target Project: ${GREEN}${GCP_PROJECT_ID}${NC}"
echo -e "Target Region:  ${GREEN}${GCP_REGION}${NC}"
echo -e "Environment:    ${GREEN}${ENVIRONMENT}${NC}"

# 2. Check Prerequisites
command -v gcloud >/dev/null 2>&1 || { echo -e "${RED}Error: gcloud CLI is not installed.${NC}" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo -e "${RED}Error: docker is not installed.${NC}" >&2; exit 1; }

# 3. Configure gcloud
echo -e "\n${BLUE}--> Setting gcloud project configuration...${NC}"
gcloud config set project "$GCP_PROJECT_ID" --quiet

# 4. Authenticate Docker with GCP Artifact Registry / Container Registry
echo -e "\n${BLUE}--> Authenticating Docker with Google Container Registry...${NC}"
gcloud auth configure-docker --quiet

# 5. Build and Push Container Image
IMAGE_TAG="gcr.io/${GCP_PROJECT_ID}/researchmind:${ENVIRONMENT}-$(date +%Y%m%d%H%M%S)"
IMAGE_LATEST="gcr.io/${GCP_PROJECT_ID}/researchmind:latest"

echo -e "\n${BLUE}--> Building container image: ${IMAGE_LATEST}...${NC}"
docker build -t "$IMAGE_TAG" -t "$IMAGE_LATEST" -f Dockerfile .

echo -e "\n${BLUE}--> Pushing container images to GCR...${NC}"
docker push "$IMAGE_TAG"
docker push "$IMAGE_LATEST"

# 6. Apply Terraform Infrastructure (if available)
if command -v terraform >/dev/null 2>&1 && [ -d "infrastructure/terraform" ]; then
    echo -e "\n${BLUE}--> Planning Terraform Infrastructure...${NC}"
    cd infrastructure/terraform
    terraform init
    terraform plan \
        -var="project_id=${GCP_PROJECT_ID}" \
        -var="region=${GCP_REGION}" \
        -var="environment=${ENVIRONMENT}" \
        -var="api_image=${IMAGE_LATEST}" \
        -var="worker_image=${IMAGE_LATEST}" \
        -out=tfplan

    read -r -p "Apply Terraform plan? [y/N] " response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        terraform apply tfplan
    else
        echo -e "${YELLOW}Terraform apply skipped by user.${NC}"
    fi
    cd ../..
fi

echo -e "\n${GREEN}=== ResearchMind Deployment Completed Successfully ===${NC}"
