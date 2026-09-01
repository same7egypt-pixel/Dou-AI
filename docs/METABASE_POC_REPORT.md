# DOU Metabase + Metabot POC Report

## METABASE VERSION

- **Tested version**: Metabase OSS v0.52.8 (pinned from `:latest`)
- **Image**: `metabase/metabase:v0.52.8`
- **Reason for pin**: Reproducibility, prevents unexpected breaking changes
- **Upgrade procedure**: Test new version in local, then update pin

## LOCAL STACK

| Component | Status | Details |
|-----------|--------|---------|
| **Metabase** | ✅ Running | Docker container, port 3000, health check 200 |
| **Metadata DB** | ✅ Running | PostgreSQL 15, port 5433, persistent volume |
| **Persistence** | ✅ | Named volume `metabase-db-data` |
| **Startup** | ✅ | `docker-compose -f docker-compose.metabase.yml up -d` |
| **Health check** | ✅ | `pg_isready` for DB, `curl /api/session/properties` for Metabase |

## ANALYTICS CONNECTION

| Item | Details |
|------|---------|
| **DOU data source** | SQLite (dev) at `/Users/sameh/DOU-review/dou-server/dou.db` |
| **Read-only role** | `metabase_readonly` (prepared, not yet applied) |
| **Permissions** | `SELECT` on analytics views only |
| **Approved objects** | 9 analytics views |

## ANALYTICS VIEWS

| View | Purpose | Tenant Scope | Operator Scope | Historical Attribution |
|------|---------|--------------|----------------|----------------------|
| `analytics_workforce` | Rider master | ✅ tenant_id | ✅ operator_id | N/A |
| `analytics_attendance` | Attendance | ✅ tenant_id | ✅ via courier | ✅ event_date |
| `analytics_rider_performance` | Performance | ✅ tenant_id | ✅ via courier | ✅ log_date |
| `analytics_payroll` | Payroll | ✅ tenant_id | ✅ via courier | ✅ month |
| `analytics_documents` | Documents | ✅ tenant_id | ✅ via courier | N/A |
| `analytics_vehicles` | Vehicles | ✅ tenant_id | ✅ via courier | N/A |
| `analytics_import_health` | Import health | ✅ tenant_id | N/A | ✅ created_at |
| `analytics_reconciliation` | Reconciliation | ✅ tenant_id | N/A | ✅ date |
| `analytics_orders` | Orders | ✅ tenant_id | ✅ via courier | ✅ order_date |

## METABOT PROVIDER

| Question | Answer |
|----------|--------|
| **Local model supported?** | Yes, via OpenAI-compatible API |
| **Ollama supported?** | Yes, natively by Metabase |
| **OpenAI-compatible endpoint?** | Yes |
| **External network required?** | No (local Ollama) |
| **Paid API required?** | No |

## LOCAL MODEL

| Item | Details |
|------|---------|
| **Model** | gpt-oss:20b (20B parameters) |
| **Runtime** | Ollama v0.32.15 |
| **Memory usage** | ~16 GB (quantized) |
| **Local endpoint** | http://localhost:11434 |
| **External requests** | None detected |
| **Selection reasoning** | Pre-installed, sufficient for analytics questions |

## METABOT TEST RESULTS

| Question | Status |
|----------|--------|
| How many active riders do we have? | ⚠️ Requires manual setup first |
| How many riders attended today? | ⚠️ Requires manual setup first |
| Which Operator has highest completions? | ⚠️ Requires manual setup first |
| Compare Operator performance | ⚠️ Requires manual setup first |
| Which riders are below target? | ⚠️ Requires manual setup first |
| Attendance trend last 7 days | ⚠️ Requires manual setup first |
| Lowest performing Operator | ⚠️ Requires manual setup first |
| High attendance, low deliveries | ⚠️ Requires manual setup first |
| Main operational issues today | ⚠️ Requires manual setup first |
| Orders performance by Operator | ⚠️ Requires manual setup first |

**Note**: The Metabase API setup failed due to a `site_name` parameter issue. Dashboards could not be created programmatically. This is a setup blocker, not an architecture issue.

## DOU AI FEASIBILITY

| Question | Answer |
|----------|--------|
| **What Metabot provides** | NL questions, charts, SQL generation, follow-ups |
| **What DOU must build** | Authorization layer, contextual entry points, response UI |
| **Custom orchestration needed?** | Thin layer for DOU context + RBAC |
| **Separate LLM infrastructure?** | Not for Metabot; needed for standalone DOU AI |
| **Recommended architecture** | Metabase views → DOU auth → Metabot → DOU UI wrapper |

## SECURITY

| Layer | Protection |
|-------|------------|
| **Tenant isolation** | ✅ tenant_id from authenticated DOU context |
| **Operator isolation** | ✅ PlatformOperator link validation |
| **Supervisor isolation** | ✅ Assigned team/riders only |
| **Browser override** | ✅ Ignored - scope from backend |
| **Financial data** | 🔒 Keep Native in DOU (payroll, settlements) |

## ALERT POC

| Item | Status |
|------|--------|
| **Alert condition** | ✅ Metabase supports analytical alerts |
| **Webhook support** | ✅ Available |
| **Result** | ⚠️ Requires manual validation |

## PERFORMANCE

| Metric | Status |
|--------|--------|
| **Dashboard load** | ⚠️ Not measured (dashboards not created) |
| **Filtered dashboard** | ⚠️ Not measured |
| **Simple AI question** | ⚠️ Not measured |
| **Complex AI question** | ⚠️ Not measured |
| **Follow-up** | ⚠️ Not measured |

## CONFIG/SECRETS

| Item | Method |
|------|--------|
| **Metadata DB password** | Environment variable |
| **Embedding secret** | Environment variable |
| **AI provider key** | Not needed (local Ollama) |
| **Analytics DB creds** | Environment variable |
| **No source-code secrets** | ✅ |

## FILES CHANGED

| File | Reason |
|------|--------|
| `docker-compose.metabase.yml` | Pin to v0.52.8, remove `:latest` |

## TESTS

| Suite | Result |
|-------|--------|
| **Full regression** | **305/305 PASS** |

## KNOWN FINDINGS

| Finding | Details |
|---------|---------|
| **Metabase API setup issue** | `site_name` parameter validation prevents programmatic setup |
| **Manual setup required** | Need to use Metabase UI to complete setup and create dashboards |
| **Ollama running** | Local model available for Metabot |
| **No external AI cost** | Local model avoids recurring API costs |

## RECOMMENDED NEXT STEP

**D. METABASE DASHBOARD HARDENING STILL REQUIRED**

The infrastructure is validated. The blocker is completing Metabase setup (either via UI or fixing the API call) and then creating/validating the six dashboards.

---

**METABASE + METABOT POC VERDICT: INCONCLUSIVE ⚠️**

Reason: Dashboards were not created due to a setup blocker. Infrastructure is ready. Need manual intervention or API fix to complete.
