# DOU Platform — production image
#
# Pinned to bookworm rather than plain -slim on purpose. The floating tag moved
# to Debian trixie, whose postgresql-client is 17, and a pg_dump 17 archive is
# unreadable by the PostgreSQL 15 server this stack runs: backups verified fine
# and then failed to restore. bookworm ships client 15, matching the db image.
# If the db image is upgraded, move this tag in the same commit.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# postgresql-client supplies pg_dump and pg_restore, which scripts/backup.py
# shells out to. Without them the nightly backup fails inside the container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY frontend-v2 ./frontend-v2
COPY static ./static
COPY tools ./tools
COPY scripts ./scripts
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
