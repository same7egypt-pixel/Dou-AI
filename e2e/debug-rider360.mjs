import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8123';

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  page.on('console', msg => {
    if (msg.type() === 'error') console.log('[CONSOLE ERROR]', msg.text());
  });

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

  // Check page content
  const content = await page.evaluate(() => {
    const table = document.querySelector('.table-wrap');
    const empty = document.querySelector('.state-empty');
    const buttons = document.querySelectorAll('button');
    return {
      hasTable: !!table,
      hasEmpty: !!empty,
      tableHtml: table?.innerHTML?.slice(0, 500) || 'NO TABLE',
      emptyText: empty?.textContent || 'NO EMPTY',
      buttonCount: buttons.length,
      buttonTexts: Array.from(buttons).map(b => b.textContent?.trim()).filter(t => t).slice(0, 15)
    };
  });
  console.log('Content:', JSON.stringify(content, null, 2));

  // Try to find the rider 360 button
  const btn = await page.$('button[onclick*="openRider360"]');
  console.log('Found button via selector:', !!btn);

  const btn2 = await page.evaluate(() => {
    const btns = document.querySelectorAll('button');
    for (const b of btns) {
      if (b.getAttribute('onclick')?.includes('openRider360')) {
        return { found: true, text: b.textContent, onclick: b.getAttribute('onclick') };
      }
    }
    return { found: false };
  });
  console.log('Found button via evaluate:', btn2);

  await browser.close();
}

run().catch(e => { console.error(e); process.exit(1); });
