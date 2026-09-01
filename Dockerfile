# DOU Platform — production image
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY frontend-v2 ./frontend-v2
COPY static ./static
COPY tools ./tools
COPY alembic.ini .
COPY alembic ./alembic
COPY seed.py .

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)" || exit 1

CMD ["sh", "-c", "python tools/migrate.py || exit 1; if [ \"$SEED_DEMO_DATA\" = \"true\" ]; then python seed.py || exit 1; fi; exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4"]
