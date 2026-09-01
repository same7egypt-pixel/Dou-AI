import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_production_rejects_missing_secret_key():
    env = os.environ.copy()
    env["APP_ENV"] = "production"
    env.pop("SECRET_KEY", None)

    result = subprocess.run(
        [sys.executable, "-c", "import app.config"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr


def test_production_rejects_empty_secret_key():
    env = os.environ.copy()
    env["APP_ENV"] = "production"
    env["SECRET_KEY"] = ""

    result = subprocess.run(
        [sys.executable, "-c", "import app.config"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr


def test_production_rejects_explicit_default_secret_key():
    env = os.environ.copy()
    env["APP_ENV"] = "production"
    env["SECRET_KEY"] = "change-me-in-production"

    result = subprocess.run(
        [sys.executable, "-c", "import app.config"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr


def test_production_rejects_whitespace_only_secret_key():
    env = os.environ.copy()
    env["APP_ENV"] = "production"
    env["SECRET_KEY"] = "   "

    result = subprocess.run(
        [sys.executable, "-c", "import app.config"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr


def test_production_rejects_short_secret_key():
    env = os.environ.copy()
    env["APP_ENV"] = "production"
    env["SECRET_KEY"] = "short-secret"
    result = subprocess.run(
        [sys.executable, "-c", "import app.config"], cwd=REPO_ROOT,
        env=env, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr
