# multi-stage：node build 前端 → python slim 跑 FastAPI（單一 Cloud Run 服務）
FROM node:22-slim AS fe
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
# vite.config 的 outDir 是 ../backend/static → 容器內為 /backend/static
# 改用環境變數覆寫輸出位置較脆弱，直接讓 build 寫到 /fe/../backend/static

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ backend/
COPY --from=fe /backend/static backend/static/
ENV PYTHONUNBUFFERED=1
CMD exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8080}
