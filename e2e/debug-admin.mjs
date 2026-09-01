import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8123';

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  page.on('console', msg => {
    if (msg.type() === 'error') console.log('[CONSOLE ERROR]', msg.text());
  });
  page.on('pageerror', err => {
    console.log('[PAGE ERROR]', err.message);
  });

  await page.goto(`${BASE}/admin/v2/`);
  await page.waitForSelector('#login-form', { timeout: 5000 });
  await page.fill('#login-phone', '966500000001');
  await page.fill('#login-password', 'SuperAdmin123!');
  await page.click('button[type="submit"]');
  await page.waitForSelector('.admin-app', { timeout: 5000 });
  console.log('Logged in to Super Admin');

  // Click overview
  await page.click('.nav-item[data-view="overview"]');
  await page.waitForTimeout(2000);

  const content = await page.evaluate(() => {
    const area = document.querySelector('.content-area');
    return area?.innerHTML?.slice(0, 1000) || 'NO CONTENT';
  });
  console.log('Content:', content);

  await browser.close();
}

run().catch(e => { console.error(e); process.exit(1); });
