import os
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_importing_application_does_not_create_or_migrate_database(tmp_path):
    database_path = tmp_path / "import-side-effect.db"
    env = os.environ.copy()
    env["APP_ENV"] = "test"
    env["DATABASE_URL"] = f"sqlite:///{database_path}"
    env["SECRET_KEY"] = "test-only-secret-key"
    env.pop("RENDER", None)

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not database_path.exists()


def test_application_startup_does_not_mutate_database(tmp_path):
    database_path = tmp_path / "startup.db"
    env = os.environ.copy()
    env["APP_ENV"] = "test"
    env["DATABASE_URL"] = f"sqlite:///{database_path}"
    env["SECRET_KEY"] = "test-only-secret-key"
    env.pop("RENDER", None)
    script = """
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    assert client.get('/health').status_code == 200
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not database_path.exists()


def test_explicit_migration_command_initializes_database(tmp_path):
    database_path = tmp_path / "migration.db"
    env = os.environ.copy()
    env["APP_ENV"] = "test"
    env["DATABASE_URL"] = f"sqlite:///{database_path}"
    env["SECRET_KEY"] = "test-only-secret-key"
    env.pop("RENDER", None)

    result = subprocess.run(
        [sys.executable, "tools/migrate.py"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert database_path.exists()
    with sqlite3.connect(database_path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert revision is not None


def test_explicit_migration_command_is_idempotent(tmp_path):
    database_path = tmp_path / "migration-twice.db"
    env = os.environ.copy()
    env["APP_ENV"] = "test"
    env["DATABASE_URL"] = f"sqlite:///{database_path}"
    env["SECRET_KEY"] = "test-only-secret-key"
    env.pop("RENDER", None)

    first = subprocess.run(
        [sys.executable, "tools/migrate.py"], cwd=REPO_ROOT, env=env,
        capture_output=True, text=True,
    )
    second = subprocess.run(
        [sys.executable, "tools/migrate.py"], cwd=REPO_ROOT, env=env,
        capture_output=True, text=True,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    with sqlite3.connect(database_path) as connection:
        revision_rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    assert len(revision_rows) == 1


def test_readiness_endpoint_checks_initialized_database(tmp_path):
    database_path = tmp_path / "readiness.db"
    env = os.environ.copy()
    env["APP_ENV"] = "test"
    env["DATABASE_URL"] = f"sqlite:///{database_path}"
    env["SECRET_KEY"] = "test-only-secret-key"
    env.pop("RENDER", None)
    script = """
from fastapi.testclient import TestClient
from app.db_maintenance import initialize_database
from app.main import app
initialize_database()
with TestClient(app) as client:
    response = client.get('/health/ready')
    assert response.status_code == 200, response.text
    assert response.json()['database'] == 'ok'
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
