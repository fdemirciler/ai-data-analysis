PROJECT_ID=ai-data-analyser
gcloud config set project "$PROJECT_ID"

# Create a GitHub trigger (using GitHub App integration)
gcloud builds triggers create github \
  --name="backend-ci" \
  --repo-owner="ORG" \
  --repo-name="REPO" \
  --branch-pattern="^main$" \
  --build-config="backend/cloudbuild.yaml" \
  --included-files="backend/**" \
  --substitutions="_PROJECT_ID=ai-data-analyser,_REGION=europe-west4,_BUCKET=ai-data-analyser-files"