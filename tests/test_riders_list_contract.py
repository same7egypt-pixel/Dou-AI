"""The riders table must read fields /fleet/couriers/page actually returns.

The sponsorship column and its filter both read `courier_type`, which the
endpoint did not return. The view defaulted the missing value to "COMPANY", so
every rider displayed as company-sponsored regardless of what they were - wrong
data shown confidently, which is worse than a blank cell. The filter also ran in
the browser over the current page only, so it silently disagreed with paging.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "frontend-v2" / "fleet" / "views" / "riders.js"
ROUTER = ROOT / "app" / "routers" / "fleet.py"


def _paged_couriers_body() -> str:
    source = ROUTER.read_text(encoding="utf-8")
    start = source.index("def paged_couriers(")
    rest = source[start:]
    end = rest.index("\n@router", 1) if "\n@router" in rest[1:] else len(rest)
    return rest[:end]


def test_endpoint_returns_courier_type():
    body = _paged_couriers_body()
    assert '"courier_type":' in body, (
        "/fleet/couriers/page must return courier_type; the riders table renders "
        "a sponsorship badge from it"
    )


def test_endpoint_accepts_a_courier_type_filter():
    body = _paged_couriers_body()
    assert "courier_type: str = None" in body, (
        "/fleet/couriers/page must accept courier_type so filtering happens in "
        "SQL; a browser-side filter only narrows the page already fetched"
    )
    assert "Courier.courier_type ==" in body, "the parameter is accepted but not applied"


def test_view_sends_the_filter_to_the_server():
    source = VIEW.read_text(encoding="utf-8")
    assert "params.set('courier_type'" in source, (
        "riders.js must pass the type filter to the API rather than filtering rows locally"
    )


def test_view_does_not_invent_a_default_courier_type():
    """A missing field must read as unknown, not as a real sponsorship type."""
    source = VIEW.read_text(encoding="utf-8")
    assert not re.search(r"\(\s*v\s*\|\|\s*'COMPANY'\s*\)", source), (
        "riders.js falls back to 'COMPANY' for a missing courier_type, which "
        "presents absent data as fact"
    )
