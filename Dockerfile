# Multi-stage build — keeps final image lean
FROM python:3.11-slim

RUN apt-get update && apt-get upgrade -y && apt-get clean

WORKDIR /app
 
# Copy installed packages from builder
COPY --from=builder /install /usr/local
 
# Copy source
COPY app/ ./app/
 
# Cloud Run sets PORT env var — default 8080
ENV PORT=8080
 
# Uvicorn: 1 worker per Cloud Run instance (Cloud Run scales by instance count)
# --no-access-log: Cloud Run captures logs via stdout anyway
CMD uvicorn app.main:app \
    --host 0.0.0.0 \
    --port ${PORT} \
    --workers 1 \
    --no-access-log