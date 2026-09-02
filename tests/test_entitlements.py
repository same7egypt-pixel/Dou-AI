"""Account type and capabilities are decided server-side, once, at creation.

A header button used to flip `customer_type` inside the browser's own store.
It was not a data leak -- the operators list filters on the caller's tenant and
`operator_id` only narrows a query that is already tenant-filtered -- but it
showed an account the chrome of a product it had not bought, and it put a
product decision in the one place that does not hold the truth.

These tests pin the replacement: the type is fixed when the tenant is created,
capabilities follow from it, the session endpoint reports them, and no client
code writes either field.
"""

import json
import re
from pathlib import Path

import pytest

from app.models.entities import Capability, CustomerType
from app.services.entitlements import (
    VENDOR_PORTAL,
    capabilities_for,
    clean_capabilities,
    default_capabilities,
    normalize_customer_type,
    parse,
    resolve_capabilities,
    serialize,
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend-v2"


class _Tenant:
    def __init__(self, customer_type=None, capabilities=None):
        self.customer_type = customer_type
        self.capabilities = capabilities


# ---------------------------------------------------------------- the matrix


def test_a_platform_has_no_payroll_capability():
    """A platform does not pay riders; its vendors do. Granting it payroll would
    either render an empty screen or imply a decision it does not make."""
    platform = default_capabilities(CustomerType.DELIVERY_PLATFORM.value)
    assert Capability.RIDER_PAYROLL.value not in platform
    assert Capability.MANAGE_OPERATORS.value in platform
    assert Capability.OPERATOR_SETTLEMENTS.value in platform


def test_a_logistics_company_has_payroll_and_no_operator_management():
    logistics = default_capabilities(CustomerType.LOGISTICS_OPERATOR.value)
    assert Capability.RIDER_PAYROLL.value in logistics
    assert Capability.MANAGE_OPERATORS.value not in logistics
    assert Capability.OPERATOR_SETTLEMENTS.value not in logistics


def test_the_vendor_portal_is_a_capability_not_a_customer_type():
    """The vendor stays a logistics company. Keeping the link a capability is
    what stops a platform from ending the vendor's subscription by withdrawing
    one setting."""
    assert VENDOR_PORTAL not in [t.value for t in CustomerType]
    assert VENDOR_PORTAL in clean_capabilities([VENDOR_PORTAL])


# ---------------------------------------------------------------- resolution


def test_an_unknown_type_falls_back_to_the_narrower_one():
    for value in (None, "", "PLATFORM", "nonsense"):
        assert normalize_customer_type(value) == CustomerType.LOGISTICS_OPERATOR.value


def test_unknown_capabilities_are_dropped_rather_than_stored():
    cleaned = clean_capabilities(["RIDER_PAYROLL", "NOT_A_CAPABILITY", "manage_riders"])
    assert cleaned == ["MANAGE_RIDERS", "RIDER_PAYROLL"]


def test_an_explicit_list_overrides_the_defaults():
    resolved = resolve_capabilities(
        CustomerType.DELIVERY_PLATFORM.value, ["MANAGE_RIDERS"]
    )
    assert resolved == ["MANAGE_RIDERS"]


def test_a_tenant_created_before_capabilities_existed_still_works():
    """The column is empty on older rows; falling back to the type's defaults
    keeps them working instead of losing every screen."""
    legacy = _Tenant(customer_type=CustomerType.LOGISTICS_OPERATOR.value, capabilities=None)
    assert Capability.RIDER_PAYROLL.value in capabilities_for(legacy)


def test_a_malformed_capabilities_column_does_not_break_the_session():
    for broken in ("{", "null", '"RIDER_PAYROLL"', "[]"):
        tenant = _Tenant(CustomerType.DELIVERY_PLATFORM.value, broken)
        resolved = capabilities_for(tenant)
        assert Capability.MANAGE_OPERATORS.value in resolved


def test_serialize_and_parse_round_trip():
    caps = default_capabilities(CustomerType.DELIVERY_PLATFORM.value)
    assert sorted(parse(serialize(caps))) == sorted(caps)
    assert json.loads(serialize(caps))


# ---------------------------------------------------------------- the server owns it


def test_tenant_creation_records_type_and_capabilities():
    source = (ROOT / "app" / "routers" / "admin.py").read_text(encoding="utf-8")
    block = source[source.index("def create_tenant(") :]
    block = block[: block.index("\n@router")]
    assert "normalize_customer_type(payload.get(\"customer_type\"))" in block
    assert "customer_type=customer_type" in block
    assert "capabilities=serialize_capabilities(capabilities)" in block


def test_the_session_endpoint_returns_a_real_capability_list():
    source = (ROOT / "app" / "routers" / "fleet.py").read_text(encoding="utf-8")
    assert '"capabilities": capabilities_for(tenant),' in source, (
        "/fleet/me must send the resolved list, not the raw column"
    )


# ---------------------------------------------------------------- the client does not


def test_no_client_code_writes_the_account_type():
    """This is the defect itself: the toggle set customer_type in the store."""
    offenders = []
    assignment = re.compile(r"customer_type\s*:\s*(?!\s*$)", re.M)
    for path in FRONTEND.rglob("*.js"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            if assignment.search(line):
                offenders.append(f"{path.name}:{number} {stripped[:80]}")
    assert not offenders, (
        "client code assigns customer_type; the account type is server truth:\n  "
        + "\n  ".join(offenders)
    )


def test_the_operating_model_switcher_is_gone():
    shell = (FRONTEND / "fleet" / "shell.js").read_text(encoding="utf-8")
    assert "btn-toggle-operating-model" not in shell, (
        "the mode switcher is back; a mode the browser can change is not a mode"
    )


def test_the_sidebar_is_gated_on_capabilities():
    shell = (FRONTEND / "fleet" / "shell.js").read_text(encoding="utf-8")
    assert "RIDER_PAYROLL" in shell and "can(" in shell, (
        "the sidebar should hide screens the account has no capability for"
    )


@pytest.mark.parametrize("plan", ["VENDOR", "PLATFORM"])
def test_the_new_plans_are_offered(plan):
    source = (ROOT / "app" / "routers" / "admin.py").read_text(encoding="utf-8")
    assert f'("{plan}"' in source


def test_plan_seeding_is_additive():
    """Seeding only when the table is empty means a new plan never reaches an
    existing deployment."""
    source = (ROOT / "app" / "routers" / "admin.py").read_text(encoding="utf-8")
    block = source[source.index("def list_plans(") :]
    block = block[: block.index("\n@router")]
    assert "if not db.query(SubscriptionPlan).count():" not in block
    assert "missing" in block
