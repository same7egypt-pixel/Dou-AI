import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8123';

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  page.on('console', msg => {
    console.log(`[${msg.type()}]`, msg.text());
  });
  page.on('pageerror', err => {
    console.log('[PAGE ERROR]', err.message, err.stack);
  });
  page.on('requestfinished', async req => {
    if (req.url().includes('/auth/login')) {
      const res = await req.response();
      console.log(`[LOGIN REQ] ${req.method()} ${req.url()} -> ${res?.status()}`);
      if (res && res.status() >= 400) {
        const body = await res.text().catch(() => '');
        console.log('[LOGIN ERROR BODY]', body);
      }
    }
  });

  await page.goto(`${BASE}/app/v2/`);
  await page.waitForSelector('#login-form', { timeout: 5000 });

  await page.fill('#login-phone', '966511111111');
  await page.fill('#login-password', 'Company123!');
  await page.click('button[type="submit"]');

  await page.waitForTimeout(4000);

  console.log('Final URL:', page.url());
  await browser.close();
}

run().catch(e => { console.error(e); process.exit(1); });
