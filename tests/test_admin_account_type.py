"""The admin console must ask for the account type when creating a company.

A platform account was created on the platform plan, priced at 7500, and still
came up as a fleet partner with a payroll screen. The API was correct: it
defaults to the narrower type when customer_type is absent, and the console
never sent it, because the field did not exist on the form. Backend support
without the field that feeds it is not a feature.

The type cannot be changed from inside the product on purpose - it decides what
the account is - so the console is the only place it can be set, and later
corrected.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TENANTS_JS = (ROOT / "frontend-v2" / "admin" / "views" / "tenants.js").read_text(encoding="utf-8")
ADMIN_PY = (ROOT / "app" / "routers" / "admin.py").read_text(encoding="utf-8")


def test_the_create_form_offers_both_account_types():
    assert "ncType" in TENANTS_JS, "the create-company form has no account-type selector"
    assert "LOGISTICS_OPERATOR" in TENANTS_JS
    assert "DELIVERY_PLATFORM" in TENANTS_JS


def test_the_create_request_actually_sends_the_type():
    """The field existing is not enough; it has to reach the API."""
    assert "api.post('/admin/tenants'" in TENANTS_JS or 'api.post("/admin/tenants"' in TENANTS_JS
    assert "payload['customer_type'] = typeSelect.value" in TENANTS_JS, (
        "the form collects a type and then posts without it, so every account "
        "is created as a logistics company"
    )


def test_an_existing_account_can_be_corrected():
    block = ADMIN_PY[ADMIN_PY.index("def patch_tenant(") :]
    block = block[: block.index("\n@router")]
    assert "customer_type" in block, (
        "there is no way to fix an account created before the console asked"
    )


def test_correcting_the_type_re_derives_capabilities():
    """Keeping the old set would leave a platform holding payroll."""
    block = ADMIN_PY[ADMIN_PY.index("def patch_tenant(") :]
    block = block[: block.index("\n@router")]
    assert "resolve_capabilities" in block
    assert "serialize_capabilities" in block
