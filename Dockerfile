FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV APP_PORT=8765 \
    SCAN_INTERVAL_MINUTES=60 \
    SCAN_ON_STARTUP=true \
    JOBS_JSON_PATH=/app/data/linkedin_jobs.json \
    STATE_JSON_PATH=/app/data/app_state.json \
    SCAN_CONFIG_PATH=/app/data/scan_config.json \
    LOGO_EXTERNAL_SEARCH_ENABLED=true

EXPOSE 8765

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT}"]
