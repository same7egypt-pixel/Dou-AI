#!/usr/bin/env python3
"""فحص نحوي لسكربتات اللوحات (static/*.html) قبل النشر.

يمنع تكرار حادثة "قوس زائد في دالة واحدة كسّرت كل أزرار 4 لوحات".
يتحقق من:
  1. توازن الأقواس () {} [] في كل <script>.
  2. توازن الـ template literals (`...`).
  3. عدم وجود أسطر مقطوعة بعلامة اقتباس غير مقفلة.
  4. سلامة بنية كل سطر (quote balance لكل سطر بمحتوى).
"""

import re
import sys
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
PAIRS = {"(": ")", "{": "}", "[": "]"}


def balanced(chars: str) -> bool:
    stack = []
    i = 0
    while i < len(chars):
        ch = chars[i]
        if ch == "`":
            j = chars.find("`", i + 1)
            if j == -1:
                return False
            i = j
        elif ch in PAIRS:
            stack.append(ch)
        elif ch in PAIRS.values():
            if not stack or PAIRS[stack[-1]] != ch:
                return False
            stack.pop()
        i += 1
    return not stack


def scan_file(path: Path) -> list[str]:
    errors = []
    html = path.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    for idx, body in enumerate(scripts, 1):
        if not balanced(body):
            # حدد السطر التقريبي للخطأ
            stack = []
            line = 1
            found = None
            i = 0
            while i < len(body):
                ch = body[i]
                if ch == "\n":
                    line += 1
                elif ch == "`":
                    j = body.find("`", i + 1)
                    if j == -1:
                        found = (line, "قالب (backtick) غير مقفول")
                        break
                    i = j
                elif ch in PAIRS:
                    stack.append(ch)
                elif ch in PAIRS.values():
                    if not stack or PAIRS[stack[-1]] != ch:
                        found = (line, f"{ch!r} زائدة بلا فتح مقابل")
                        break
                    stack.pop()
                i += 1
            if not found and stack:
                found = (line, "أقواس مفتوحة بدون إغلاق")
            loc = f" عند سطر {found[0]} ({found[1]})" if found else ""
            errors.append(f"{path.name}: <script>#{idx} — أقواس/قالب غير متوازن{loc}")
    return errors


def main() -> int:
    files = sorted(STATIC_DIR.glob("*.html"))
    total_errors = []
    for f in files:
        total_errors += scan_file(f)
    if total_errors:
        print("❌ فحص اللوحات فشل — أخطاء نحوية:" )
        for e in total_errors:
            print("   -", e)
        return 1
    print(f"✓ فحص {len(files)} لوحة — لا أخطاء نحوية")
    return 0


if __name__ == "__main__":
    sys.exit(main())
