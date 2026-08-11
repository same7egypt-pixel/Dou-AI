#!/usr/bin/env python3
"""يبني dou-demo.html (AR) و dou-demo-en.html (EN) — ملفات مكتفية ذاتياً:
   صفحة هوية + landing + 5 واجهات معزولة + mock API. بدون أي سيرفر أو إنترنت."""
import re, pathlib

STATIC = pathlib.Path("/Users/sameh/Documents/Default Project/dou-server/static")

PAGES_AR = [
    ("merchant", "🏪", "لوحة التاجر", "إدارة الطلبات، المنتجات، المخزون، الخصومات، شرائح العملاء والولاء، قنوات البيع، التقارير، التحصيل، التسويق، وإعدادات التوصيل الذكي"),
    ("courier", "🛵", "تطبيق المندوب", "استقبال المهام، تسجيل الحضور، الورديات، التتبع الحي، الأرباح والحوافز"),
    ("customer", "🛍", "تطبيق العميل", "تصفح المتاجر، الطلب، تتبع الشحنة مباشرة، وتأكيد الاستلام OTP"),
    ("fleet", "📊", "Fleet Partners", "إدارة الأسطول، الإرسال والتحكم، الرواتب والعقود، التذاكر، والقنوات"),
    ("ops", "☁️", "لوحة التشغيل Ops Cloud", "لوحة قيادة، الإرسال والتحكم، القنوات والتكاليف، شركات التشغيل، وإعدادات النظام"),
]
PAGES_EN = [
    ("merchant", "🏪", "Merchant Dashboard", "Orders, products, inventory, discounts, customer segments & loyalty, sales channels, reports, payouts, marketing, and smart dispatch settings"),
    ("courier", "🛵", "Courier App", "Accept tasks, clock in/out, shifts, live tracking, earnings and incentives"),
    ("customer", "🛍", "Customer App", "Browse stores, order, track your delivery live, and confirm receipt via OTP"),
    ("fleet", "📊", "Fleet Partners", "Fleet management, dispatch control, payouts & contracts, tickets, and channels"),
    ("ops", "☁️", "Ops Cloud Console", "Command center, dispatch control, channels & costs, operations companies, and system settings"),
]

# File suffix per language: AR uses merchant.html, EN uses merchant-en.html
SUFFIX = {"ar": "", "en": "-en"}
MOCK_SUFFIX = {"ar": "", "en": "-en"}

def inject_mock(html: str, mock: str) -> str:
    script = "<script>" + mock + "</script>\n"
    m = re.search(r"<body[^>]*>", html)
    if m:
        html = html[:m.end()] + "\n" + script + html[m.end():]
    else:
        html = html.replace("</head>", script + "</head>")
    return html

def langbar(lang):
    if lang == "ar":
        return '''<div class="langbar">
  <a href="dou-demo.html" class="active">العربية</a>
  <a href="dou-demo-en.html">English</a>
</div>'''
    return '''<div class="langbar">
  <a href="dou-demo.html">العربية</a>
  <a href="dou-demo-en.html" class="active">English</a>
</div>'''

def build(output, lang, PAGES, MOCK):
    go_text = "افتح التجربة ←" if lang == "ar" else "Open demo →"
    close_back = "العودة للواجهات" if lang == "ar" else "Back to interfaces"
    hero = hero_block(lang)
    country_screen = country_screen_block(lang)
    country_data_js = COUNTRY_JS_AR if lang == "ar" else COUNTRY_JS_EN
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
        titles_js = 'const TITLES = {merchant:"لوحة التاجر", courier:"تطبيق المندوب", customer:"تطبيق العميل", fleet:"Fleet Partners", ops:"لوحة التشغيل Ops Cloud"};'
    else:
        titles_js = 'const TITLES = {merchant:"Merchant Dashboard", courier:"Courier App", customer:"Customer App", fleet:"Fleet Partners", ops:"Ops Cloud Console"};'

    html = f'''<!doctype html>
<html lang="{lang}" dir="{"rtl" if lang == "ar" else "ltr"}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DOU — {title_attr(lang)}</title>
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
.foot{{text-align:center;color:#5b6b86;font-size:11px;padding:0 20px 40px;direction:ltr}}
#stage{{position:fixed;inset:0;background:var(--nav);display:none;z-index:20}}
#stage.open{{display:block}}
.appbar{{height:58px;background:var(--card);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:14px;padding:0 18px}}
.appbar .back{{background:none;border:0;color:var(--orange2);font-family:inherit;font-size:13px;font-weight:700;cursor:pointer;display:flex;gap:8px;align-items:center}}
.appbar .t{{font-size:13px;color:var(--muted)}}
.appbar .t b{{color:var(--ink)}}
#frame{{width:100%;height:calc(100% - 58px);border:0}}
/* ===== Country chooser ===== */
.countryGate{{position:fixed;inset:0;background:rgba(10,15,26,.82);backdrop-filter:blur(6px);z-index:100;display:grid;place-items:center;padding:20px}}
.countryGate .box{{background:var(--nav);border:1px solid #2a3a58;border-radius:22px;max-width:720px;width:100%;padding:36px 30px;text-align:center}}
.countryGate h2{{margin:0 0 6px;font-size:22px}}
.countryGate p{{color:var(--muted);font-size:13px;margin:0 0 24px}}
.countryOpts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}}
.copt{{background:var(--card);border:1.5px solid var(--line);border-radius:16px;padding:22px 16px;cursor:pointer;font-family:inherit;color:inherit;transition:.18s;display:flex;flex-direction:column;align-items:center;gap:6px}}
.copt:hover{{border-color:var(--orange);transform:translateY(-3px);box-shadow:0 18px 44px rgba(0,0,0,.4)}}
.copt .fl{{font-size:42px}}
.copt b{{font-size:16px}}.copt small{{color:var(--muted);font-size:11.5px}}
.copt .cur{{margin-top:8px;background:var(--orange-soft);color:var(--orange2);font-size:10.5px;font-weight:700;padding:3px 12px;border-radius:20px}}
.countryTag{{position:fixed;bottom:18px;right:20px;background:var(--card);border:1px solid var(--line);border-radius:30px;padding:9px 16px;font-size:12px;font-weight:700;z-index:30;display:none;align-items:center;gap:8px;cursor:pointer;box-shadow:var(--shadow)}}
.countryTag.show{{display:flex}}
.countryTag .x{{color:var(--orange2);font-weight:800;font-size:14px}}
</style>
</head>
<body>
{langbar(lang)}
{hero}
<div class="grid">
{landing_cards}
</div>

<div class="foot">DOU Delivery Operations Platform &copy; Sameh Saleh &middot; TechBuilder Confidential &middot; Interactive demo with simulated data</div>

{country_screen}

<div class="countryTag" id="countryTag" onclick="openCountryGate()">
  <span id="countryTagFlag">🌍</span><span id="countryTagName">–</span><span class="x">✕</span>
</div>

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
const COUNTRIES = {country_data_js};
let country = localStorage.getItem('dou_country') || 'SA';
let blobUrl = null;
function setCountry(code){{
  country = code;
  localStorage.setItem('dou_country', code);
  document.getElementById('countryGate').style.display = 'none';
  const tag = document.getElementById('countryTag');
  tag.classList.add('show');
  document.getElementById('countryTagFlag').textContent = COUNTRIES[code].flag;
  document.getElementById('countryTagName').textContent = COUNTRIES[code].name;
}}
function openCountryGate(){{ document.getElementById('countryGate').style.display = 'grid'; }}
function openDemo(name){{
  const tpl = document.getElementById('tpl-'+name);
  document.getElementById('stageTitle').textContent = TITLES[name];
  const pre = '<script>window.DOU_COUNTRY="'+country+'";<\/script>';
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
document.addEventListener('DOMContentLoaded', () => {{
  if(COUNTRIES[country]) setCountry(country);
}});
</script>
</body>
</html>'''
    out = STATIC / output
    out.write_text(html)
    print(f"✅ Built {output} — {len(html)} bytes")

def hero_block(lang):
    if lang == "ar":
        return '''<div class="hero">
  <div class="logo">D<i></i>ou</div>
  <div class="logoFull">DELIVERY OPERATIONS PLATFORM</div>
  <div class="badge"><span>⚡</span> نسخة تفاعلية كاملة — تعمل بدون إنترنت وبدون سيرفر</div>
  <h1>منصة التوصيل الموحّدة</h1>
  <p>اجمع طلباتك من كل القنوات (POS / تطبيق / منصات الطعام)، أسنِدها ذكياً لمندوبيك الدائمين أو الفريلانسر أو شركات الشحن، وتابع كل توصيلة لحظياً — كل ذلك من لوحة واحدة. اختر واجهة وافتح التجربة:</p>
</div>'''
    return '''<div class="hero">
  <div class="logo">D<i></i>ou</div>
  <div class="logoFull">DELIVERY OPERATIONS PLATFORM</div>
  <div class="badge"><span>⚡</span> Full interactive demo — runs offline, no server needed</div>
  <h1>Unified Delivery Platform</h1>
  <p>Collect orders from every channel (POS / app / food platforms), smart-assign them to your dedicated couriers, freelancers or shipping companies, and track every drop live — all from a single console. Pick an interface and open the demo:</p>
</div>'''

def title_attr(lang):
    return "Delivery Platform | Interactive Demo" if lang == "en" else "منصة التوصيل | تجربة تفاعلية"

def country_screen_block(lang):
    if lang == "ar":
        return '''<div class="countryGate" id="countryGate">
  <div class="box">
    <h2>🌍 اختر دولة التشغيل</h2>
    <p>اختر الدولة أولاً — كل البيانات (المتاجر، العملة، المدن، المناديب) تتغير تلقائياً.</p>
    <div class="countryOpts">
      <button class="copt" onclick="setCountry('SA')"><span class="fl">🇸🇦</span><b>السعودية</b><small>الرياض، جدة — العملة ر.س</small><span class="cur">ر.س SAR</span></button>
      <button class="copt" onclick="setCountry('EG')"><span class="fl">🇪🇬</span><b>مصر</b><small>القاهرة، الإسكندرية — العملة ج.م</small><span class="cur">ج.م EGP</span></button>
    </div>
  </div>
</div>'''
    return '''<div class="countryGate" id="countryGate">
  <div class="box">
    <h2>🌍 Choose your operating country</h2>
    <p>Pick a country first — all data (stores, currency, cities, couriers) updates automatically.</p>
    <div class="countryOpts">
      <button class="copt" onclick="setCountry('SA')"><span class="fl">🇸🇦</span><b>Saudi Arabia</b><small>Riyadh, Jeddah — SAR</small><span class="cur">SAR ر.س</span></button>
      <button class="copt" onclick="setCountry('EG')"><span class="fl">🇪🇬</span><b>Egypt</b><small>Cairo, Alexandria — EGP</small><span class="cur">EGP ج.م</span></button>
    </div>
  </div>
</div>'''

COUNTRY_JS_AR = '{SA:{name:"السعودية",flag:"🇸🇦"},EG:{name:"مصر",flag:"🇪🇬"}}'
COUNTRY_JS_EN = '{SA:{name:"Saudi Arabia",flag:"🇸🇦"},EG:{name:"Egypt",flag:"🇪🇬"}}'

MOCK = (STATIC / "dou-demo-mock.js").read_text()
MOCK_EN = (STATIC / "dou-demo-mock-en.js").read_text()

build("dou-demo.html", "ar", PAGES_AR, MOCK)
build("dou-demo-en.html", "en", PAGES_EN, MOCK_EN)
