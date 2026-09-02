"""Catch identifiers a module uses but never defines.

Driver 360 was completely broken in production: `renderTabs` read a `TABS`
constant that was declared inside a different function, so every visit threw
`ReferenceError: TABS is not defined`. The throw happened inside a try block,
so the screen rendered "تعذر تحميل السائقين" and the real cause was invisible.

Nothing caught it. `node --check` only parses, so scope errors pass. The E2E
suite never opens Driver 360. The screen was broken for anyone who clicked a
rider, and every test was green.

This walks each module's top-level identifiers and flags a capitalised
constant-style name that is used but never declared or imported anywhere in the
file — the shape of the bug above, without needing a full JS engine.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend-v2"

# Browser and language globals a module may legitimately use without declaring.
KNOWN_GLOBALS = {
    "Array", "Boolean", "Date", "Error", "Intl", "JSON", "Map", "Math",
    "Number", "Object", "Promise", "RegExp", "Set", "String", "Symbol",
    "URL", "URLSearchParams", "WeakMap", "FormData", "Blob", "File",
    "FileReader", "Image", "Audio", "Notification", "AbortController",
    "CustomEvent", "Event", "MutationObserver", "IntersectionObserver",
    "TextDecoder", "TextEncoder", "DOMParser", "Response", "Request",
    "Headers", "Infinity", "NaN",
}

DECLARATION = re.compile(
    r"\b(?:const|let|var|function|class)\s+([A-Z][A-Z0-9_]*|[A-Z][A-Za-z0-9_]*)\b"
)
IMPORTED = re.compile(r"import\s*\{([^}]*)\}|import\s+(\w+)\s+from")
# SCREAMING_CASE identifiers: the constant convention this bug lived in.
# The trailing lookahead skips object literal keys (`ADVANCE: {...}`), which are
# declarations of a property rather than references to a binding. Without it the
# check fires on every status map in the codebase, and a guard that cries wolf
# gets muted.
USAGE = re.compile(r"(?<![.\w$'\"`])([A-Z][A-Z0-9_]{2,})\b(?!\s*:)")


def _strip_noise(source: str) -> str:
    """Remove comments and string literals so their contents are not read as code."""
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    source = re.sub(r"(?m)//.*$", " ", source)
    source = re.sub(r"`(?:\\.|[^`\\])*`", "``", source)
    source = re.sub(r"'(?:\\.|[^'\\])*'", "''", source)
    source = re.sub(r'"(?:\\.|[^"\\])*"', '""', source)
    return source


@pytest.mark.parametrize("path", sorted(FRONTEND.rglob("*.js")), ids=lambda p: p.name)
def test_module_declares_every_constant_it_uses(path):
    source = _strip_noise(path.read_text(encoding="utf-8"))

    declared = set(DECLARATION.findall(source))
    for braced, default in IMPORTED.findall(source):
        if braced:
            for name in braced.split(","):
                cleaned = name.split(" as ")[-1].strip()
                if cleaned:
                    declared.add(cleaned)
        if default:
            declared.add(default)

    used = set(USAGE.findall(source))
    missing = sorted(used - declared - KNOWN_GLOBALS)

    assert not missing, (
        f"{path.name} uses {missing} but never declares or imports them at module "
        "scope. A constant declared inside one function and read from another "
        "throws ReferenceError at runtime, which is how Driver 360 broke."
    )
