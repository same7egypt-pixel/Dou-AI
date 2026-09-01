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
  
  const ts = Date.now();
  const contractRes = await page.request.post(`${BASE_URL}/hr/contracts`, {
    headers: { Authorization: `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
    data: {
      name: `عقد نينجا إكسبريس ${ts}`,
      client_name: 'Ninja Delivery App',
      client_rate_per_order: 16.50,
      contract_type: 'COMMERCIAL',
      start_date: new Date().toISOString().slice(0, 10),
      end_date: new Date(Date.now() + 180*24*3600*1000).toISOString().slice(0, 10),
      cities: [
        { city: 'الرياض', city_id: 1, supervisor_ids: [1, 2] },
        { city: 'جدة', city_id: 2, supervisor_ids: [1] }
      ]
    }
  });
  console.log('Status:', contractRes.status());
  console.log('Body:', await contractRes.text());
  await browser.close();
}
test();
