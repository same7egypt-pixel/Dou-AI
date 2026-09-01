import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8123';

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  await page.goto(`${BASE}/app/v2/`);
  await page.waitForSelector('#login-form', { timeout: 5000 });
  await page.fill('#login-phone', '966511111111');
  await page.fill('#login-password', 'Company123!');
  await page.click('button[type="submit"]');
  await page.waitForSelector('.fleet-app', { timeout: 5000 });
  console.log('Logged in');

  // Go to Riders
  await page.click('.nav-item[data-view="riders"]');
  await page.waitForSelector('.table-wrap, .state-empty', { timeout: 5000 });

  // Add Rider
  await page.click('button:has-text("إضافة سائق")');
  await page.waitForSelector('#add-rider-form', { timeout: 5000 });
  await page.fill('#ar-name', 'Test Rider E2E');
  await page.fill('#ar-phone', '966599999999');
  await page.fill('#ar-password', 'TempPass123');
  await page.click('#add-rider-form button[type="submit"]');
  await page.waitForTimeout(2000);

  const msgEl = await page.$('#ar-msg');
  if (msgEl) {
    const msgText = await msgEl.textContent();
    const msgColor = await msgEl.evaluate(el => el.style.color);
    console.log('Add rider message:', msgText, 'color:', msgColor);
  }

  const modalOpen = await page.$('#add-rider-form');
  console.log('Modal still open:', !!modalOpen);

  await page.waitForTimeout(1000);
  const tableHtml = await page.evaluate(() => document.querySelector('.table-wrap')?.innerHTML?.slice(0, 1500) || 'NO TABLE');
  console.log('Table HTML after add:', tableHtml);

  await browser.close();
}

run().catch(e => { console.error(e); process.exit(1); });
