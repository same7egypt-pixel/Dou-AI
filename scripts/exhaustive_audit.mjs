/**
 * Exhaustive hands-on audit: every public route, every role, every nav item,
 * every tab, every modal, every download.
 *
 * Safety rule this script enforces on itself: it navigates, opens and closes,
 * and downloads. It does NOT submit forms and does NOT click anything whose
 * label reads as destructive or as a commitment — delete, remove, approve,
 * finalize, send, pay. An audit that runs against production must not be able
 * to change what production holds. Buttons it declines are reported, not
 * silently skipped, so the coverage gap is visible rather than assumed away.
 *
 *   DOU_TEST_URL=https://dou.delivery DOU_ALLOW_PRODUCTION=yes \
 *     node scripts/exhaustive_audit.mjs
 */
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.DOU_TEST_URL || 'http://127.0.0.1:8123';
if (BASE.includes('dou.delivery') && process.env.DOU_ALLOW_PRODUCTION !== 'yes') {
  console.error(`Refusing to run against ${BASE} without DOU_ALLOW_PRODUCTION=yes`);
  process.exit(2);
}

const PASSWORD = process.env.DOU_TEST_PASSWORD || 'dou123456';
const ROLES = [
  { key: 'FLEET_ADMIN', phone: '966581112233', surface: '/app' },
  { key: 'OPS_MANAGER', phone: '966500000000', surface: '/app' },
  { key: 'SUPERVISOR', phone: '966591112233', surface: '/app' },
  { key: 'SUPER_ADMIN', phone: '966512345678', surface: '/admin' },
  { key: 'COURIER', phone: '966551112233', surface: '/driver' },
];

const PUBLIC_ROUTES = [
  '/', '/en', '/help', '/help/en', '/robots.txt', '/sitemap.xml',
  '/health', '/health/ready', '/app', '/admin', '/driver',
];
const ANCHORS = ['#why-dou', '#structure', '#payroll', '#driver-app', '#pricing', '#dou-ai-section', '#faq-section'];
const DOWNLOADS = ['/download/driver-apk'];

// A label matching any of these is a commitment or a deletion. Not clicked.
const UNSAFE = /حذف|احذف|إزالة|امسح|اعتماد|اعتمد|تأكيد|إرسال|ارسل|صرف|دفع|إنهاء|أنهِ|ترحيل|إلغاء الاشتراك|delete|remove|approve|confirm|send|finalize|pay|submit/i;

const findings = [];
const skipped = [];
let checks = 0;
const record = (area, name, ok, detail = '') => {
  checks++;
  if (!ok) findings.push({ area, name, detail });
  console.log(`${ok ? '✅' : '❌'} [${area}] ${name}${detail ? ' — ' + detail : ''}`);
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  console.log(`\n🎯 ${BASE}\n${'='.repeat(70)}`);

  // ── 1. Public surface ────────────────────────────────────────────────────
  console.log('\n--- 1. Public routes, assets and downloads ---');
  for (const route of PUBLIC_ROUTES) {
    try {
      const res = await fetch(`${BASE}${route}`, { redirect: 'follow' });
      record('PUBLIC', `GET ${route}`, res.ok, `${res.status}`);
    } catch (e) {
      record('PUBLIC', `GET ${route}`, false, e.message);
    }
  }
  for (const route of DOWNLOADS) {
    try {
      const res = await fetch(`${BASE}${route}`);
      const buf = res.ok ? Buffer.from(await res.arrayBuffer()) : Buffer.alloc(0);
      record('DOWNLOAD', `GET ${route}`, res.ok && buf.length > 1024,
        `${res.status} · ${(buf.length / 1048576).toFixed(2)} MB`);
    } catch (e) {
      record('DOWNLOAD', `GET ${route}`, false, e.message);
    }
  }

  const browser = await chromium.launch();

  // ── 2. Landing anchors and outbound links ────────────────────────────────
  console.log('\n--- 2. Landing anchors and internal links ---');
  {
    const page = await browser.newPage();
    const consoleErrors = [];
    page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()));
    await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded' });
    await sleep(2500);

    for (const anchor of ANCHORS) {
      const id = anchor.slice(1);
      const exists = await page.locator(`#${id}`).count();
      record('LANDING', `anchor ${anchor}`, exists > 0, exists ? 'target present' : 'no element with that id');
    }

    const hrefs = await page.$$eval('a[href]', (as) => as.map((a) => a.getAttribute('href')));
    const internal = [...new Set(hrefs.filter((h) => h && h.startsWith('/') && !h.startsWith('//')))];
    for (const href of internal) {
      try {
        const res = await fetch(`${BASE}${href}`, { redirect: 'follow' });
        record('LANDING', `link ${href}`, res.ok, `${res.status}`);
      } catch (e) {
        record('LANDING', `link ${href}`, false, e.message);
      }
    }
    record('LANDING', 'zero console errors', consoleErrors.length === 0,
      consoleErrors.slice(0, 2).join(' | ') || 'clean');
    await page.close();
  }

  // ── 3. Every role, every screen, every tab ───────────────────────────────
  for (const role of ROLES) {
    console.log(`\n--- 3. ${role.key} (${role.phone}) on ${role.surface} ---`);
    const ctx = await browser.newContext({ acceptDownloads: true });
    const page = await ctx.newPage();
    const consoleErrors = [];
    const netFailures = [];
    page.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 160));
    });
    page.on('pageerror', (e) => consoleErrors.push('UNCAUGHT: ' + String(e).slice(0, 160)));
    page.on('response', (r) => {
      const u = r.url().replace(BASE, '');
      if (r.status() >= 400 && !u.includes('/auth/login')) {
        netFailures.push(`${r.status()} ${u.slice(0, 90)}`);
      }
    });

    let loggedIn = false;
    try {
      const res = await fetch(`${BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: role.phone, password: PASSWORD }),
      });
      const body = await res.json().catch(() => ({}));
      const token = body.access_token;
      record('AUTH', `${role.key} login`, res.status === 200 && !!token, `${res.status}`);
      if (token) {
        await page.goto(`${BASE}${role.surface}`, { waitUntil: 'domcontentloaded' });
        await page.evaluate(([t, r]) => {
          localStorage.setItem('dou_token_v2', t);
          localStorage.setItem('dou_token_admin', t);
          localStorage.setItem('dou_token_courier', t);
          localStorage.setItem('dou_role_v2', r);
        }, [token, body.role || '']);
        await page.goto(`${BASE}${role.surface}`, { waitUntil: 'domcontentloaded' });
        await sleep(4000);
        loggedIn = true;
      }
    } catch (e) {
      record('AUTH', `${role.key} login`, false, e.message);
    }

    if (loggedIn) {
      // /driver is a different application — static/courier.html — with no
      // sidebar at all. Asserting `.nav-item` there reported "0 items" and
      // called it a product defect; it was a gap in this script. Each surface
      // is checked for what it actually renders.
      if (role.surface === '/driver') {
        const body = await page.$eval('body', (el) => el.innerText.trim().length).catch(() => 0);
        const errs = consoleErrors.filter((e) => e.startsWith('UNCAUGHT'));
        record(role.key, 'driver app renders', body > 80 && netFailures.length === 0,
          `text=${body} · net=${netFailures.slice(0, 2).join('; ') || 'ok'}`);
        record(role.key, 'zero uncaught JS exceptions', errs.length === 0,
          errs.slice(0, 2).join(' | ') || 'clean');
        await ctx.close();
        continue;
      }

      const navs = await page.$$eval('.nav-item[data-view]', (els) =>
        els.map((e) => e.dataset.view));
      record(role.key, 'sidebar rendered', navs.length > 0, `${navs.length} items: ${navs.join(', ')}`);

      for (const view of navs) {
        netFailures.length = 0;
        const before = consoleErrors.length;
        try {
          await page.click(`.nav-item[data-view="${view}"]`);
          await sleep(2300);
        } catch (e) {
          record(role.key, `open ${view}`, false, e.message.slice(0, 80));
          continue;
        }
        const content = await page.$eval('#content-area, #admin-content, #app', (el) => el.innerText.trim().length)
          .catch(() => 0);
        const newErrors = consoleErrors.slice(before);
        record(role.key, `screen ${view}`,
          content > 20 && netFailures.length === 0 && newErrors.length === 0,
          `text=${content} · net=${netFailures.slice(0, 2).join('; ') || 'ok'} · js=${newErrors.slice(0, 1).join('') || 'ok'}`);

        // Every tab inside the screen.
        const tabs = await page.$$eval('#content-area .tab, #content-area [data-tab]',
          (els) => els.map((e) => e.textContent.trim().slice(0, 30)));
        for (let i = 0; i < tabs.length; i++) {
          netFailures.length = 0;
          const errBefore = consoleErrors.length;
          try {
            const handles = await page.$$('#content-area .tab, #content-area [data-tab]');
            if (!handles[i]) continue;
            await handles[i].click();
            await sleep(1900);
          } catch { continue; }
          const body = await page.$eval('#content-area', (el) => el.innerText.trim().length)
            .catch(() => 0);
          record(role.key, `tab ${view} › ${tabs[i]}`,
            body > 20 && netFailures.length === 0 && consoleErrors.length === errBefore,
            `net=${netFailures.slice(0, 1).join('') || 'ok'}`);
        }

        // Non-destructive buttons: open, look, close.
        const buttons = await page.$$eval('#content-area button', (els) =>
          els.map((e) => e.textContent.trim().slice(0, 40)).filter(Boolean));
        for (let i = 0; i < buttons.length; i++) {
          const label = buttons[i];
          if (UNSAFE.test(label)) { skipped.push(`${role.key} · ${view} · ${label}`); continue; }
          const errBefore = consoleErrors.length;
          netFailures.length = 0;
          try {
            const handles = await page.$$('#content-area button');
            if (!handles[i]) continue;

            const dl = page.waitForEvent('download', { timeout: 4000 }).catch(() => null);
            await handles[i].click({ timeout: 3000 });
            await sleep(1500);

            const download = await dl;
            if (download) {
              const to = path.join('/tmp', `dou-audit-${Date.now()}-${download.suggestedFilename()}`);
              await download.saveAs(to);
              const size = fs.statSync(to).size;
              record(role.key, `download ${view} › ${label}`, size > 0,
                `${download.suggestedFilename()} · ${size} bytes`);
              fs.unlinkSync(to);
            }

            const modal = await page.$('.modal-overlay, .modal-box');
            if (modal) {
              const modalText = await page.$eval('.modal-box', (el) => el.innerText.trim().length)
                .catch(() => 0);
              record(role.key, `modal ${view} › ${label}`,
                modalText > 10 && consoleErrors.length === errBefore, `text=${modalText}`);
              await page.keyboard.press('Escape').catch(() => {});
              await page.$$eval('.modal-overlay', (els) => els.forEach((e) => e.remove())).catch(() => {});
              await sleep(400);
            } else if (consoleErrors.length > errBefore || netFailures.length) {
              record(role.key, `button ${view} › ${label}`, false,
                `js=${consoleErrors.slice(errBefore, errBefore + 1).join('')} net=${netFailures.slice(0, 1).join('')}`);
            }
          } catch { /* a button that cannot be clicked is not a defect by itself */ }
        }
      }

      record(role.key, 'zero uncaught JS exceptions',
        consoleErrors.filter((e) => e.startsWith('UNCAUGHT')).length === 0,
        consoleErrors.filter((e) => e.startsWith('UNCAUGHT')).slice(0, 2).join(' | ') || 'clean');
    }
    await ctx.close();
  }

  await browser.close();

  // ── Report ───────────────────────────────────────────────────────────────
  console.log(`\n${'='.repeat(70)}\n📊 AUDIT SUMMARY\n${'='.repeat(70)}`);
  console.log(`Checks run:      ${checks}`);
  console.log(`Failures:        ${findings.length}`);
  console.log(`Skipped (unsafe on production): ${skipped.length}`);
  if (findings.length) {
    console.log('\nFailures:');
    for (const f of findings) console.log(`  ❌ [${f.area}] ${f.name} — ${f.detail}`);
  }
  if (skipped.length) {
    console.log('\nNot clicked (destructive or committing):');
    for (const s of [...new Set(skipped)].slice(0, 40)) console.log(`  ⏭  ${s}`);
  }
  process.exit(findings.length ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(3); });
