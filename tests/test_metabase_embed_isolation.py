"""The signed embed must pin one tenant, or the dashboard shows everyone.

Metabase signed embedding carries its filters inside the JWT. The generator
previously accepted a tenant argument and then sent `params: {}`, which leaves
the dashboard filter unlocked: every customer renders the same dashboard over
every tenant's rows. It was never reachable in production because Metabase was
never switched on, so this guard exists to keep it that way.

Three things have to hold, and each has bitten a real system somewhere:
  - the tenant is inside the signed payload, not the query string
  - there is no fallback signing key in source
  - a request without a tenant is refused rather than signed wide open
"""

import importlib
import time

import jwt
import pytest
from fastapi import HTTPException

SECRET = "test-embed-secret-key-for-signing-only"


@pytest.fixture
def reports(monkeypatch):
    """Reload the module so it picks up the patched environment."""
    monkeypatch.setenv("METABASE_EMBEDDING_SECRET_KEY", SECRET)
    monkeypatch.setenv("METABASE_URL", "https://metabase.example")
    module = importlib.import_module("app.routers.reports")
    return importlib.reload(module)


def _payload(url: str) -> dict:
    token = url.split("/embed/dashboard/")[1].split("#")[0]
    return jwt.decode(token, SECRET, algorithms=["HS256"])


def test_tenant_is_locked_inside_the_signed_payload(reports):
    url = reports._generate_metabase_embed_url(2, tenant_id=7)
    payload = _payload(url)

    assert payload["params"], (
        "params is empty, so the dashboard filter is unlocked and renders "
        "every tenant's rows"
    )
    assert payload["params"][reports.METABASE_TENANT_PARAM] == 7
    assert payload["resource"] == {"dashboard": 2}


def test_the_tenant_never_travels_in_the_query_string(reports):
    """A tenant outside the signature is a tenant the viewer can edit."""
    url = reports._generate_metabase_embed_url(2, tenant_id=7)
    query_and_fragment = url.split("/embed/dashboard/")[1]
    after_token = query_and_fragment.split("#", 1)[1]
    assert "tenant" not in after_token.lower()


def test_two_tenants_get_different_tokens(reports):
    a = reports._generate_metabase_embed_url(2, tenant_id=1)
    b = reports._generate_metabase_embed_url(2, tenant_id=2)
    assert a != b
    assert _payload(a)["params"] != _payload(b)["params"]


def test_a_missing_tenant_is_refused_rather_than_signed_wide_open(reports):
    for missing in (None, 0):
        with pytest.raises(HTTPException) as raised:
            reports._generate_metabase_embed_url(2, tenant_id=missing)
        assert raised.value.status_code == 403


def test_signing_fails_closed_without_a_configured_key(monkeypatch):
    monkeypatch.setenv("METABASE_EMBEDDING_SECRET_KEY", "")
    module = importlib.reload(importlib.import_module("app.routers.reports"))
    with pytest.raises(HTTPException) as raised:
        module._generate_metabase_embed_url(2, tenant_id=7)
    assert raised.value.status_code == 503


def test_no_signing_key_is_hardcoded_in_source():
    """A fallback key in the repository is a forgeable token for every dashboard."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "routers" / "reports.py"
    ).read_text(encoding="utf-8")
    line = next(
        ln for ln in source.splitlines() if "METABASE_EMBEDDING_SECRET_KEY = " in ln
    )
    assert 'os.getenv("METABASE_EMBEDDING_SECRET_KEY", "")' in line, (
        "the embedding key must come from the environment with no fallback"
    )


def test_the_token_expires_quickly(reports):
    payload = reports._generate_metabase_embed_url(2, tenant_id=7)
    lifetime = _payload(payload)["exp"] - int(time.time())
    assert 0 < lifetime <= 3600, (
        "an embed URL carries a tenant's data; it should live minutes, not a day"
    )


def test_unknown_dashboards_are_rejected(reports):
    with pytest.raises(HTTPException) as raised:
        reports._generate_metabase_embed_url(9999, tenant_id=7)
    assert raised.value.status_code == 404
