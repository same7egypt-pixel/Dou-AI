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


# ─────────────────────────────────────────────────────────────────────────────
# The driver app carries its own dictionary, in four languages
# ─────────────────────────────────────────────────────────────────────────────

COURIER = ROOT / "static" / "courier.html"
DRIVER_LANGUAGES = ("ar", "en", "ur", "hi")


def _copy_tables() -> dict[str, dict[str, str]]:
    """Parse the COPY object out of courier.html."""
    source = COURIER.read_text(encoding="utf-8")
    start = source.index("{", source.index("const COPY"))
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    block = source[start:end]

    tables: dict[str, dict[str, str]] = {}
    for lang in DRIVER_LANGUAGES:
        match = re.search(rf"\b{lang}\s*:\s*{{", block)
        assert match, f"COPY has no {lang} table"
        inner_start = match.end() - 1
        depth = 0
        for index in range(inner_start, len(block)):
            if block[index] == "{":
                depth += 1
            elif block[index] == "}":
                depth -= 1
                if depth == 0:
                    inner_end = index + 1
                    break
        body = block[inner_start:inner_end]
        tables[lang] = {
            m.group(1): m.group(2)[1:-1]
            for m in re.finditer(
                r"(?:^|[{,]\s*)([A-Za-z_]\w*)\s*:\s*"
                r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')",
                body,
            )
        }
    return tables


def _driver_script_after_copy() -> str:
    source = COURIER.read_text(encoding="utf-8")
    start = source.index("{", source.index("const COPY"))
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[index + 1 :]
    raise AssertionError("COPY block never closes")


def test_all_four_driver_languages_are_complete():
    """Urdu and Hindi were missing 50 of 133 keys.

    t() falls back to Arabic on a miss, so a Pakistani or Indian rider read more
    than a third of the app in a script they may not read at all — and nothing
    reported it, because falling back is not an error.
    """
    tables = _copy_tables()
    arabic = set(tables["ar"])
    assert len(arabic) > 200, f"COPY.ar looks truncated: {len(arabic)} keys"
    for lang in ("en", "ur", "hi"):
        missing = sorted(arabic - set(tables[lang]))
        assert not missing, (
            f"COPY.{lang} is missing {len(missing)} keys, which silently fall "
            f"back to Arabic: {missing[:10]}"
        )


def test_every_driver_key_used_is_defined():
    """t('notAvailable') printed the literal string "notAvailable" on screen."""
    tables = _copy_tables()
    used = set(re.findall(r"\bt\(\s*['\"]([A-Za-z_]\w*)['\"]\s*\)", _driver_script_after_copy()))
    undefined = sorted(used - set(tables["ar"]))
    assert not undefined, (
        "these keys are passed to t() but defined nowhere, so the key name "
        f"itself is rendered to the rider: {undefined}"
    )


def test_no_arabic_is_rendered_outside_the_driver_dictionary():
    """73 strings bypassed COPY, so they stayed Arabic in all four languages."""
    script = _driver_script_after_copy()
    runs = {m.group(0) for m in re.finditer(r"[؀-ۿ]+", script)}
    # The language picker names each language in its own script, on purpose.
    runs -= {"العربية", "اردو"}
    assert not runs, (
        "these Arabic strings are rendered without going through t(), so they "
        f"appear untranslated in English, Urdu and Hindi: {sorted(runs)[:10]}"
    )
