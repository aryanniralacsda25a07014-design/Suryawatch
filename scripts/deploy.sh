#!/usr/bin/env bash
# Deploy SuryaWatch: backend (SAM) + web app (Amplify Hosting).
# Run from the repo root inside AWS CloudShell (region us-east-1):   bash scripts/deploy.sh
set -euo pipefail

STACK=suryawatch
REGION=us-east-1
cd "$(dirname "$0")/.."

echo "==> 1/4 Running tests"
python3 -m unittest discover -s tests >/dev/null 2>&1 && echo "    tests passed" || {
  echo "    TESTS FAILED - fix before deploying:"; python3 -m unittest discover -s tests; exit 1; }

echo "==> 2/4 Deploying backend (API Gateway, Lambda, DynamoDB, S3, Amplify app)"
sam deploy --region "$REGION"

out() { aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
          --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
API_URL=$(out ApiUrl)
APP_ID=$(out WebAppId)
WEB_URL=$(out WebUrl)

echo "==> 3/4 Packaging web app for API $API_URL"
# Build in a temp copy so the repo stays clean (later "git pull" never conflicts)
rm -rf /tmp/suryawatch-web /tmp/suryawatch-web.zip
cp -r frontend /tmp/suryawatch-web
echo "window.SURYAWATCH_API = \"$API_URL\";" > /tmp/suryawatch-web/config.js
python3 - <<'PY'
import os, zipfile
src = "/tmp/suryawatch-web"
with zipfile.ZipFile("/tmp/suryawatch-web.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(src):
        for f in files:
            full = os.path.join(root, f)
            z.write(full, os.path.relpath(full, src))
PY

echo "==> 4/4 Publishing web app to Amplify Hosting"
read -r JOB_ID UPLOAD_URL < <(aws amplify create-deployment --app-id "$APP_ID" --branch-name main \
  --region "$REGION" --query "[jobId, zipUploadUrl]" --output text)
code=$(curl -s -o /tmp/upload.out -w "%{http_code}" -X PUT -H "Content-Type: application/zip" \
       --upload-file /tmp/suryawatch-web.zip "$UPLOAD_URL")
if [ "$code" != "200" ]; then
  code=$(curl -s -o /tmp/upload.out -w "%{http_code}" -X PUT --upload-file /tmp/suryawatch-web.zip "$UPLOAD_URL")
fi
[ "$code" = "200" ] || { echo "Upload failed (HTTP $code):"; cat /tmp/upload.out; exit 1; }
aws amplify start-deployment --app-id "$APP_ID" --branch-name main --job-id "$JOB_ID" --region "$REGION" >/dev/null

echo
echo "Done."
echo "  API:      $API_URL/health"
echo "  Web app:  $WEB_URL   (live in about a minute)"
