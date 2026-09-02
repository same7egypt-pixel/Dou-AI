"""What a tenant is allowed to do, decided once and served by the API.

The frontend used to decide this itself: a header button flipped
``customer_type`` in the browser store, which showed a logistics company the
platform chrome over its own unchanged data. State the client can invent is not
state, so the account type is fixed when the account is created and the server
sends the capability set with every session.

Three shapes exist today, and they differ by capability rather than by codebase:

  LOGISTICS_OPERATOR  a company that sponsors riders and pays them
  DELIVERY_PLATFORM   a platform that works through many logistics vendors
  vendor portal       a vendor whose platform opened its dashboard to it,
                      which is the logistics set plus a read-only link
"""

from __future__ import annotations

import json
from typing import Iterable

from ..models.entities import Capability, CustomerType

# A vendor granted access through a platform. Not a customer type of its own:
# the vendor is a logistics company first, and this is an add-on its platform
# pays for. Keeping it a capability is what stops the platform from being able
# to end the vendor's subscription by withdrawing one setting.
VENDOR_PORTAL = "VENDOR_PORTAL"

LOGISTICS_DEFAULTS: tuple[str, ...] = (
    Capability.MANAGE_RIDERS.value,
    Capability.MANAGE_SUPERVISORS.value,
    Capability.RIDER_PAYROLL.value,
    Capability.DOU_SHIFT_MANAGEMENT.value,
    Capability.MANUAL_PERFORMANCE_IMPORT.value,
)

# No RIDER_PAYROLL: a platform does not pay riders, its vendors do. Showing it a
# payroll screen would either be empty or imply a financial decision it does not
# make. A platform that sponsors riders directly gets the capability added.
PLATFORM_DEFAULTS: tuple[str, ...] = (
    Capability.MANAGE_RIDERS.value,
    Capability.MANAGE_SUPERVISORS.value,
    Capability.MANAGE_OPERATORS.value,
    Capability.OPERATOR_SETTLEMENTS.value,
    Capability.EXTERNAL_SHIFT_SOURCE.value,
    Capability.PERFORMANCE_API_INGESTION.value,
    Capability.MANUAL_PERFORMANCE_IMPORT.value,
)

KNOWN_CAPABILITIES: frozenset[str] = frozenset(
    [c.value for c in Capability] + [VENDOR_PORTAL]
)

DEFAULTS_BY_TYPE = {
    CustomerType.LOGISTICS_OPERATOR.value: LOGISTICS_DEFAULTS,
    CustomerType.DELIVERY_PLATFORM.value: PLATFORM_DEFAULTS,
}


def normalize_customer_type(value: str | None) -> str:
    """Fall back to logistics: it is the narrower of the two."""
    candidate = (value or "").strip().upper()
    if candidate in DEFAULTS_BY_TYPE:
        return candidate
    return CustomerType.LOGISTICS_OPERATOR.value


def default_capabilities(customer_type: str) -> list[str]:
    return list(DEFAULTS_BY_TYPE[normalize_customer_type(customer_type)])


def clean_capabilities(requested: Iterable[str] | None) -> list[str]:
    """Drop anything not in the enum. An unknown capability is a typo that would
    otherwise sit in the database granting nothing and confusing the next
    reader."""
    if not requested:
        return []
    return sorted({str(c).strip().upper() for c in requested} & KNOWN_CAPABILITIES)


def resolve_capabilities(
    customer_type: str, requested: Iterable[str] | None = None
) -> list[str]:
    """Explicit list wins; otherwise the account type's defaults."""
    explicit = clean_capabilities(requested)
    return explicit or default_capabilities(customer_type)


def serialize(capabilities: Iterable[str]) -> str:
    return json.dumps(sorted(set(capabilities)), ensure_ascii=False)


def parse(stored: str | None) -> list[str]:
    """Tolerate the column being empty, malformed, or already a list."""
    if not stored:
        return []
    if isinstance(stored, (list, tuple)):
        return clean_capabilities(stored)
    try:
        loaded = json.loads(stored)
    except (TypeError, ValueError):
        return []
    return clean_capabilities(loaded) if isinstance(loaded, list) else []


def capabilities_for(tenant) -> list[str]:
    """The capability set a session should be told about.

    Falls back to the account type's defaults when the column was never
    populated, so tenants created before this existed behave sensibly instead of
    losing every screen.
    """
    if tenant is None:
        return []
    stored = parse(getattr(tenant, "capabilities", None))
    if stored:
        return stored
    return default_capabilities(getattr(tenant, "customer_type", None))
