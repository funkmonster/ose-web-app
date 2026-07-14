# ── Stage 1: build the frontend ──────────────────────────────────────────────
FROM node:20-alpine AS frontend
WORKDIR /app
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
# Build straight into a static dir we copy out
RUN npx vite build --outDir /static

# ── Stage 2: run the backend ─────────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY users.yaml /app/users.yaml
COPY --from=frontend /static /app/static

ENV USERS_FILE=/app/users.yaml \
    STATIC_DIR=/app/static \
    DB_PATH=/app/data/campaign.db

VOLUME /app/data
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
