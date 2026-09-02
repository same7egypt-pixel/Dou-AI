"""Every button colour modifier must sit on the base `btn` class.

In main.css, `.btn` alone carries padding, border-radius, font-weight, cursor
and the inline-flex layout. `.btn-blue`, `.btn-ghost`, `.btn-green`, `.btn-red`,
`.btn-amber` and `.btn-primary` set nothing but colours. A control given only
the modifier therefore renders with no padding and square corners — visibly
broken, but with no console error and no failing request, so nothing catches it
except looking at the screen.

67 controls were in this state across Rider 360, Shifts, Capacity, Imports, the
admin console and notifications.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend-v2"
CSS = FRONTEND / "shared" / "styles" / "main.css"

# Modifiers that supply only colour and must be paired with `btn`.
COLOUR_ONLY = {
    "btn-blue",
    "btn-ghost",
    "btn-green",
    "btn-red",
    "btn-amber",
    "btn-primary",
}
# These bring their own padding and radius, so they stand alone.
SELF_SUFFICIENT = {"btn-ai", "btn-small", "btn-full"}

CLASS_PROP = re.compile(r"""class:\s*(?P<q>['"])(?P<value>[^'"]*?)(?P=q)""")


def _rule_body(css: str, selector: str) -> str:
    match = re.search(r"\.%s\s*\{([^}]*)\}" % re.escape(selector), css)
    return " ".join(match.group(1).split()) if match else ""


def test_colour_modifiers_really_are_colour_only():
    """Pin the premise. If a modifier gains its own padding, relax this list."""
    css = CSS.read_text(encoding="utf-8")
    base = _rule_body(css, "btn")
    assert "padding" in base and "border-radius" in base

    for modifier in COLOUR_ONLY:
        body = _rule_body(css, modifier)
        assert body, f".{modifier} is not defined in main.css"
        assert "padding" not in body, (
            f".{modifier} now sets its own padding; it is no longer colour-only"
        )


def test_base_btn_is_declared_before_its_modifiers():
    """Adding `btn` must not override a modifier's deliberate overrides."""
    css = CSS.read_text(encoding="utf-8")
    base_at = css.index(".btn {")
    for modifier in COLOUR_ONLY | SELF_SUFFICIENT:
        match = re.search(r"\.%s\s*\{" % re.escape(modifier), css)
        if match:
            assert match.start() > base_at, (
                f".{modifier} is declared before .btn, so .btn would override it"
            )


@pytest.mark.parametrize(
    "path", sorted(FRONTEND.rglob("*.js")), ids=lambda p: p.name
)
def test_no_button_uses_a_colour_modifier_without_the_base_class(path):
    offenders = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for match in CLASS_PROP.finditer(line):
            classes = match.group("value").split()
            if any(c in COLOUR_ONLY for c in classes) and "btn" not in classes:
                offenders.append(f"{path.name}:{number} class=\"{match.group('value')}\"")

    assert not offenders, (
        "these controls use a colour modifier with no base `btn`, so they render "
        "unpadded and square:\n  " + "\n  ".join(offenders)
    )


def test_dynamic_class_assignments_keep_the_base_class():
    """Template-literal className writes bypass the check above."""
    offenders = []
    pattern = re.compile(r"className\s*=\s*`([^`]*)`")
    for path in sorted(FRONTEND.rglob("*.js")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in pattern.finditer(line):
                template = match.group(1)
                if any(m in template for m in COLOUR_ONLY):
                    # The literal part must contain a standalone `btn` token.
                    literal = re.sub(r"\$\{[^}]*\}", " ", template)
                    if "btn" not in literal.split():
                        offenders.append(f"{path.name}:{number} `{template.strip()}`")

    assert not offenders, (
        "these dynamic className writes drop the base `btn`:\n  "
        + "\n  ".join(offenders)
    )
