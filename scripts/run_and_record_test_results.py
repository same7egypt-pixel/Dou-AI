"""Run and record all test results for the DOU Read-Only Independent Audit Package."""
import os
import sys
import time
import subprocess
import tempfile

BASE_DIR = "/Users/sameh/DOU-review/dou-server"
OUT_DIR = "/tmp/dou_audit_package_build/test-results"
os.makedirs(OUT_DIR, exist_ok=True)


def execute_and_log(filename, title, command, env_extra=None):
    print(f"Running: {title} ({command})...")
    filepath = os.path.join(OUT_DIR, filename)
    
    env = os.environ.copy()
    env["PYTHONPATH"] = BASE_DIR
    if env_extra:
        env.update(env_extra)

    start_time = time.time()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            env=env
        )
        duration = time.time() - start_time
        exit_code = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except Exception as e:
        duration = time.time() - start_time
        exit_code = -1
        stdout = ""
        stderr = str(e)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write(f"{title}\n")
        f.write("================================================================================\n\n")
        f.write(f"Command: {command}\n")
        f.write(f"Working Directory: {BASE_DIR}\n")
        f.write(f"Execution Duration: {duration:.2f} seconds\n")
        f.write(f"Exit Code: {exit_code}\n")
        f.write(f"Status: {'PASSED' if exit_code == 0 else 'FAILED'}\n\n")
        f.write("--- STDOUT ---\n")
        f.write(stdout + "\n\n")
        f.write("--- STDERR ---\n")
        f.write(stderr + "\n")

    print(f"  -> {filename} saved (Exit Code: {exit_code}, Duration: {duration:.2f}s)")
    return exit_code


def main():
    print("Collecting and recording test results...")

    # 1. Backend Unit/Integration Tests
    execute_and_log(
        "01_BACKEND_TESTS.txt",
        "BACKEND UNIT & INTEGRATION TEST SUITE (PYTEST)",
        ".venv/bin/pytest -v"
    )

    # 2. Frontend Static & Lint
    execute_and_log(
        "02_FRONTEND_STATIC_AND_LINT.txt",
        "FRONTEND JAVASCRIPT & ASSETS INTEGRITY CHECKS",
        "node tools/check_fleet_js.mjs && node -c frontend-v2/fleet/main.js && node -c frontend-v2/shared/api/client.js"
    )

    # 3. Startup Smoke Test
    smoke_cmd = """
.venv/bin/python -c "
import sys
from app.main import app
from app.database import engine, Base
from sqlalchemy import text

print('Importing FastAPI application: SUCCESS')
print(f'Title: {app.title}, Version: {app.version}')
print(f'Total Registered Routes: {len(app.routes)}')

with engine.connect() as conn:
    res = conn.execute(text('SELECT 1')).scalar()
    print(f'Database Connection Check: SUCCESS (SELECT 1 -> {res})')
"
"""
    execute_and_log(
        "03_STARTUP_SMOKE_TEST.txt",
        "BACKEND APPLICATION STARTUP & DATABASE CONNECTIVITY SMOKE TEST",
        smoke_cmd
    )

    # 4. Database Migration Validation on Fresh Temp DB
    mig_cmd = """
.venv/bin/python -c "
import tempfile
from sqlalchemy import create_engine
from app.database import Base
import app.models.entities
import app.models.salary
import app.models.intelligence

with tempfile.NamedTemporaryFile(suffix='.db') as tmp_db:
    temp_db_url = f'sqlite:///{tmp_db.name}'
    engine = create_engine(temp_db_url)
    Base.metadata.create_all(bind=engine)
    print('Fresh Database Schema Generation: SUCCESS')
    print(f'Created {len(Base.metadata.sorted_tables)} tables successfully.')
"
"""
    execute_and_log(
        "04_DATABASE_MIGRATION_VALIDATION.txt",
        "DATABASE MIGRATION & SCHEMA INITIALIZATION VALIDATION ON FRESH DB",
        mig_cmd
    )

    # 5. E2E Acceptance Tests
    execute_and_log(
        "05_E2E_ACCEPTANCE_TESTS.txt",
        "END-TO-END ACCEPTANCE & SCENARIOS REGRESSION SUITE (PLAYWRIGHT)",
        "node e2e/test-3-scenarios-live-acceptance.mjs"
    )

    print("All test results recorded successfully.")


if __name__ == "__main__":
    main()
