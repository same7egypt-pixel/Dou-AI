"""Every third-party package the app imports must be declared in requirements.

This defect appeared three separate times: ``redis`` (caching and the login
throttle), ``boto3`` (S3 document storage and backup upload), and ``sentry-sdk``
(error reporting) were all imported inside ``try``/``except`` blocks and none of
them were installed. Each failure was silent — the feature just never worked in
production, with no error anywhere.
"""

import re
from pathlib import Path

import tomllib  # noqa: F401 - stdlib probe, see _stdlib_modules

ROOT = Path(__file__).resolve().parents[1]

# Import name -> distribution name, where they differ.
DISTRIBUTION_NAMES = {
    "jwt": "pyjwt",
    "dotenv": "python-dotenv",
    "sqlalchemy": "sqlalchemy",
    "sentry_sdk": "sentry-sdk",
    "psycopg2": "psycopg2-binary",
}

# Imported by the app but supplied by another package or the standard library.
NOT_DIRECT_DEPENDENCIES = {
    "app",
    "alembic",
    "pydantic",
    "starlette",
}


def _declared() -> set[str]:
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    names = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # "sentry-sdk[fastapi]==2.19.2" -> "sentry-sdk"
        name = re.split(r"[<>=\[;]", line)[0].strip().lower()
        if name:
            names.add(name)
    return names


def _third_party_imports() -> set[str]:
    """Top-level import names found in app/, excluding stdlib and local modules."""
    import ast
    import sys

    stdlib = set(sys.stdlib_module_names)
    found = set()
    # Parsed, not pattern-matched. A regex for "^from X" also matches prose
    # inside a docstring — a sentence beginning "from DOU. This entity is..."
    # was read as an import of a package named DOU, and this guard failed the
    # whole suite over an English sentence. The syntax tree only contains real
    # imports.
    for path in (ROOT / "app").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # A relative import is local by definition.
                names = [node.module] if node.module and node.level == 0 else []
            else:
                continue
            for name in names:
                module = name.split(".")[0]
                if module in stdlib or module.startswith("_"):
                    continue
                found.add(module)
    return found - NOT_DIRECT_DEPENDENCIES


def test_every_imported_package_is_declared():
    declared = _declared()
    missing = sorted(
        module
        for module in _third_party_imports()
        if DISTRIBUTION_NAMES.get(module, module).lower() not in declared
    )
    assert missing == [], (
        "app/ imports these packages but requirements.txt does not declare them, "
        "so the features using them fail silently in production: "
        f"{missing}"
    )


def test_optional_runtime_packages_are_declared():
    """Named explicitly because these three were each missing at some point."""
    declared = _declared()
    for distribution in ("redis", "boto3", "sentry-sdk"):
        assert distribution in declared, f"{distribution} is missing from requirements"
