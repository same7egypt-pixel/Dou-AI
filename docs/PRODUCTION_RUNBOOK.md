# DOU Fleet OS — Production Runbook

Operating instructions for the live stack. Read section 2 before your next
deploy: the release procedure changed.

---

## 1. Secrets

Every secret lives in `/opt/dou-fleet/.env`, mode `600`, owned by `ubuntu`. It is
git-ignored and must never be committed. `docker-compose.yml` has no fallback
values, so a missing variable stops the stack instead of silently starting with
a guessable default.

```bash
umask 077
cat > /opt/dou-fleet/.env <<EOF
APP_ENV=production
POSTGRES_DB=dou_prod
POSTGRES_USER=dou_user
POSTGRES_PASSWORD=$(openssl rand -hex 24)
SECRET_KEY=$(openssl rand -hex 32)
ADMIN_KEY=$(openssl rand -hex 16)
STORAGE_PROVIDER=S3
S3_BUCKET=dou-fleet-documents
AWS_REGION=me-central-1
BACKUP_S3_BUCKET=dou-fleet-backups
SENTRY_DSN=
EOF
chmod 600 /opt/dou-fleet/.env
```

**Rotating `SECRET_KEY` signs every session out.** Tokens are HS256 over that
key, so plan the rotation for a quiet hour and tell users they must log in
again. `POSTGRES_PASSWORD` must be changed inside PostgreSQL as well as in
`.env`:

```bash
docker compose exec db psql -U dou_user -d dou_prod \
  -c "ALTER USER dou_user WITH PASSWORD '<new password>';"
# then update .env and: docker compose up -d
```

---

## 2. Deploying a release

The app container no longer bind-mounts the source tree. It runs the code baked
into its image, so **copying files onto the server does not deploy them** —
`rsync` followed by `restart` will appear to succeed and change nothing.

```bash
# On the server
cd /opt/dou-fleet
git pull origin main
docker compose up -d --build
docker compose logs -f app        # watch migrations then uvicorn start
curl -fsS http://127.0.0.1:8000/health/ready
```

Migrations run automatically from `tools/migrate.py` before uvicorn starts,
under a PostgreSQL advisory lock so concurrent deploys cannot race. A failed
migration aborts the boot rather than serving against a half-changed schema.

**Rollback:**

```bash
git checkout <previous good sha>
docker compose up -d --build
```

A rollback does not undo a migration. If the bad release added a migration,
restore from backup (section 4) instead.

---

## 3. Health and monitoring

| Endpoint | Purpose | Healthy |
| --- | --- | --- |
| `GET /health` | liveness for the load balancer | `200` |
| `GET /health/ready` | readiness, touches the database | `200` |
| `GET /health/metrics` | uptime and system health | `200` |

Alert on `/health/ready` failing twice in a row, and on a sustained 5xx rate.
`SENTRY_DSN` in `.env` turns on error reporting.

```bash
docker compose ps                      # container state
docker compose logs --tail=200 app     # recent application log
docker compose exec db pg_isready -U dou_user -d dou_prod
```

---

## 4. Backups and recovery

Nightly backup, verified on write and uploaded to S3:

```bash
0 2 * * * cd /opt/dou-fleet && docker compose exec -T app python scripts/backup.py backup >> /var/log/dou-backup.log 2>&1
```

```bash
python scripts/backup.py backup            # dump, verify, upload, prune
python scripts/backup.py list              # local and remote copies
python scripts/backup.py restore <file>    # overwrite the live database
```

`backup` fails loudly rather than writing an unusable file: it rejects a dump
that is too small and runs `pg_restore --list` to confirm the archive is
readable and contains table data. Local copies are pruned after
`BACKUP_RETENTION_DAYS` (default 30); set a lifecycle policy on the bucket for
the remote ones.

**The dump format is tied to the PostgreSQL version.** `pg_dump` writes an
archive that only an equal or newer `pg_restore` can read. The app image is
pinned to `python:3.12-slim-bookworm` so its client is 15, matching the
`postgres:15-alpine` server. This is not cosmetic: the floating `-slim` tag had
moved to Debian trixie, whose client is 17, and those backups verified
successfully and then could not be restored at all. **If you upgrade the
database image, move the Python base image tag in the same commit.**

**Restore drill — run this quarterly, against a scratch database, and record the
date.** An unrehearsed restore is not a recovery plan.

```bash
# On the server, against a throwaway database. Production is untouched.
cd /opt/dou-fleet
PGUSER=$(grep '^POSTGRES_USER=' .env | cut -d= -f2-)
DUMP=$(cd backups && ls -t dou_postgres_*.dump | head -1)
CID=$(sudo docker compose ps -q db)

sudo docker compose exec -T db psql -U "$PGUSER" -d postgres -c "CREATE DATABASE dou_drill;"
sudo docker cp "backups/$DUMP" "$CID":/tmp/d.dump
sudo docker exec "$CID" pg_restore -U "$PGUSER" -d dou_drill --no-owner /tmp/d.dump
sudo docker exec "$CID" psql -U "$PGUSER" -d dou_drill -c "SELECT count(*) FROM couriers;"
sudo docker exec "$CID" psql -U "$PGUSER" -d postgres -c "DROP DATABASE dou_drill;"
```

Last drill: 2026-09-02, restored 110 tables / 3 tenants / 7 couriers / 9 users,
zero errors.

```bash
createdb -U dou_user dou_restore_test
DATABASE_URL=postgresql://dou_user:<pw>@localhost:5432/dou_restore_test \
  python scripts/backup.py restore backups/<latest>.dump
psql -U dou_user -d dou_restore_test -c "SELECT count(*) FROM couriers;"
dropdb -U dou_user dou_restore_test
```

---

## 5. Database

```bash
docker compose exec app alembic current           # applied revision
docker compose exec app alembic history --verbose
docker compose exec app alembic check             # models vs schema; must be clean
```

`alembic check` must report no drift. If it does not, the models and the
database disagree and the next autogenerated revision will be wrong.

Two rules the schema depends on:

- A new model module must be imported in **both** `alembic/env.py` and
  `app/db_maintenance.py`. Missing from the first, autogenerate emits
  `drop_table` for its live tables; missing from the second, a fresh install
  never creates them. `tests/test_schema_integrity.py` enforces this.
- `alembic upgrade head` on an empty database is **not** a supported path.
  Revision `0001` adopts a pre-existing schema rather than creating it. Only
  `tools/migrate.py` builds a correct database from nothing.

---

## 6. Security posture

- Multi-tenant isolation is enforced in the query layer; every scoped read
  filters on `tenant_id`. Frontend hiding is not authorization.
- Login throttling is 8 failures per 10 minutes per IP and phone, held in Redis
  so it is shared across the four uvicorn workers.
- Request rate limiting: 300 requests per minute per client IP.
- Request body cap: 15 MB.
- PostgreSQL and Redis bind to loopback only and are reachable solely over the
  compose network.
- Security headers (CSP, HSTS, `X-Frame-Options`, `nosniff`) are applied by
  middleware on every response.

---

## 7. Incidents

1. Check `docker compose ps` and `/health/ready`.
2. Read `docker compose logs --tail=200 app`.
3. If the boot loops on a migration, the schema is the problem — do not force
   the container up; read the migration error and decide between fixing forward
   and restoring from backup.
4. If the database is unreachable, confirm the `db` container is healthy and
   that `.env` matches the password PostgreSQL actually has.
5. To invalidate every session at once (suspected token compromise):

```bash
curl -X POST https://dou.delivery/auth/logout-all -H "X-Admin-Key: $ADMIN_KEY"
```
