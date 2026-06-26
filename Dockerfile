FROM python:3.11-slim AS build_stage

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.11-slim

WORKDIR /app

COPY --from=build_stage /install /usr/local

COPY app/ ./app/

ENV PORT=8080

CMD uvicorn app.main:app \
    --host 0.0.0.0 \
    --port ${PORT} \
    --workers 1 \
    --no-access-log
