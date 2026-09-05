"""One place decides what language the interface is in.

The views ask `getLang() === 'ar'`. The shared components used to ask
`localStorage.getItem('dou_lang') !== 'en'` instead. Those two agree on Arabic
and on English and disagree on everything else — and the rider app ships Urdu
and Hindi and writes the same storage key. A rider who picked Hindi on a shared
company phone put the fleet console into a state where the page body rendered
English and the shared chips inside it rendered Arabic, on the same screen.

Seen in the browser as `5 حالات` sitting under "Top Priority Actions Now".
"""

import re
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1] / "frontend-v2" / "shared"
FLEET = Path(__file__).resolve().parents[1] / "frontend-v2" / "fleet"

# The one function allowed to read the stored language.
AUTHORITY = SHARED / "i18n" / "i18n.js"


def _js_files():
    for root in (SHARED, FLEET):
        for path in root.rglob("*.js"):
            if path != AUTHORITY:
                yield path


def test_only_i18n_reads_the_language_storage_key():
    direct = re.compile(r"""localStorage\.getItem\(\s*['"]dou_lang['"]""")
    offenders = [
        str(p.relative_to(SHARED.parent))
        for p in _js_files()
        if direct.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "these read the language key directly instead of calling getLang(), "
        "which is how one screen ends up rendering two languages: " + ", ".join(offenders)
    )


def test_no_component_decides_arabic_by_ruling_out_english():
    """`!== 'en'` calls Urdu and Hindi Arabic. Only `=== 'ar'` is Arabic."""
    ruling_out = re.compile(r"""!==\s*['"]en['"]""")
    offenders = [
        str(p.relative_to(SHARED.parent))
        for p in _js_files()
        if ruling_out.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "'not English' is not the same as 'Arabic' — the rider app ships ur and "
        "hi: " + ", ".join(offenders)
    )


def test_the_authority_still_offers_getlang():
    source = AUTHORITY.read_text(encoding="utf-8")
    assert "export function getLang()" in source, (
        "the guards above are only meaningful while getLang is what callers use"
    )
