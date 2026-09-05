#!/usr/bin/env python3
"""بوابة الجاهزية التقنية لـ DOU OS.

الجاهزية مش «الكود خلص» — هي «إيه اللي بيحصل لما حاجة تغلط».
السكربت ده بيقيس تمن شروط، كل واحد بنعم/لأ ودليله، عشان تعرف إنت فين
من غير ما تسأل حد.

    python tools/readiness_gate.py
    python tools/readiness_gate.py --url https://dou.delivery
    python tools/readiness_gate.py --fast     # من غير تشغيل الاختبارات

الخروج بصفر لما كل الشروط الآلية تعدي. الشرطين اللي محتاجين سيرفر أو
بني آدم بيتقالوا بصراحة إنهم كده، وما بيتحسبوش نجاح.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PASS, FAIL, WARN, MANUAL = "PASS", "FAIL", "WARN", "MANUAL"
MARK = {PASS: "✓", FAIL: "✗", WARN: "⚠", MANUAL: "◐"}


@dataclass
class Check:
    number: str
    name: str
    status: str
    evidence: str
    detail: str = ""


def _run(cmd: list[str], cwd: Path = ROOT, timeout: int = 600) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, str(e)


def _get_json(url: str, timeout: int = 15) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return None


# ─── ١ · النسخ الاحتياطية ─────────────────────────────────────────────────────

def check_backups(url: str | None) -> Check:
    """نسخة موجودة، حديثة، وخرجت من الجهاز.

    «استرجعت وطابقت» مش بيتقاس من هنا — لازم يتشغّل على السيرفر نفسه.
    خطواته في docs/PRODUCTION_RUNBOOK.md قسم ٤.
    """
    if not url:
        return Check("١", "النسخ الاحتياطية", MANUAL,
                     "محتاج --url", "شغّله على السيرفر عشان تتأكد من الاسترجاع كمان")

    data = _get_json(f"{url}/admin/system-status")
    if not data:
        return Check("١", "النسخ الاحتياطية", MANUAL,
                     "الحالة محمية بتوكن أدمن",
                     "شغّل الفحص من داخل السيرفر أو مرّر X-Admin-Key")

    b = data.get("backup_details") or {}
    if not b:
        return Check("١", "النسخ الاحتياطية", FAIL,
                     "system-status مش بيرجّع backup_details")

    offsite = bool(b.get("is_offsite"))
    age = b.get("age_hours")
    fresh = isinstance(age, (int, float)) and age < 26

    if offsite and fresh:
        return Check("١", "النسخ الاحتياطية", PASS,
                     f"آخر نسخة من {age:.0f} ساعة · {b.get('storage_destination')}",
                     "فاضل تتأكد إنك استرجعت واحدة فعلًا وطابقت الأرقام")
    return Check("١", "النسخ الاحتياطية", FAIL,
                 f"{b.get('status')} · offsite={offsite} · عمرها={age}",
                 "الجهاز يروح = كل حاجة تروح")


# ─── ٢ · CI ───────────────────────────────────────────────────────────────────

def check_ci() -> Check:
    """الكود المكسور ما يوصلش الإنتاج."""
    wf_dir = ROOT / ".github" / "workflows"
    files = list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml")) if wf_dir.exists() else []
    if not files:
        return Check("٢", "CI", FAIL, "مفيش .github/workflows",
                     "لينت مكسور وصل الإنتاج مرتين قبل كده")

    text = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in files)
    runs_tests = "pytest" in text
    runs_lint = "ruff" in text
    if runs_tests and runs_lint:
        return Check("٢", "CI", PASS,
                     f"{len(files)} workflow · بيشغّل pytest و ruff")
    missing = [n for n, ok in (("pytest", runs_tests), ("ruff", runs_lint)) if not ok]
    return Check("٢", "CI", FAIL, f"موجود بس مش بيشغّل: {' و '.join(missing)}")


# ─── ٣ · تعرف إيه الشغال ──────────────────────────────────────────────────────

def check_deploy_drift(url: str | None) -> Check:
    """الكوميت المنشور = المحلي، ومفيش شغل على الرف."""
    _, head = _run(["git", "rev-parse", "--short", "HEAD"])
    head = head.strip()
    _, dirty = _run(["git", "status", "--porcelain"])
    uncommitted = len([ln for ln in dirty.splitlines() if ln.strip()])

    deployed = None
    if url:
        h = _get_json(f"{url}/health") or {}
        deployed = h.get("commit") or h.get("revision") or h.get("git_sha")
        version = h.get("version")
    else:
        version = None

    problems = []
    if uncommitted:
        problems.append(f"{uncommitted} ملف غير مرفوع")
    if url and not deployed:
        problems.append(f"/health ما بيرجّعش الكوميت (بيرجّع version={version})")
    elif deployed and not deployed.startswith(head[:7]):
        problems.append(f"المنشور {deployed} · المحلي {head}")

    if problems:
        return Check("٣", "تعرف إيه الشغال", FAIL, " · ".join(problems),
                     "لما حاجة تقع، أول سؤال هو «إيه الشغال؟»")
    return Check("٣", "تعرف إيه الشغال", PASS, f"المنشور = المحلي = {head} · الشجرة نضيفة")


# ─── ٤ · العطل بيوصلك ─────────────────────────────────────────────────────────

def check_error_reporting(url: str | None) -> Check:
    """لو الرواتب رمت استثناء، حد يعرف قبل العميل."""
    if url:
        h = _get_json(f"{url}/health") or {}
        flag = h.get("error_reporting")
        if flag in ("on", True, "enabled"):
            return Check("٤", "العطل بيوصلك", PASS, "error_reporting: on",
                         "فاضل ترمي خطأ متعمّد وتتأكد إنه وصل فعلًا")
        if flag is not None:
            return Check("٤", "العطل بيوصلك", FAIL, f"error_reporting: {flag}")

    src = (ROOT / "app" / "services" / "observability.py")
    wired = src.exists() and "sentry" in src.read_text(encoding="utf-8").lower()
    return Check("٤", "العطل بيوصلك", WARN,
                 "الكود جاهز، والتفعيل غير مقيس" if wired else "مفيش تتبّع أخطاء",
                 "خلّي /health يرجّع error_reporting عشان يتقاس بدل ما يتخمّن")


# ─── ٥ · الفلوس صح من الأول للآخر ─────────────────────────────────────────────

MONEY_TESTS = [
    "tests/test_flex_month_end_to_end.py",
    "tests/test_payroll_golden.py",
    "tests/test_payroll_tenant_isolation.py",
]


def check_money(fast: bool) -> Check:
    if fast:
        return Check("٥", "الفلوس", MANUAL, "--fast شغّال، الاختبارات ما اتشغلتش")

    present = [t for t in MONEY_TESTS if (ROOT / t).exists()]
    if not present:
        return Check("٥", "الفلوس", FAIL, "ملفات اختبارات الفلوس مش موجودة")

    code, out = _run(
        [".venv/bin/python", "-m", "pytest", *present, "-q"], timeout=900
    )
    m = re.search(r"(\d+) passed", out)
    f = re.search(r"(\d+) failed", out)
    passed = m.group(1) if m else "?"
    if code == 0 and not f:
        return Check("٥", "الفلوس", PASS, f"{passed} اختبار · شهر مطعم ورواتب متصالحين",
                     "ملف WPS: البنك بيقبله ولا لأ — ده مش بيتقاس من هنا")
    return Check("٥", "الفلوس", FAIL,
                 f"{f.group(1) if f else '؟'} ساقط من {passed}",
                 out.strip().splitlines()[-1] if out.strip() else "")


# ─── ٦ · عميل يشتغل من غيرك ───────────────────────────────────────────────────

ONBOARDING_STEPS = [
    ("POST", "/admin/tenants", "إنشاء الشركة"),
    ("GET", "/admin/plans", "اختيار الباقة"),
    ("PATCH", "/admin/tenants/{}", "ضبط الفوترة والاستحقاق"),
    ("POST", "/admin/tenants/{}/payments", "تسجيل أول دفعة"),
    ("POST", "/fleet/couriers", "أول مندوب"),
    ("GET", "/hr/payroll", "أول مسير"),
    ("GET", "/hr/payroll/wps-export", "ملف البنك"),
]


def check_onboarding_surface() -> Check:
    """بيثبت إن الدورة *ممكنة* من الكونسول — مش إنها *مستخدَمة*.

    الفرق بينهم إن حد تاني يعملها من غير ما يسألك، وده اختبار بني آدم.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from app.main import app  # noqa: PLC0415
        paths = {re.sub(r"\{[^}]*\}", "{}", p) for p in app.openapi().get("paths", {})}
    except Exception as e:  # pragma: no cover - بيئة ناقصة
        return Check("٦", "عميل يشتغل من غيرك", MANUAL, f"تعذّر قراءة المسارات: {e}")

    missing = [label for _, path, label in ONBOARDING_STEPS if path not in paths]
    if missing:
        return Check("٦", "عميل يشتغل من غيرك", FAIL,
                     "خطوات مالهاش نقطة: " + " · ".join(missing))
    return Check("٦", "عميل يشتغل من غيرك", MANUAL,
                 "كل الخطوات ليها نقطة",
                 "القياس الوحيد: اقفل الترمينال أسبوع وخلّي حد تاني يشغّل عميل")


# ─── ٧ · كل حد مدفوع بيتفرض ───────────────────────────────────────────────────

def check_paid_boundaries() -> Check:
    """السقف والإيقاف والقدرات — اللي بتبيعه لازم يتفرض."""
    problems = []

    # السقف: الملف اللي بيخلق مندوب لازم يفحص السقف — سواء بنفسه أو بمناداة
    # الدالة المشتركة enforce_courier_plan_cap.
    creators = {
        "app/services/rider_management.py": True,
        "app/routers/couriers.py": False,
    }
    for rel, _ in creators.items():
        src = ROOT / rel
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8")
        enforces = "max_couriers" in text or "enforce_courier_plan_cap" in text
        if "Courier(" in text and not enforces:
            problems.append(f"{Path(rel).name} بيخلق مندوب بلا فحص سقف")

    # الإيقاف: العد القديم كان بيدوّر على نص "check_active" جوّه ملفات الراوتر،
    # فكان بيقرأ ٢ من ١٦٤ ويقول إن الإيقاف شبه غير مفروض. ده قياس غلط: الفحص
    # مش عايش في الراوترات، عايش في get_current_user اللي كل نقطة مصدَّقة
    # بتعتمد عليه — يعني التغطية بتاعته هي كل النقاط المصدَّقة مرة واحدة.
    # اللي يستاهل القياس بقى: هل الفحص المركزي ده لسه موجود، وهل كل نقطة في
    # الراوترات التشغيلية فعلاً بتعدّي منه.
    auth_src = ROOT / "app" / "routers" / "auth.py"
    central = False
    if auth_src.exists():
        text = auth_src.read_text(encoding="utf-8")
        m = re.search(r"def get_current_user\(.*?\n    return user", text, re.S)
        central = bool(m and "check_active" in m.group(0))
    if not central:
        problems.append("get_current_user مش بينادي check_active — الإيقاف بقى بلا فرض مركزي")
    else:
        unguarded = 0
        for rel in ("fleet", "hr", "couriers", "shifts", "payroll", "salary"):
            src = ROOT / "app" / "routers" / f"{rel}.py"
            if not src.exists():
                continue
            text = src.read_text(encoding="utf-8")
            ops = text.count("@router.")
            # نقطة بتعتمد get_current_user (مباشرة أو عبر dependencies على الراوتر)
            # بتعدّي على الفحص المركزي.
            covered = text.count("Depends(get_current_user)")
            if "dependencies=[Depends(" in text and "get_current_user" in text:
                covered = max(covered, ops)
            if covered < ops:
                unguarded += ops - covered
        if unguarded:
            problems.append(f"{unguarded} نقطة تشغيلية من غير مصادقة تعدّي الإيقاف")

    if problems:
        return Check("٧", "الحدود المدفوعة", FAIL, " · ".join(problems),
                     "التدرّج اللي بتبيعه ديكور لو مش متفرض على كل مسار")
    return Check("٧", "الحدود المدفوعة", PASS, "السقف والإيقاف مفروضين")


# ─── ٨ · مفيش شاشة بتكدب ──────────────────────────────────────────────────────

FABRICATED = re.compile(r"api[.(][a-z]*\([^)]*\)\.catch\(\(\) ?=> ?(\[\]|\{|null)")


def check_honesty() -> Check:
    """رد مختلق وقت الفشل، وحقل حالة بيدّعي بدل ما يقيس."""
    fabricated = 0
    for base in ("frontend-v2", "static"):
        d = ROOT / base
        if not d.exists():
            continue
        for f in list(d.rglob("*.js")) + list(d.rglob("*.html")):
            if "node_modules" in str(f):
                continue
            fabricated += len(FABRICATED.findall(f.read_text(encoding="utf-8", errors="ignore")))

    constants = []
    admin = ROOT / "app" / "routers" / "admin.py"
    if admin.exists():
        block = admin.read_text(encoding="utf-8")
        m = re.search(r'def system_status\(.*?\n    \}', block, re.S)
        if m:
            for line in m.group(0).splitlines():
                hit = re.match(r'\s*"(\w+)":\s*"[A-Z_]+"\s*,?\s*$', line)
                # `"ONLINE" if database_ok else "ERROR"` is measured; only a bare
                # literal with nothing deciding it is a claim rather than a check.
                if hit:
                    constants.append(hit.group(1))

    problems = []
    if fabricated:
        problems.append(f"{fabricated} رد مختلق وقت الفشل")
    if constants:
        problems.append("حقول حالة ثابتة: " + " · ".join(constants))

    if problems:
        return Check("٨", "مفيش شاشة بتكدب", WARN if not fabricated else FAIL,
                     " · ".join(problems),
                     "الحقل اللي بيطمّن من غير ما يقيس أسوأ من غيابه")
    return Check("٨", "مفيش شاشة بتكدب", PASS, "كل حقل بيقيس · صفر رد مختلق")


# ─── التقرير ──────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="بوابة الجاهزية التقنية لـ DOU OS")
    ap.add_argument("--url", help="عنوان الإنتاج، مثال https://dou.delivery")
    ap.add_argument("--fast", action="store_true", help="من غير تشغيل الاختبارات")
    args = ap.parse_args()

    checks = [
        check_backups(args.url),
        check_ci(),
        check_deploy_drift(args.url),
        check_error_reporting(args.url),
        check_money(args.fast),
        check_onboarding_surface(),
        check_paid_boundaries(),
        check_honesty(),
    ]
    checks.sort(key=lambda c: c.number)

    print()
    print("  DOU OS · بوابة الجاهزية التقنية")
    print("  " + "─" * 62)
    for c in checks:
        print(f"  {MARK[c.status]} {c.number}  {c.name}")
        print(f"       {c.evidence}")
        if c.detail:
            print(f"       ↳ {c.detail}")
    print("  " + "─" * 62)

    auto = [c for c in checks if c.status in (PASS, FAIL, WARN)]
    passed = [c for c in auto if c.status == PASS]
    manual = [c for c in checks if c.status == MANUAL]

    print(f"  عدّى {len(passed)} من {len(auto)} آلي" +
          (f"   ·   {len(manual)} محتاج سيرفر أو بني آدم" if manual else ""))
    if manual:
        print("  " + " · ".join(c.name for c in manual))
    print()

    return 0 if len(passed) == len(auto) else 1


if __name__ == "__main__":
    raise SystemExit(main())
