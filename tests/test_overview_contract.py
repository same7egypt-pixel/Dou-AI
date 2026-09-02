"""The Command Center must read fields /fleet/overview actually returns.

Eight of the twelve KPI cards on the landing screen rendered blank because the
view read `overview.total_riders`, `overview.online_riders`,
`overview.expired_docs` and five more names the endpoint has never sent. Reading
a missing key in JavaScript yields `undefined` rather than an error, so the card
just showed a dash and nothing anywhere reported a problem.

This pins the contract from both ends: the endpoint must keep sending the names
the screen reads, and the screen must not invent new ones.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "frontend-v2" / "fleet" / "views" / "commandCenter.js"
ROUTER = ROOT / "app" / "routers" / "fleet.py"

# Read off the view, so adding a card to the screen extends this automatically.
CONSUMED = re.compile(r"\boverview\.([a-zA-Z_][\w]*)")


def _fields_the_screen_reads() -> set[str]:
    return set(CONSUMED.findall(VIEW.read_text(encoding="utf-8")))


def _fields_the_endpoint_returns() -> set[str]:
    """Keys in the dict literal fleet_overview returns."""
    source = ROUTER.read_text(encoding="utf-8")
    start = source.index("def fleet_overview(")
    # The next top-level def bounds the function body.
    rest = source[start:]
    end = rest.index("\ndef ", 1) if "\ndef " in rest[1:] else len(rest)
    body = rest[:end]
    return set(re.findall(r'^\s*"([a-z_0-9]+)":', body, re.M))


def test_command_center_reads_only_fields_the_endpoint_sends():
    consumed = _fields_the_screen_reads()
    returned = _fields_the_endpoint_returns()
    missing = sorted(consumed - returned)

    assert not missing, (
        "commandCenter.js reads these from /fleet/overview but the endpoint does "
        f"not return them, so their cards render blank: {missing}"
    )


def test_the_endpoint_still_sends_the_headline_numbers():
    """Named explicitly: renaming one of these silently empties a card."""
    returned = _fields_the_endpoint_returns()
    for field in (
        "couriers_total",
        "couriers_online",
        "shifts_running",
        "not_ready",
        "absent_today",
        "present_today",
        "on_leave",
        "pending_leaves",
        "documents_expired",
        "documents_30",
        "documents_60",
    ):
        assert field in returned, f"/fleet/overview no longer returns {field!r}"
