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

  // Check table content
  const tableHtml = await page.evaluate(() => document.querySelector('.table-wrap')?.innerHTML?.slice(0, 1000) || 'NO TABLE');
  console.log('Table HTML:', tableHtml);

  const emptyState = await page.evaluate(() => document.querySelector('.state-empty')?.textContent || 'NO EMPTY STATE');
  console.log('Empty state:', emptyState);

  // Check if any buttons exist
  const buttons = await page.evaluate(() => {
    const btns = document.querySelectorAll('button');
    return Array.from(btns).map(b => b.textContent?.trim()).filter(t => t).slice(0, 20);
  });
  console.log('All buttons:', buttons);

  await browser.close();
}

run().catch(e => { console.error(e); process.exit(1); });
