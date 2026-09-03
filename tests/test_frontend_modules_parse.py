"""Every shipped frontend module must parse.

Replaces the node-parse check that used to run over the retired dashboard's one
big inline script. The product is ES modules now, and a syntax error in any of
them is a blank screen with a console error nobody reads — the failure mode that
check existed to catch, so it follows the code to where the code lives.

The rest of the tests that read static/fleet.html went with the file: they
asserted that the old dashboard contained certain sections and functions, which
says nothing about the product customers use. What they covered in substance is
covered against the real thing — payroll by test_payroll_golden and
test_phase1_readiness_fixes, imports by test_w6_imports, the command centre by
test_overview_contract, the rider list by test_riders_list_contract, analytics
embedding by test_metabase_embed_isolation.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend-v2"

MODULES = sorted(FRONTEND.rglob("*.js"))


def test_there_are_modules_to_check():
    """A glob that silently matches nothing would make every test below pass."""
    assert len(MODULES) >= 15, f"only found {len(MODULES)} modules under frontend-v2"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("module", MODULES, ids=lambda p: str(p.relative_to(FRONTEND)))
def test_module_parses(module):
    result = subprocess.run(
        ["node", "--input-type=module", "--check"],
        stdin=module.open("rb"),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{module.relative_to(ROOT)} does not parse — the screen it backs will "
        f"render blank:\n{result.stderr.strip()[:600]}"
    )
