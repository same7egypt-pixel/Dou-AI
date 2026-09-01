"""Generate exact audit evidence files for DOU Read-Only Independent Audit Package."""
import os
import sys
import subprocess
import datetime
import re
import json

BASE_DIR = "/Users/sameh/DOU-review/dou-server"
OUT_DIR = "/tmp/dou_audit_package_build/audit-evidence"
os.makedirs(OUT_DIR, exist_ok=True)


def run_cmd(cmd, cwd=BASE_DIR):
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
        return p.stdout + ("\nSTDERR:\n" + p.stderr if p.stderr else "")
    except Exception as e:
        return f"ERROR running '{cmd}': {e}"


def main():
    print("Generating audit evidence...")

    # 1. Project Metadata
    with open(f"{OUT_DIR}/01_PROJECT_METADATA.txt", "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("DOU PLATFORM — PROJECT AUDIT METADATA\n")
        f.write("================================================================================\n\n")
        f.write(f"Absolute Project Path: {BASE_DIR}\n")
        f.write(f"Audit Generation Timestamp: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n")
        f.write(f"Operating System: {sys.platform} ({os.uname().sysname} {os.uname().release} {os.uname().machine})\n")
        f.write(f"Python Version: {sys.version}\n")
        f.write(f"Python Executable: {sys.executable}\n")
        f.write(f"Node Version: {run_cmd('node -v').strip()}\n")
        f.write(f"NPM Version: {run_cmd('npm -v').strip()}\n")
        f.write(f"Git Version: {run_cmd('git --version').strip()}\n")

    # 2. Git Evidence
    with open(f"{OUT_DIR}/02_GIT_EVIDENCE.txt", "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("GIT REPOSITORY EVIDENCE & STATUS\n")
        f.write("================================================================================\n\n")
        f.write("--- Git Branch ---\n")
        f.write(run_cmd("git branch -vv") + "\n\n")
        f.write("--- Git Status ---\n")
        f.write(run_cmd("git status") + "\n\n")
        f.write("--- Git Log (Latest 20 Commits) ---\n")
        f.write(run_cmd("git log -n 20 --oneline --graph --decorate") + "\n\n")
        f.write("--- Git Diff Stat ---\n")
        f.write(run_cmd("git diff --stat") + "\n\n")
        f.write("--- Full Git Diff of Tracked Changes ---\n")
        f.write(run_cmd("git diff") + "\n\n")
        f.write("--- Untracked Files List ---\n")
        f.write(run_cmd("git ls-files --others --exclude-standard") + "\n")

    # 3. File Tree & Counts
    with open(f"{OUT_DIR}/03_FILE_TREE_AND_COUNTS.txt", "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("FILE TREE & EXTENSION INVENTORY\n")
        f.write("================================================================================\n\n")
        f.write("--- File Tree (Excluding .git, node_modules, .venv, build) ---\n")
        f.write(run_cmd("find . -maxdepth 4 -not -path '*/.*' -not -path './node_modules*' -not -path './.venv*' -not -path './venv*' | sort") + "\n\n")
        f.write("--- File Count by Extension ---\n")
        f.write(run_cmd("find . -type f -not -path '*/.*' -not -path './node_modules*' -not -path './.venv*' -not -path './venv*' | sed -n 's/..*\\.//p' | sort | uniq -c | sort -nr") + "\n\n")
        f.write("--- Total Lines of Code (Python, JavaScript, HTML, CSS) ---\n")
        f.write(run_cmd("find app frontend-v2 static tests e2e -type f \\( -name '*.py' -o -name '*.js' -o -name '*.html' -o -name '*.css' \\) -exec wc -l {} + | sort -n") + "\n")

    # 4. Dependency Inventory
    with open(f"{OUT_DIR}/04_DEPENDENCY_INVENTORY.txt", "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("DEPENDENCIES & MANIFESTS INVENTORY\n")
        f.write("================================================================================\n\n")
        f.write("--- requirements.txt ---\n")
        if os.path.exists(f"{BASE_DIR}/requirements.txt"):
            with open(f"{BASE_DIR}/requirements.txt") as req:
                f.write(req.read() + "\n\n")
        f.write("--- package.json ---\n")
        if os.path.exists(f"{BASE_DIR}/package.json"):
            with open(f"{BASE_DIR}/package.json") as pkg:
                f.write(pkg.read() + "\n\n")
        f.write("--- Installed Python Packages (.venv) ---\n")
        f.write(run_cmd(".venv/bin/pip list") + "\n")

    # 5. Database Schema & Migrations
    with open(f"{OUT_DIR}/05_DATABASE_SCHEMA_AND_MIGRATIONS.txt", "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("DATABASE SCHEMA, MODELS & MIGRATIONS INVENTORY\n")
        f.write("================================================================================\n\n")
        f.write("--- Alembic Migration Versions ---\n")
        if os.path.exists(f"{BASE_DIR}/alembic/versions"):
            f.write(run_cmd("ls -la alembic/versions/") + "\n\n")
        f.write("--- Alembic Current Revision Status ---\n")
        f.write(run_cmd(".venv/bin/alembic current") + "\n\n")
        f.write("--- SQL Analytics Views (analytics_views.sql) ---\n")
        if os.path.exists(f"{BASE_DIR}/analytics_views.sql"):
            with open(f"{BASE_DIR}/analytics_views.sql") as av:
                f.write(av.read() + "\n\n")
        f.write("--- SQLAlchemy Entity Table Names ---\n")
        extract_tables = """
PYTHONPATH=. .venv/bin/python -c "
from app.database import Base
import app.models.entities
import app.models.salary
import app.models.intelligence
for table in Base.metadata.sorted_tables:
    print(f'Table: {table.name} (Columns: {len(table.columns)})')
"
"""
        f.write(run_cmd(extract_tables) + "\n")

    # 6. Backend Routes Inventory
    with open(f"{OUT_DIR}/06_BACKEND_ROUTES_INVENTORY.txt", "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("BACKEND FASTAPI ROUTES & ENDPOINTS INVENTORY\n")
        f.write("================================================================================\n\n")
        extract_routes = """
PYTHONPATH=. .venv/bin/python -c "
from app.main import app
routes = []
for route in app.routes:
    methods = ','.join(route.methods) if hasattr(route, 'methods') else 'ALL'
    name = getattr(route, 'name', '')
    path = getattr(route, 'path', '')
    routes.append((methods, path, name))
routes.sort(key=lambda x: x[1])
for m, p, n in routes:
    print(f'{m:<12} {p:<45} {n}')
print(f'\\nTotal Registered Routes: {len(routes)}')
"
"""
        f.write(run_cmd(extract_routes) + "\n")

    # 7. Frontend Routes & Components
    with open(f"{OUT_DIR}/07_FRONTEND_ROUTES_AND_COMPONENTS.txt", "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("FRONTEND ROUTES, PAGES & UI VIEWS INVENTORY\n")
        f.write("================================================================================\n\n")
        f.write("1. Core User Interfaces:\n")
        f.write("   - /admin (DOU Master Admin Console) -> static/admin.html\n")
        f.write("   - /app/v2/ (DOU Fleet Management OS V2) -> frontend-v2/fleet/index.html\n")
        f.write("   - /driver or /app/courier (Rider Web OS PWA) -> static/courier.html\n")
        f.write("   - / (Landing & Public Portal) -> static/index.html\n")
        f.write("   - /static/fleet.html (Legacy Fleet Portal)\n")
        f.write("   - /static/supervisor.html (Supervisor Portal)\n\n")
        f.write("2. Frontend V2 Fleet Views (frontend-v2/fleet/views/):\n")
        f.write(run_cmd("ls -la frontend-v2/fleet/views/") + "\n\n")
        f.write("3. Frontend V2 Shared Components (frontend-v2/shared/components/):\n")
        f.write(run_cmd("ls -la frontend-v2/shared/components/") + "\n")

    # 8. Roles & Permissions Inventory
    with open(f"{OUT_DIR}/08_ROLES_PERMISSIONS_INVENTORY.txt", "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("ROLES & PERMISSIONS (RBAC) INVENTORY\n")
        f.write("================================================================================\n\n")
        extract_roles = """
PYTHONPATH=. .venv/bin/python -c "
from app.models.entities import UserRole
print('Defined User Roles:')
for r in UserRole:
    print(f' - {r.name} = {r.value}')
"
"""
        f.write(run_cmd(extract_roles) + "\n")

    # 9. Environment Variables Inventory (REDACTED)
    with open(f"{OUT_DIR}/09_ENVIRONMENT_VARIABLES_INVENTORY.txt", "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("REDACTED ENVIRONMENT VARIABLES INVENTORY (NAMES ONLY — NO SECRETS/VALUES)\n")
        f.write("================================================================================\n\n")
        env_vars = [
            ("DATABASE_URL", "Database connection string (SQLite file or PostgreSQL URI)", "Required"),
            ("SECRET_KEY", "JWT encryption secret key for signing auth tokens (>=32 bytes in prod)", "Required"),
            ("APP_ENV", "Runtime environment (development / staging / production)", "Optional (default: development)"),
            ("ADMIN_KEY", "Super Admin Master Key for /admin master access header", "Optional"),
            ("CORS_ORIGINS", "Allowed CORS origins for browser fetch requests", "Optional"),
            ("METABASE_URL", "URL of Metabase server instance (e.g. http://localhost:3000)", "Optional"),
            ("METABASE_EMBEDDING_SECRET_KEY", "Secret key for generating signed JWT Metabase dashboard embed URLs", "Optional"),
            ("METABASE_DATABASE_ID", "ID of DOU database connected inside Metabase", "Optional"),
            ("METABASE_API_KEY", "API key for Metabase server REST API calls", "Optional"),
            ("METABASE_WEBHOOK_SECRET", "Secret for verifying incoming Metabase alerts/webhooks", "Optional"),
            ("SMALL_ORDER_LOCAL_RADIUS_KM", "Radius in km for small order dispatching", "Optional (default: 5)"),
            ("LONG_DISTANCE_THRESHOLD_KM", "Threshold distance in km for long distance classification", "Optional (default: 25)"),
            ("DOU_AI_MODE", "Operational AI mode (DETERMINISTIC / LLM)", "Optional (default: DETERMINISTIC)"),
            ("GOOGLE_ANALYTICS_ID", "Google Analytics measurement ID", "Optional"),
            ("ENABLE_LEGACY_DELIVERY", "Toggle legacy delivery merchant routes", "Optional (default: false)"),
            ("ENABLE_PUBLIC_COMPANY_SIGNUP", "Toggle public company self-signup", "Optional (default: false)"),
        ]
        for name, desc, req in env_vars:
            f.write(f"VARIABLE: {name}\n")
            f.write(f"  Description: {desc}\n")
            f.write(f"  Status: {req}\n")
            f.write(f"  Value: [REDACTED]\n\n")

    # 10. Code Hygiene (TODO/FIXME Search)
    with open(f"{OUT_DIR}/10_CODE_HYGIENE_TODO_FIXME_SEARCH.txt", "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("CODE HYGIENE AUDIT: TODO / FIXME / HACK / STUB SEARCH RESULTS\n")
        f.write("================================================================================\n\n")
        f.write("--- grep -rn 'TODO' app/ frontend-v2/ static/ ---\n")
        f.write(run_cmd("grep -rn 'TODO' app frontend-v2 static || true") + "\n\n")
        f.write("--- grep -rn 'FIXME' app/ frontend-v2/ static/ ---\n")
        f.write(run_cmd("grep -rn 'FIXME' app frontend-v2 static || true") + "\n\n")
        f.write("--- grep -rn 'HACK' app/ frontend-v2/ static/ ---\n")
        f.write(run_cmd("grep -rn 'HACK' app frontend-v2 static || true") + "\n\n")
        f.write("--- grep -rn 'STUB' app/ frontend-v2/ static/ ---\n")
        f.write(run_cmd("grep -rn 'STUB' app frontend-v2 static || true") + "\n")

    # 11. Security Patterns & Credentials Search
    with open(f"{OUT_DIR}/11_SECURITY_PATTERNS_CREDENTIALS_SEARCH.txt", "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("SECURITY AUDIT: SENSITIVE PATTERNS & CREDENTIAL SEARCH\n")
        f.write("================================================================================\n\n")
        f.write("--- Hardcoded Password Patterns in app/ ---\n")
        f.write(run_cmd("grep -rn 'password\\s*=' app/ || true") + "\n\n")
        f.write("--- Localhost references in app/ and frontend-v2/ ---\n")
        f.write(run_cmd("grep -rn 'localhost' app/ frontend-v2/ || true") + "\n")

    # 12. API Coverage Matrix
    with open(f"{OUT_DIR}/12_API_COVERAGE_MATRIX.txt", "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("API COVERAGE MATRIX (FRONTEND FETCH CALLS VS BACKEND ROUTES)\n")
        f.write("================================================================================\n\n")
        f.write("--- Frontend API Endpoints Called in frontend-v2/ and static/ ---\n")
        f.write(run_cmd("grep -rhoE '(\\/api\\/[a-zA-Z0-9_\\-\\/{}]*|\\/admin\\/[a-zA-Z0-9_\\-\\/{}]*|\\/auth\\/[a-zA-Z0-9_\\-\\/{}]*|\\/fleet\\/[a-zA-Z0-9_\\-\\/{}]*|\\/shifts\\/[a-zA-Z0-9_\\-\\/{}]*|\\/hr\\/[a-zA-Z0-9_\\-\\/{}]*|\\/payroll\\/[a-zA-Z0-9_\\-\\/{}]*|\\/sources\\/[a-zA-Z0-9_\\-\\/{}]*|\\/client-invoices[a-zA-Z0-9_\\-\\/{}]*)' frontend-v2/ static/ | sort | uniq") + "\n")

    # 13. Deployment & Infrastructure
    with open(f"{OUT_DIR}/13_DEPLOYMENT_AND_INFRASTRUCTURE.txt", "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("PRODUCTION DEPLOYMENT & CONTAINER CONFIGURATION INVENTORY\n")
        f.write("================================================================================\n\n")
        f.write("--- Dockerfile ---\n")
        if os.path.exists(f"{BASE_DIR}/Dockerfile"):
            with open(f"{BASE_DIR}/Dockerfile") as df:
                f.write(df.read() + "\n\n")
        f.write("--- docker-compose.yml ---\n")
        if os.path.exists(f"{BASE_DIR}/docker-compose.yml"):
            with open(f"{BASE_DIR}/docker-compose.yml") as dc:
                f.write(dc.read() + "\n\n")
        f.write("--- docker-compose.metabase.yml ---\n")
        if os.path.exists(f"{BASE_DIR}/docker-compose.metabase.yml"):
            with open(f"{BASE_DIR}/docker-compose.metabase.yml") as dcm:
                f.write(dcm.read() + "\n\n")
        f.write("--- render.yaml ---\n")
        if os.path.exists(f"{BASE_DIR}/render.yaml"):
            with open(f"{BASE_DIR}/render.yaml") as ry:
                f.write(ry.read() + "\n\n")
        f.write("--- netlify.toml ---\n")
        if os.path.exists(f"{BASE_DIR}/netlify.toml"):
            with open(f"{BASE_DIR}/netlify.toml") as nt:
                f.write(nt.read() + "\n")

    print("Audit evidence generated successfully.")


if __name__ == "__main__":
    main()
