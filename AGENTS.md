# DOU Fleet OS

Multi-tenant SaaS that runs delivery fleets for logistics companies operating on
behalf of platforms like HungerStation and Ninja. Workforce, shifts and
attendance, documents and KYC, targets and incentives, payroll, reporting, and a
deterministic operational assistant.

## Running it

```bash
# Tests (the whole suite, ~60s)
DATABASE_URL=sqlite:///./test_run.db .venv/bin/python -m pytest tests/ -q

# Lint — must stay clean, CI gates on it
.venv/bin/python -m ruff check app/ --select E,F,I,W --ignore E501

# Local server
DATABASE_URL=sqlite:///./dou.db .venv/bin/python -m uvicorn app.main:app --port 8123 --reload
```

Deployment, backups, incidents: `docs/PRODUCTION_RUNBOOK.md`.

## Layout

```
app/
  main.py         router mounting and static/SPA routes
  config.py       env config; refuses weak SECRET_KEY/ADMIN_KEY in production
  models/         entities.py (core), intelligence.py (AI/notifications), salary.py
  routers/        ~41 routers; hr.py and fleet.py are the large ones
  services/       financial_calculations.py is the money engine
frontend-v2/      vanilla ES modules, no build step
  fleet/          8 screens + rider360; shared/ has the api client and i18n
alembic/versions/ schema migrations
```

## Rules that are not obvious from the code

**Payroll has exactly one calculation path.** `calculate_payroll_preview` (one
rider) delegates to `payroll_rows` (the sheet), which delegates to
`calculate_payroll_previews`. They previously diverged and showed different net
pay for the same rider on different screens. Do not add a second path — if a
caller needs different data, add a parameter.

**Preview is side-effect free.** It runs on GET endpoints. Only
`finalize_payroll_period` writes: snapshots, branch financials, and debt.

**A `FLAT_PER_ORDER` bonus plan replaces `per_delivery_rate`,** it does not stack
on it. The plan's rate is what the rider earns per order. Paying both pays the
same delivery twice. `Contract.client_rate_per_order` is a different thing
entirely: what the company bills the platform.

**Net pay is never negative.** If advances and deductions exceed earnings, the
rider is paid zero and the shortfall becomes a row in `courier_debts`, deducted
from later months oldest-first.

**A finalized month is read from its snapshot,** never recomputed. Changing a
rate today must not change what was already paid.

**A new model module must be imported in both `alembic/env.py` and
`app/db_maintenance.py`.** Missing from the first, autogenerate emits
`drop_table` for its live tables; missing from the second, a fresh install never
creates them. Both defects have happened. `tests/test_schema_integrity.py`
guards it.

**`alembic upgrade head` on an empty database does not work.** Revision `0001`
adopts a pre-existing schema instead of creating it. Use `tools/migrate.py`.

**Schema changes go in Alembic only.** No `ALTER TABLE` at import or startup —
`tests/test_startup_safety.py` fails if importing the app touches the database.

**The backend is the only authority on access.** Every scoped query filters on
`tenant_id`; supervisors narrow further by `supervisor_id`. Hiding something in
the frontend is not authorization. Cross-tenant leakage is a P0.

**DOU AI is deterministic.** Question to parser to an approved server-side report
to a structured answer. No LLM in the runtime path, no arbitrary SQL or question
ids from the browser.

## Tests worth knowing

- `test_payroll_golden.py` — exact amounts, each worked by hand in its docstring.
  If you change what a rider is paid, these fail, and that is the point.
- `test_payroll_tenant_isolation.py` — two companies, asserts zero leakage.
- `test_schema_integrity.py` — the model-registration guards above.

## Conventions

- Arabic is the primary UI language; the interface is RTL with English
  secondary. User-facing strings live in the views and `shared/i18n/i18n.py`.
- Money is rounded to 2 decimals at every boundary.
- Months are `YYYY-MM` strings, ordered lexically.

## AWS

- Prefer the AWS MCP Server for AWS interactions; it gives sandboxed execution
  and audit logging. Otherwise use the AWS CLI.
- Check for a relevant AWS skill before starting; prefer its guidance over
  general knowledge.
- Verify uncertain AWS specifics (API parameters, permissions, limits, error
  codes) against documentation rather than guessing, and say so when you cannot
  confirm.
- Prefer infrastructure-as-code (CDK or CloudFormation) over CLI mutations, and
  follow Well-Architected principles.
- Use hyphens, not em dashes, in AWS resource names and descriptions.

### Secret safety

Load the `aws-secrets-manager` skill first for any secret, credential, API key,
token, or password task. Do not call `secretsmanager get-secret-value` or
`batch-get-secret-value`, and do not hit the Secrets Manager Agent daemon
directly. Use `{{resolve:secretsmanager:secret-id:SecretString:json-key}}` with
`asm-exec` so the secret resolves at runtime without entering context.
