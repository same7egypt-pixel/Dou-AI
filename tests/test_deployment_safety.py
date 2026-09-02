"""Guards on the deployment configuration and schema bootstrap.

Each assertion here corresponds to a fix that was reverted once already, in
every case as a pragmatic workaround for a real deployment error. They are
tested rather than documented because none of them is visible from the app's
behaviour: the system runs fine either way, right up until it does not.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def test_compose_declares_no_fallback_secrets():
    """A guessable default in a tracked file is worse than a stack that refuses
    to start, because it looks like a real production credential to anyone
    reading the repository."""
    for variable in ("SECRET_KEY", "ADMIN_KEY", "POSTGRES_PASSWORD"):
        # ${VAR:-something} supplies a default; ${VAR:?message} demands a value.
        default = re.search(rf"\$\{{{variable}:-([^}}]*)\}}", COMPOSE)
        assert default is None, (
            f"{variable} has the inline default {default.group(1)!r} in "
            "docker-compose.yml; require it with ${VAR:?message} instead"
        )
        assert f"${{{variable}:?" in COMPOSE, (
            f"{variable} should be required with ${{{variable}:?message}}"
        )


def test_app_container_has_no_source_bind_mount():
    """With `.:/app` the container runs host files instead of its image, so a
    file copy appears to deploy and a rebuild appears to do nothing."""
    assert ".:/app" not in COMPOSE, (
        "docker-compose.yml bind-mounts the source into the app container; "
        "releases must come from a rebuilt image"
    )


def test_datastores_are_not_published_on_all_interfaces():
    """PostgreSQL and Redis belong on loopback. The security group is the outer
    layer, not the only one."""
    for port in ("5432", "6379"):
        assert f'"127.0.0.1:{port}:{port}"' in COMPOSE, (
            f"port {port} should be published on loopback only"
        )


def test_create_all_failures_are_not_swallowed():
    """create_all already skips existing objects, so an exception here means the
    database is genuinely wrong and the app must not boot past it."""
    source = (ROOT / "app" / "db_maintenance.py").read_text(encoding="utf-8")
    initialize = source[source.index("def initialize_database") :]
    body = initialize[: initialize.index("\ndef ")] if "\ndef " in initialize else initialize
    assert "create_all" in body
    assert "except Exception" not in body, (
        "initialize_database swallows create_all failures and reports success; "
        "a partial schema must stop the boot instead"
    )


def test_courier_indexes_are_declared_on_the_model():
    """A fresh install builds its schema from create_all, not from migrations,
    so an index that lives only in a migration is absent there. Migration 0022
    uses if_not_exists, so declaring them in both places is safe."""
    source = (ROOT / "app" / "models" / "entities.py").read_text(encoding="utf-8")
    for index in (
        "ix_couriers_tenant_id",
        "ix_couriers_tenant_supervisor",
        "ix_couriers_tenant_branch",
    ):
        assert index in source, f"{index} is missing from the Courier model"


def test_index_migration_is_idempotent():
    """Both schema paths can create these indexes, so the migration must
    tolerate finding them already there."""
    migration = next(
        (ROOT / "alembic" / "versions").glob("*hot_query_indexes*.py")
    ).read_text(encoding="utf-8")
    assert "if_not_exists=True" in migration, (
        "the index migration must use if_not_exists, or it collides with "
        "create_all on a database that already has them"
    )


def test_ci_workflow_is_present():
    """The pipeline previously lived in deploy/ci/, where GitHub never ran it,
    and was later deleted outright. Nothing was enforced on push either way."""
    workflow = ROOT / ".github" / "workflows" / "ci.yml"
    assert workflow.exists(), (
        "no .github/workflows/ci.yml, so lint, tests, migrations and the image "
        "build are not gating pushes"
    )
    content = workflow.read_text(encoding="utf-8")
    for step in ("ruff check", "pytest", "alembic check", "node --check"):
        assert step in content, f"CI does not run {step!r}"
