import { chromium } from 'playwright';
const BASE_URL = 'http://127.0.0.1:8123';
async function test() {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(`${BASE_URL}/app/v2/`);
  await page.fill('#login-phone', '966511111111');
  await page.fill('#login-password', 'Company123!');
  await page.click('button[type="submit"]');
  await page.waitForSelector('.fleet-app', { timeout: 8000 });
  const adminToken = await page.evaluate(() => localStorage.getItem('dou_token_v2'));
  
  const wpsRes = await page.request.get(`${BASE_URL}/hr/payroll/wps-export?month=2026-08`, {
    headers: { Authorization: `Bearer ${adminToken}` }
  });
  console.log('WPS status:', wpsRes.status());
  console.log('WPS Content:\n', (await wpsRes.text()).slice(0, 300));
  await browser.close();
}
test();
