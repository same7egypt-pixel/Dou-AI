# DOU Production Migration & Recovery Runbook

## Purpose

This runbook governs schema changes for `dou-server`. It does not authorize a production change. A production migration requires explicit owner approval, a verified backup/Neon branch, a reviewed revision, and a rehearsed rollback.

## Current migration architecture

- Web import and web startup do not mutate schema.
- `tools/migrate.py` is the only supported migration entrypoint.
- Docker runs `python tools/migrate.py` before Uvicorn.
- Alembic baseline: `20260829_0001`.
- An unversioned Phase 1 database is brought to the verified legacy schema once and stamped at the baseline.
- Once `alembic_version` exists, only `alembic upgrade head` runs.
- PostgreSQL uses an advisory lock so two instances cannot migrate concurrently.
- `/health` is liveness only; `/health/ready` verifies database connectivity and is the Render readiness path.

## Non-negotiable rules

1. Never run tests or `drop_all()` against a production `DATABASE_URL`.
2. Never run `alembic stamp` unless schema equivalence has been verified.
3. Never deploy a schema revision without a fresh recovery point.
4. Never combine destructive column removal with the application release that stops using the column.
5. Never store credentials, connection strings, or backup URLs in Git, logs, tickets, or this runbook.
6. Prefer expand → migrate data → switch reads/writes → contract across separate releases.

## Local/CI verification

Use an isolated database only:

```bash
export APP_ENV=test
export DATABASE_URL=sqlite:////tmp/dou-migration-check.db
export SECRET_KEY=test-only-secret-key
python tools/migrate.py
python tools/migrate.py
alembic current
alembic check
python -m pytest -q
python tools/check_html_js.py
```

Acceptance:

- The second migration run succeeds.
- `alembic current` equals repository head.
- `alembic check` reports no new upgrade operations.
- Tests and dashboard syntax checks pass.

## First Alembic adoption on an existing database

Do this first on a disposable Neon branch/staging copy, never first on production.

1. Record the current application commit and current schema inventory.
2. Create a Neon recovery branch or provider-supported snapshot.
3. Confirm the recovery branch can accept connections.
4. Run `python tools/migrate.py` against the disposable branch.
5. Verify `alembic_version = 20260829_0001`.
6. Compare table/column/index counts and run tenant-isolation smoke tests.
7. Run the application against that branch and verify `/health/ready`.
8. Only after owner approval, repeat with a fresh production recovery point.

The baseline downgrade is intentionally blocked. Recovery from a failed first adoption is restore/switch-back to the pre-migration Neon branch.

## Normal versioned release

### Before deployment

- Review the Alembic revision and downgrade.
- Prove upgrade on empty SQLite and a production-like PostgreSQL staging branch.
- Prove upgrade twice or verify the second run is a no-op.
- Prove application compatibility with both pre-change and post-change schemas when using expand/contract.
- Create and verify a fresh recovery branch/snapshot.
- Record expected duration and lock impact.

### Deployment

1. Pause manual schema changes.
2. Deploy one migration-capable release.
3. Docker executes `tools/migrate.py`; PostgreSQL advisory lock prevents concurrent execution.
4. Start Uvicorn only after migration succeeds.
5. Verify `/health/ready` returns `200` and `{ "database": "ok" }`.
6. Run authenticated smoke tests for login, tenant dashboard, rider list, attendance, payroll preview, and reports.
7. Monitor errors, latency, connection count, and database locks.

### Rollback decision

- **Application-only regression, schema backward-compatible:** roll back the application image.
- **Reversible schema regression:** stop traffic, run the reviewed `alembic downgrade <previous_revision>`, then roll back the application.
- **Irreversible/data migration regression:** do not improvise a downgrade. Switch/restore the verified pre-migration Neon recovery branch and redeploy the previous application commit.

## Revision standards

Every new revision must include:

- One clear purpose.
- Explicit `upgrade()` operations.
- A real `downgrade()` or a documented restore-only reason.
- Tenant-aware backfills.
- Idempotent data migration keys where applicable.
- Index creation designed to limit production locks.
- No credentials or environment-specific identifiers.
- Tests for upgrade, schema result, and critical data preservation.

## Destructive changes

Use at least three releases:

1. **Expand:** add nullable/new structures; old code continues working.
2. **Migrate:** backfill in bounded batches; dual-read/write if necessary.
3. **Contract:** after verification and retention window, remove old structures in a separately approved release.

## Incident checklist

- Stop further deploys.
- Preserve application and migration logs without secrets.
- Identify current Alembic revision.
- Determine whether writes occurred after migration.
- Choose application rollback, Alembic downgrade, or database restore based on the policy above.
- Verify tenant counts and critical payroll/attendance aggregates after recovery.
- Document root cause and add a regression test before retrying.
