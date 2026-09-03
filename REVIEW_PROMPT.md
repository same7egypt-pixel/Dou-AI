# Adversarial code review request — DOU Fleet OS, commits `16dfabb..377dfd0`

You are reviewing six commits that were written by another AI agent and **deployed
to production** on a live multi-tenant SaaS. Your job is to find what is wrong
with them. Assume the author was over-confident. I am not looking for
affirmation — a review that finds nothing is a failed review.

## The product

DOU Fleet OS: multi-tenant B2B SaaS that runs delivery fleets for logistics
companies and for delivery platforms (Ninja, HungerStation) in Saudi Arabia.
Workforce, shifts, attendance, documents/KYC, targets, **payroll**, reporting.

- FastAPI + SQLAlchemy 2.0 + Pydantic 2, Python 3.12
- PostgreSQL 15 in production, SQLite locally and in tests
- Vanilla ES modules frontend (`frontend-v2/`), no build step, Arabic-first RTL
- Multi-tenancy on `tenant_id`; entitlements via `Tenant.capabilities`
- Production: single EC2 `t3.micro` (909 MB RAM), Docker Compose, nginx

Read `CLAUDE.md` first. It states rules that are not visible in the code,
including: payroll has exactly one calculation path; preview is side-effect
free; a finalized month is read from its snapshot; **the backend is the only
authority on access and cross-tenant leakage is a P0**.

## What to review

```bash
git log --oneline 16dfabb..377dfd0
git diff 16dfabb..377dfd0
```

Six commits, in order:

1. `7bef621` — a platform account could not add a single rider; one tab id
   rendered two different products. Also removed fabricated data from the vendor
   screen and wired a form that previously faked success.
2. `1d4c9ef` — a rider could never be moved between vendors (every transfer
   answered 409). Per-vendor health rows, vendor portal toggle, capability
   re-gating, and a change to the global 404 handler.
3. `57f231d` — the ingestion pipeline's middle step did not exist. Adds
   `app/services/ingestion.py`, routes the Ninja live endpoint through it, gates
   all 17 `/sources` endpoints on a capability, adds an integration screen.
4. `3a60935` — reconciliation compared two different date axes and hardcoded
   `total_revenue_source=0`.
5. `c0533db` — a city filter matched on free text while a canonical `city_id`
   sat unread; filtering returned 1 of 3 riders in one city.
6. `377dfd0` — i18n: 65 Arabic strings were surviving with the UI set to English.

## Run it yourself

```bash
DATABASE_URL=sqlite:///./test_run.db .venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check app/ --select E,F,I,W --ignore E501
```

768 tests pass and lint is clean, so **do not report "the tests pass" as
evidence of anything**. Instead: find behaviour these tests do not cover, and
write a failing test that proves it. A review finding backed by a test I can run
is worth ten findings backed by prose.

## Places I am least confident — start here

These are real doubts, not a checklist. Attack them.

1. **`normalize_row` idempotency, `app/services/ingestion.py`.** The existence
   check matches `idempotency_key == key OR source_delivery_id == <id>` scoped
   only by `tenant_id` — deliberately, so that facts written before this change
   (which carry a legacy key format and a wrong `source_platform_id`) are not
   duplicated by a re-sent event. But `source_delivery_id` is **not** scoped by
   `source_platform_id` in that check. If one tenant receives the same delivery
   id from two different sources, the second is silently swallowed as a
   duplicate and the rider is never credited. How likely is that collision in
   practice, and is the transition safety worth it? Is there a formulation that
   gets both?

2. **`create_reconciliation`, `app/routers/sources.py`.** It loads **every**
   raw row for a source platform into Python (`.all()`), then filters by date in
   a Python loop, parsing each row's JSON twice. On a platform sending millions
   of rows this is an OOM on a 909 MB box. The date lives inside a JSON text
   column, which is why it was done this way — but is that a good enough reason?
   What is the right fix: a generated/indexed column, a stored `event_date` on
   the raw row, or something else? This shipped to production; how bad is it
   today and what is the trigger threshold?

3. **The 404 handler, `app/main.py`.** `_wants_html` no longer treats `*/*` as a
   page navigation, so API 404s return JSON with the endpoint's own message
   instead of an HTML error page. Blast radius is the entire application. Is
   there any legitimate client that sends `text/html` in `Accept` on an API
   call and now gets an HTML page it cannot parse? Any crawler, monitor, or
   mobile client this breaks? Does returning `exc.detail` on a 404 leak
   anything a generic "Not Found" was hiding?

4. **The `/sources` capability gate.** All 17 endpoints now require
   `PERFORMANCE_API_INGESTION`. `LOGISTICS_DEFAULTS` does not include it. Three
   test fixtures had to start granting it. **I did not verify against production
   data whether any live logistics tenant was relying on `/sources`.** Find
   whether anything in the codebase reaches `/sources` on behalf of an account
   that would not hold this capability.

5. **The Ninja live path, `app/routers/ninja_integration.py`.** It now records a
   `RawImportRow` and normalizes through the shared function. `is_new_fact` is
   computed as `fact is not None and before != "NORMALIZED"`, and the `DailyLog`
   order counter depends on it. Walk the retry and replay paths: can a rider's
   daily order count be incremented twice, or missed? What happens when the same
   `order_id` arrives with a *changed* payload?

6. **City filter, `app/routers/hr.py`.** The fallback is
   `city_id == resolved.id OR (city_id IS NULL AND text matches)`. A rider whose
   `city_id` points at a *different* city but whose `work_city` text matches the
   query is now excluded. Correct, or a silent behaviour change for someone?

## What I want back

For each finding:

- **the defect in one sentence**, then a concrete failure scenario: inputs and
  state in, wrong output or crash out;
- **the file and line**;
- **severity**, and say plainly if it is cosmetic — do not inflate;
- **a failing test** where you can write one.

Rank by severity. Put anything that is a **cross-tenant data leak, a wrong
payroll number, or money moving incorrectly** at the top regardless of how small
the code change is — those are the failure modes this product cannot survive.

Then answer three questions directly:

1. Is there any path by which one tenant can read or write another tenant's
   data, that these commits opened or failed to close?
2. Can any of this change what a rider is paid, for a month already finalized or
   for a month in progress?
3. If you had to roll one of these six commits back, which one, and why?

Finally: the commit messages claim each new test was verified by reintroducing
its defect and watching the test fail. **Spot-check that claim.** Pick three
tests, reintroduce the defect they describe, and tell me whether they actually
fail. If one does not, say so — the author already found five that did not fail
on the first attempt, and there may be more.

## Ground rules

- Read-only. Do not modify source, migrations, or infrastructure. Writing new
  test files in a scratch directory to demonstrate a finding is fine and
  encouraged.
- Do not run anything against production.
- If you disagree with a design decision but cannot show a failure it causes,
  say so and label it an opinion, separately from the defects.
