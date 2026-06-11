#!/usr/bin/env bash
# deploy.sh — 一鍵部署到 GCP（Cloud Run + GCS + Cloud Scheduler）
# 用法：
#   1. gcloud auth login && gcloud config set project <PROJECT_ID>
#   2. 填好 .env（PIN / APP_SECRET / REFRESH_SECRET / DISCORD_WEBHOOK_URL）
#   3. ./deploy.sh
set -euo pipefail

# 讀 .env（只取部署需要的鍵）
source .env

# 部署目標：.env 的 GCP_PROJECT 優先，未設則用 gcloud config 當前專案
PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
: "${PROJECT:?未指定 GCP 專案：在 .env 設 GCP_PROJECT，或先跑 gcloud config set project <ID>}"
REGION="${GCP_REGION:-asia-east1}"   # 台灣：避開 Binance 對美國 IP 的封鎖
SERVICE="crypto-agent"
BUCKET="${PROJECT}-crypto-cache"
gcloud config set project "${PROJECT}" --quiet
echo "▸ 部署目標：專案 ${PROJECT}，區域 ${REGION}"
: "${PIN:?請在 .env 設定 PIN}"
: "${APP_SECRET:?請在 .env 設定 APP_SECRET（隨機 32+ 字元）}"
: "${REFRESH_SECRET:?請在 .env 設定 REFRESH_SECRET（隨機字串）}"
DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:-}"

echo "▸ 啟用必要 API"
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com storage.googleapis.com --quiet

echo "▸ 建立 GCS bucket（已存在則略過）: gs://${BUCKET}"
gcloud storage buckets create "gs://${BUCKET}" --location="${REGION}" 2>/dev/null || true

echo "▸ 部署 Cloud Run: ${SERVICE} (${REGION})"
gcloud run deploy "${SERVICE}" \
  --source . \
  --region "${REGION}" \
  --allow-unauthenticated \
  --memory 512Mi --cpu 1 \
  --min-instances 0 --max-instances 1 \
  --timeout 300 \
  --set-env-vars "PIN=${PIN},APP_SECRET=${APP_SECRET},REFRESH_SECRET=${REFRESH_SECRET},GCS_BUCKET=${BUCKET},DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL},LOCAL_MODE=0,TOP_N=${TOP_N:-10}"

URL=$(gcloud run services describe "${SERVICE}" --region "${REGION}" --format 'value(status.url)')
echo "▸ 服務網址: ${URL}"

echo "▸ 授權 Cloud Run 服務帳戶讀寫 bucket"
SA=$(gcloud run services describe "${SERVICE}" --region "${REGION}" \
  --format 'value(spec.template.spec.serviceAccountName)')
SA=${SA:-"$(gcloud projects describe "$(gcloud config get-value project)" --format 'value(projectNumber)')-compute@developer.gserviceaccount.com"}
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${SA}" --role="roles/storage.objectAdmin" --quiet

echo "▸ 建立/更新 Cloud Scheduler（每 5 分鐘刷新）"
gcloud scheduler jobs delete crypto-refresh --location "${REGION}" --quiet 2>/dev/null || true
gcloud scheduler jobs create http crypto-refresh \
  --location "${REGION}" \
  --schedule "*/5 * * * *" \
  --uri "${URL}/tasks/refresh" \
  --http-method POST \
  --headers "X-Refresh-Secret=${REFRESH_SECRET}" \
  --attempt-deadline 300s

echo "▸ 觸發第一輪刷新"
curl -s -X POST "${URL}/tasks/refresh" -H "X-Refresh-Secret: ${REFRESH_SECRET}" | head -c 400
echo
echo "✅ 完成。手機開啟 ${URL} 並輸入 PIN。"
