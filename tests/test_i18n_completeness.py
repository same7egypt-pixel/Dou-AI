"""English mode must not leak Arabic interface text — and must not mangle data.

Two defects motivated this file.

The first: `translateNode()` existed in frontend-v2's i18n module and was never
called from anywhere, so the fleet dashboard rendered its Arabic source text
verbatim when the user picked English.

The second: `static/i18n.js` did call its translator, but replaced any
dictionary key found anywhere in a string. "لا" is a key, so "الاستحقاق" was
rendered "اNoستحقاق" and "صلاحيات" as "صNoحيات"; company and rider names came
out half-rewritten. Both engines now translate all-or-nothing: a string that
cannot be finished is left in Arabic, because leftover Arabic means the string
carries data rather than interface text.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "frontend-v2" / "shared" / "i18n" / "i18n.js"
LEGACY = ROOT / "static" / "i18n.js"
ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")


def test_translate_node_is_actually_wired_up():
    """A translator nobody calls is why English screens stayed Arabic."""
    for entry in ("fleet", "admin"):
        main = (ROOT / "frontend-v2" / entry / "main.js").read_text(encoding="utf-8")
        assert "startAutoTranslate" in main, (
            f"frontend-v2/{entry}/main.js never starts the auto-translator, so "
            "every Arabic string in its views survives into English mode"
        )


def test_module_translation_is_all_or_nothing():
    source = MODULE.read_text(encoding="utf-8")
    body = source[source.index("function translateText("):]
    body = body[: body.index("\nconst TRANSLATABLE_ATTRS")]
    assert "return value;" in body.rsplit("for (const", 1)[-1], (
        "translateText must fall back to the original string when the rules "
        "cannot remove every Arabic run — a partial rewrite corrupts data such "
        "as rider names and customer-named shifts"
    )


def test_legacy_translator_is_all_or_nothing():
    source = LEGACY.read_text(encoding="utf-8")
    convert = source[source.index("function convert(value)"):]
    convert = convert[: convert.index("\n  function translate(")]
    assert "return src;" in convert.rsplit("for(let i=0", 1)[-1], (
        "static/i18n.js must return the untouched string when it cannot "
        "translate all of it; the substring pass turned 'الاستحقاق' into "
        "'اNoستحقاق' on live admin screens"
    )


def test_short_arabic_keys_only_match_standing_alone():
    """The specific defect: a two-letter key eating the middle of a word."""
    for path in (MODULE, LEGACY):
        source = path.read_text(encoding="utf-8")
        assert "(?<![" in source, (
            f"{path.name} replaces short Arabic keys without a lookbehind, so a "
            "key like 'لا' will match inside longer words"
        )


def _dictionary_pairs(source: str, start: str, end: str):
    body = source.split(start, 1)[1].split(end, 1)[0]
    for match in re.finditer(r'"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"', body):
        yield match.group(1), match.group(2)
    for match in re.finditer(r"'((?:[^'\\]|\\.)*)'\s*:\s*'((?:[^'\\]|\\.)*)'", body):
        yield match.group(1), match.group(2)


def test_no_english_value_is_still_arabic():
    """An entry that maps Arabic to Arabic is a translation that never happened."""
    source = MODULE.read_text(encoding="utf-8")
    pairs = list(_dictionary_pairs(source, "const DICTIONARY = {", "\n};\n\n// Reverse mapping"))
    assert len(pairs) > 1000, f"dictionary looks truncated: {len(pairs)} entries"
    # The language switcher deliberately shows its own name in its own script.
    untranslated = [ar for ar, en in pairs if ARABIC.search(en) and ar != "العربية (AR)"]
    assert not untranslated, (
        "these dictionary entries map Arabic to Arabic, so the screen stays "
        f"Arabic in English mode: {untranslated[:10]}"
    )


def test_arabic_indic_digits_are_normalised():
    """toLocaleString('ar-SA') put "٤٩٩" on English screens."""
    for path in (MODULE, LEGACY):
        assert "westernDigits" in path.read_text(encoding="utf-8"), (
            f"{path.name} does not normalise Arabic-Indic digits, so numbers "
            "formatted with the ar-SA locale stay in Arabic numerals"
        )
