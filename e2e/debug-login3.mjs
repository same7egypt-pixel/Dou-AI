import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8123';

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  await page.goto(`${BASE}/app/v2/`);
  await page.waitForSelector('#login-form', { timeout: 5000 });

  // Fill and submit login
  await page.fill('#login-phone', '966511111111');
  await page.fill('#login-password', 'Company123!');
  await page.click('button[type="submit"]');

  await page.waitForTimeout(2000);

  // Check localStorage for token
  const token = await page.evaluate(() => localStorage.getItem('dou_token_v2'));
  const role = await page.evaluate(() => localStorage.getItem('dou_role_v2'));
  console.log('Token stored:', token ? 'YES (' + token.slice(0, 20) + '...)' : 'NO');
  console.log('Role stored:', role);

  // Try calling /fleet/me directly
  const meResult = await page.evaluate(async () => {
    const token = localStorage.getItem('dou_token_v2');
    const res = await fetch('/fleet/me', {
      headers: { Authorization: `Bearer ${token}` }
    });
    return { status: res.status, body: await res.text().catch(() => '') };
  });
  console.log('fleet/me response:', meResult.status, meResult.body.slice(0, 300));

  // Check if renderShell was called
  const appHtml = await page.evaluate(() => document.getElementById('app')?.innerHTML?.slice(0, 200));
  console.log('App HTML:', appHtml);

  await browser.close();
}

run().catch(e => { console.error(e); process.exit(1); });
