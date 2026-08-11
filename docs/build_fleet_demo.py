#!/usr/bin/env python3
"""يبني نسخة Fleet-Only — لمنتج الاشتراكات B2B:
   dou-fleet.html (عربي) و dou-fleet-en.html (إنجليزي)
   = لاندنج تسويقي + أسعار اشتراكات + واجهتان تفاعليتان:
     Fleet Partners (لوحة الشركة اللوجستية) + Courier App (تطبيق السواقين)
   مكتفية ذاتياً — بدون سيرفر أو إنترنت."""
import re, pathlib

STATIC = pathlib.Path("/Users/sameh/Documents/Default Project/dou-server/static")

PAGES_AR = [
    ("fleet", "📊", "لوحة Fleet Partners",
     "إدارة الأسطول والشركات، الإرسال والتحكم، الورديات والحضور، الرواتب والعقود، التذاكر والقنوات — كل شيء في لوحة واحدة"),
    ("courier", "🛵", "تطبيق السواقين",
     "استقبال المهام، الحضور والورديات، التتبع الحي، الأرباح والحوافز — يعمل على أي موبايل"),
]
PAGES_EN = [
    ("fleet", "📊", "Fleet Partners Console",
     "Fleet & company management, dispatch control, shifts & attendance, payouts & contracts, tickets and channels — all in one console"),
    ("courier", "🛵", "Courier App",
     "Accept tasks, clock in/out, live tracking, earnings and incentives — works on any phone"),
]

SUFFIX = {"ar": "", "en": "-en"}
MOCK_SUFFIX = {"ar": "", "en": "-en"}


def inject_mock(html, mock):
    script = "<script>" + mock + "</script>\n"
    m = re.search(r"<body[^>]*>", html)
    if m:
        html = html[:m.end()] + "\n" + script + html[m.end():]
    else:
        html = html.replace("</head>", script + "</head>")
    return html


def pricing_block(lang):
    if lang == "ar":
        return '''<div class="pricing" id="pricing">
  <div class="pHead"><h2>أسعار بسيطة تبدأ فوراً</h2><p>اشتراك شهري لكل شركة — تجربة مجانية 14 يوماً بدون بطاقة. قابلة للتوسع حسب عدد السائقين.</p></div>
  <div class="plans">
    <div class="plan">
      <div class="pl"><b>Starter</b><small>حتى 10 سائقين</small></div>
      <div class="price">1,500 <span>ر.س/شهر</span></div>
      <ul><li>لوحة Fleet Partners كاملة</li><li>تطبيق السواقين غير محدود</li><li>تتبع حي مباشر</li><li>تذاكر ودعم بالواتساب</li></ul>
      <button class="cta" onclick="alert('اطلب عرض السعر (UI)')">ابدأ التجربة ←</button>
    </div>
    <div class="plan hot">
      <div class="pl"><b>Business</b><small>حتى 50 سائقاً</small><span class="best">الأكثر طلباً</span></div>
      <div class="price">3,500 <span>ر.س/شهر</span></div>
      <ul><li>كل ميزات Starter</li><li>إرسال ذكي وإسناد تلقائي</li><li>رواتب وحوافز ومرتبات</li><li>تقارير أداء وامتثال</li><li>مدير حساب مخصص</li></ul>
      <button class="cta" onclick="alert('اطلب عرض السعر (UI)')">ابدأ التجربة ←</button>
    </div>
    <div class="plan">
      <div class="pl"><b>Enterprise</b><small>سائقون غير محدودين</small></div>
      <div class="price">عرض خاص</div>
      <ul><li>كل ميزات Business</li><li>تكامل API مع أنظمتك</li><li>عقود مخصصة وشروط دفع</li><li>على-premises أو سحابة خاصة</li></ul>
      <button class="cta" onclick="alert('تواصل معنا (UI)')">تواصل مع المبيعات</button>
    </div>
  </div>
  <div class="trust"><span>✓ بدون عقود طويلة</span><span>✓ إعداد خلال يوم</span><span>✓ دعم عربي مباشر</span><span>✓ بياناتك آمنة ومشفرة</span></div>
</div>'''
    return '''<div class="pricing" id="pricing">
  <div class="pHead"><h2>Simple pricing, launch today</h2><p>Monthly subscription per company — 14-day free trial, no card required. Scales with your fleet size.</p></div>
  <div class="plans">
    <div class="plan">
      <div class="pl"><b>Starter</b><small>Up to 10 drivers</small></div>
      <div class="price">$400 <span>/month</span></div>
      <ul><li>Full Fleet Partners console</li><li>Unlimited Courier App</li><li>Live tracking</li><li>Tickets & WhatsApp support</li></ul>
      <button class="cta" onclick="alert('Request quote (UI)')">Start free trial →</button>
    </div>
    <div class="plan hot">
      <div class="pl"><b>Business</b><small>Up to 50 drivers</small><span class="best">Most popular</span></div>
      <div class="price">$930 <span>/month</span></div>
      <ul><li>Everything in Starter</li><li>Smart dispatch & auto-assign</li><li>Payouts, incentives & payroll</li><li>Performance & compliance reports</li><li>Dedicated account manager</li></ul>
      <button class="cta" onclick="alert('Request quote (UI)')">Start free trial →</button>
    </div>
    <div class="plan">
      <div class="pl"><b>Enterprise</b><small>Unlimited drivers</small></div>
      <div class="price">Custom</div>
      <ul><li>Everything in Business</li><li>API integration with your systems</li><li>Custom contracts & terms</li><li>On-premises or private cloud</li></ul>
      <button class="cta" onclick="alert('Contact us (UI)')">Talk to sales</button>
    </div>
  </div>
  <div class="trust"><span>✓ No long contracts</span><span>✓ Setup in a day</span><span>✓ Local support</span><span>✓ Secure & encrypted</span></div>
</div>'''


def hero_block(lang):
    if lang == "ar":
        return '''<div class="hero">
  <div class="logo">D<i></i>ou</div>
  <div class="logoFull">FLEET OPERATIONS PLATFORM</div>
  <div class="badge"><span>⚡</span> لشركات التوصيل واللوجستيات — اشتراك شهري يبدأ اليوم</div>
  <h1>سيطر على أسطولك بالكامل من لوحة واحدة</h1>
  <p>تابع سائقيك لحظياً، وزّع الشحنات بذكاء، احسب الرواتب والحوافز تلقائياً، وتأكد من الالتزام والامتثال — دون أوراق ولا تنسيق عبر الواتساب. جرّب الواجهتين وافتح التجربة:</p>
  <div class="heroCtas">
    <a href="#pricing" class="btn1">شاهد الأسعار</a>
    <a href="#" class="btn2" onclick="openDemo('fleet')">افتح التجربة ←</a>
  </div>
</div>'''
    return '''<div class="hero">
  <div class="logo">D<i></i>ou</div>
  <div class="logoFull">FLEET OPERATIONS PLATFORM</div>
  <div class="badge"><span>⚡</span> For delivery & logistics companies — monthly subscription, launch today</div>
  <h1>Run your entire fleet from one console</h1>
  <p>Track your drivers live, dispatch intelligently, auto-calculate payouts & incentives, and stay on top of compliance — no spreadsheets, no WhatsApp chaos. Explore both interfaces and open the demo:</p>
  <div class="heroCtas">
    <a href="#pricing" class="btn1">See pricing</a>
    <a href="#" class="btn2" onclick="openDemo('fleet')">Open demo →</a>
  </div>
</div>'''


def title_attr(lang):
    return "DOU Fleet — Delivery Operations Platform" if lang == "en" else "دو فليت — منصة تشغيل الأساطيل"


def build(output, lang, PAGES, MOCK):
    go_text = "افتح التجربة ←" if lang == "ar" else "Open demo →"
    close_back = "العودة للواجهات" if lang == "ar" else "Back to interfaces"
    templates = []
    for name, icon, title, desc in PAGES:
        raw = (STATIC / f"{name}{SUFFIX[lang]}.html").read_text()
        injected = inject_mock(raw, MOCK)
        templates.append(f'<template id="tpl-{name}">\n{injected}\n</template>')

    landing_cards = "\n".join(
        f'''<button class="card" onclick="openDemo('{name}')">
      <div class="ic">{icon}</div>
      <div class="tx"><b>{title}</b><p>{desc}</p>
      <span class="go">{go_text}</span></div>
    </button>''' for name, icon, title, desc in PAGES
    )

    if lang == "ar":
        titles_js = 'const TITLES = {fleet:"لوحة Fleet Partners", courier:"تطبيق السواقين"};'
    else:
        titles_js = 'const TITLES = {fleet:"Fleet Partners Console", courier:"Courier App"};'

    hero = hero_block(lang)
    pricing = pricing_block(lang)

    html = f'''<!doctype html>
<html lang="{lang}" dir="{"rtl" if lang == "ar" else "ltr"}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title_attr(lang)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Alexandria:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{{--ink:#eef2f8;--muted:#93a3bd;--orange:#ff5a13;--orange2:#ff8a55;--nav:#0d1320;--card:#141c2c;--line:#202a3e;--green:#5be0a3;--blue:#7aa5ff}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(1200px 700px at 80% -10%,#1a2a44 0%,var(--nav) 55%);font-family:Alexandria,sans-serif;color:var(--ink);min-height:100vh}}
.hero{{max-width:1040px;margin:0 auto;padding:64px 26px 30px;text-align:center}}
.logo{{font-size:40px;font-weight:800;letter-spacing:-3px;direction:ltr}}.logo i{{display:inline-block;background:var(--orange);height:13px;width:34px;border-radius:8px;margin:0 3px 12px 0}}
.logoFull{{font-size:15px;color:var(--muted);letter-spacing:6px;direction:ltr;margin-top:8px;font-weight:600}}
.hero h1{{font-size:30px;margin:18px 0 8px}}.hero p{{color:var(--muted);font-size:14px;max-width:640px;margin:0 auto 26px;line-height:1.9}}
.badge{{display:inline-flex;align-items:center;gap:8px;background:#16203a;border:1px solid var(--line);border-radius:20px;padding:8px 16px;font-size:12px;color:var(--green);margin-bottom:22px}}
.heroCtas{{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}}
.btn1,.btn2{{text-decoration:none;font-size:13px;font-weight:700;padding:12px 22px;border-radius:12px}}
.btn1{{background:var(--orange);color:#fff}}.btn2{{background:var(--card);border:1px solid var(--line);color:var(--ink)}}
.langbar{{position:absolute;top:22px;left:24px;display:flex;gap:6px;background:#141c2c;border:1px solid var(--line);border-radius:12px;padding:5px}}
.langbar a{{color:var(--muted);font-size:12px;font-weight:700;text-decoration:none;padding:6px 14px;border-radius:8px}}
.langbar a.active{{background:var(--orange);color:#fff}}
.grid{{max-width:1040px;margin:0 auto;padding:0 26px 60px;display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px;text-align:{("right" if lang == "ar" else "left")};cursor:pointer;font-family:inherit;color:inherit;transition:.18s;display:flex;gap:16px;align-items:flex-start}}
.card:hover{{border-color:var(--orange);transform:translateY(-3px);box-shadow:0 18px 44px rgba(0,0,0,.35)}}
.card .ic{{font-size:30px;flex-shrink:0;width:56px;height:56px;border-radius:15px;background:linear-gradient(135deg,#1e2c48,#243d63);display:grid;place-items:center}}
.card .tx{{flex:1}}.card b{{font-size:16px;display:block;margin-bottom:5px}}
.card p{{color:var(--muted);font-size:12px;margin:0 0 12px;line-height:1.8;min-height:52px}}
.card .go{{color:var(--orange2);font-size:12px;font-weight:700}}
/* ===== Pricing ===== */
.pricing{{max-width:1040px;margin:0 auto;padding:20px 26px 60px}}
.pHead{{text-align:center;margin-bottom:30px}}
.pHead h2{{margin:0 0 6px;font-size:24px}}.pHead p{{color:var(--muted);font-size:13px;margin:0;line-height:1.8}}
.plans{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}}
.plan{{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:24px;display:flex;flex-direction:column;transition:.18s}}
.plan:hover{{transform:translateY(-3px);box-shadow:0 18px 44px rgba(0,0,0,.35)}}
.plan.hot{{border-color:var(--orange);background:linear-gradient(180deg,#1a2436,#141c2c);position:relative}}
.plan .pl{{display:flex;flex-direction:column;gap:3px}}
.plan .pl b{{font-size:17px}}.plan .pl small{{color:var(--muted);font-size:11px}}
.plan .best{{position:absolute;top:0;left:0;background:var(--orange);color:#fff;font-size:9.5px;font-weight:700;padding:4px 12px;border-radius:0 0 12px 0}}
.plan .price{{font-size:26px;font-weight:800;margin:16px 0 6px}}
.plan .price span{{font-size:12px;color:var(--muted);font-weight:600}}
.plan ul{{list-style:none;margin:0 0 18px;padding:0;display:flex;flex-direction:column;gap:8px}}
.plan li{{font-size:12.5px;color:var(--muted);padding-inline-start:22px;position:relative}}
.plan li:before{{content:"✓";position:absolute;inset-inline-start:0;color:var(--green);font-weight:800}}
.plan .cta{{margin-top:auto;background:var(--orange);color:#fff;border:0;border-radius:11px;padding:12px;font-family:inherit;font-size:13px;font-weight:700;cursor:pointer}}
.plan.hot .cta{{background:var(--orange)}}
.trust{{display:flex;justify-content:center;gap:18px;flex-wrap:wrap;margin-top:26px;color:var(--muted);font-size:12px}}
.trust span{{display:inline-flex;align-items:center;gap:6px}}
.trust span:before{{content:"✓";color:var(--green);font-weight:800}}
/* ===== Section titles ===== */
.secTitle{{max-width:1040px;margin:0 auto;padding:0 26px 16px;font-size:13px;color:var(--muted);letter-spacing:1px;font-weight:700}}
.foot{{text-align:center;color:#5b6b86;font-size:11px;padding:0 20px 40px;direction:ltr}}
#stage{{position:fixed;inset:0;background:var(--nav);display:none;z-index:20}}
#stage.open{{display:block}}
.appbar{{height:58px;background:var(--card);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:14px;padding:0 18px}}
.appbar .back{{background:none;border:0;color:var(--orange2);font-family:inherit;font-size:13px;font-weight:700;cursor:pointer;display:flex;gap:8px;align-items:center}}
.appbar .t{{font-size:13px;color:var(--muted)}}
.appbar .t b{{color:var(--ink)}}
#frame{{width:100%;height:calc(100% - 58px);border:0}}
</style>
</head>
<body>
<div class="langbar">
  <a href="dou-fleet.html" class="{"active" if lang == "ar" else ""}">العربية</a>
  <a href="dou-fleet-en.html" class="{"active" if lang == "en" else ""}">English</a>
</div>
{hero}

<div class="secTitle">الواجهات / Interfaces</div>
<div class="grid">
{landing_cards}
</div>

{hero and pricing}

<div class="foot">DOU Fleet Operations &copy; Sameh Saleh &middot; Confidential demo with simulated data &middot; dou.sa</div>

<div id="stage">
  <div class="appbar">
    <button class="back" onclick="closeDemo()">{"→" if lang == "ar" else "←"} <span>{close_back}</span></button>
    <div class="t">DOU / <b id="stageTitle"></b></div>
  </div>
  <iframe id="frame" title="DOU Demo"></iframe>
</div>

{"".join(templates)}

<script>
{titles_js}
let blobUrl = null;
function openDemo(name){{
  const tpl = document.getElementById('tpl-'+name);
  document.getElementById('stageTitle').textContent = TITLES[name];
  const pre = '<script>window.DOU_COUNTRY="SA";<\\/script>';
  const html = pre + tpl.innerHTML;
  if(blobUrl) URL.revokeObjectURL(blobUrl);
  blobUrl = URL.createObjectURL(new Blob([html], {{type:'text/html'}}));
  const frame = document.getElementById('frame');
  frame.src = blobUrl;
  document.getElementById('stage').classList.add('open');
  window.scrollTo(0,0);
}}
function closeDemo(){{
  document.getElementById('stage').classList.remove('open');
  document.getElementById('frame').src = "about:blank";
}}
</script>
</body>
</html>'''
    out = STATIC / output
    out.write_text(html)
    print(f"✅ Built {output} — {len(html)} bytes")


MOCK = (STATIC / "dou-demo-mock.js").read_text()
MOCK_EN = (STATIC / "dou-demo-mock-en.js").read_text()

build("dou-fleet.html", "ar", PAGES_AR, MOCK)
build("dou-fleet-en.html", "en", PAGES_EN, MOCK_EN)