# DOU W10: Metabase OSS Local Setup

## Prerequisites
- Docker Desktop installed and running
- Docker Compose v2+

## Quick Start

```bash
cd /Users/sameh/DOU-review/dou-server

# Start Metabase OSS + PostgreSQL metadata DB
docker-compose -f docker-compose.metabase.yml up -d

# Check status
docker-compose -f docker-compose.metabase.yml ps

# View logs
docker-compose -f docker-compose.metabase.yml logs -f metabase
```

## Access
- Metabase UI: http://localhost:3000
- First-time setup creates the admin account

## Architecture

```
DOU Application (FastAPI)
    │
    ├── Native Reports (/analytics/reports/*)
    │
    └── Embedded Analytics
            │
            ▼
    Metabase OSS (port 3000)
            │
            ├── Metabase Metadata DB (PostgreSQL, port 5433)
            │   ├── Saved questions
            │   ├── Dashboards
            │   └── Configuration
            │
            └── DOU Analytics Data (read-only)
                    │
                    ├── analytics_workforce
                    ├── analytics_attendance
                    ├── analytics_rider_performance
                    ├── analytics_payroll
                    ├── analytics_documents
                    ├── analytics_vehicles
                    ├── analytics_import_health
                    ├── analytics_reconciliation
                    └── analytics_orders
```

## Tenant Isolation Strategy

### Security Boundary
- **DOU-controlled analytics views** enforce tenant_id filtering
- **Metabase uses read-only database role** (`metabase_readonly`)
- **Server-generated constrained queries** prevent cross-tenant access
- **Native DOU reports** for sensitive analytics (full RBAC enforcement)

### Database Permissions (for Neon/PostgreSQL production)
```sql
-- Create read-only role for Metabase
CREATE ROLE metabase_readonly WITH LOGIN PASSWORD '[REDACTED]';

-- Grant SELECT on analytics views only
GRANT SELECT ON analytics_workforce TO metabase_readonly;
GRANT SELECT ON analytics_attendance TO metabase_readonly;
GRANT SELECT ON analytics_rider_performance TO metabase_readonly;
GRANT SELECT ON analytics_payroll TO metabase_readonly;
GRANT SELECT ON analytics_documents TO metabase_readonly;
GRANT SELECT ON analytics_vehicles TO metabase_readonly;
GRANT SELECT ON analytics_import_health TO metabase_readonly;
GRANT SELECT ON analytics_reconciliation TO metabase_readonly;
GRANT SELECT ON analytics_orders TO metabase_readonly;

-- Revoke all write permissions
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM metabase_readonly;
```

## Metabase OSS Capabilities Verified

| Feature | OSS Status | Notes |
|---------|-----------|-------|
| Self-hosting | ✅ Free | Docker image available |
| Dashboards | ✅ Available | Full dashboard support |
| Questions | ✅ Available | SQL + visual query builder |
| Embedding | ✅ Available | Signed embedding |
| Row-level security | ❌ Paid only | Use DOU-controlled views |
| SSO | ❌ Paid only | Use Metabase native auth |
| Sandboxing | ❌ Paid only | Use DB-level permissions |

## Production Deployment Notes

1. **Do NOT use Metabase Cloud** — use self-hosted OSS only
2. **Separate metadata DB** — Metabase's internal data stays separate
3. **Read-only analytics role** — Metabase never gets write access
4. **Tenant-scoped views** — All analytics views include tenant_id
5. **DOU enforces security** — Don't rely on Metabase filters for tenant isolation

## Stopping

```bash
docker-compose -f docker-compose.metabase.yml down

# Stop and remove volumes (WARNING: deletes Metabase config)
docker-compose -f docker-compose.metabase.yml down -v
```
