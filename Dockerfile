# --- build the UI ---
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- API + static UI ---
FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY data/seed data/seed
COPY data/samples data/samples
COPY --from=ui /ui/dist frontend/dist
# DATA_DIR holds the SQLite DB and uploaded PDFs; mount a persistent disk here.
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
WORKDIR /app/backend
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
