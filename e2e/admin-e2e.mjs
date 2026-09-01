import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8123';

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  const results = [];

  async function check(name, fn) {
    try {
      await fn();
      results.push({ name, status: 'PASS' });
      console.log(`✓ ${name}`);
    } catch (e) {
      results.push({ name, status: 'FAIL', error: e.message });
      console.log(`✗ ${name}: ${e.message}`);
    }
  }

  await check('Super Admin Login page renders', async () => {
    await page.goto(`${BASE}/admin/v2/`);
    await page.waitForSelector('#login-form', { timeout: 5000 });
  });

  await check('Super Admin Login', async () => {
    await page.fill('#login-phone', '966500000001');
    await page.fill('#login-password', 'SuperAdmin123!');
    await page.click('button[type="submit"]');
    await page.waitForSelector('.admin-app', { timeout: 5000 });
  });

  await check('Overview screen loads', async () => {
    await page.click('.nav-item[data-view="overview"]');
    await page.waitForTimeout(2000);
    await page.waitForSelector('.metric, .card, .state-empty', { timeout: 10000 });
  });

  await check('Tenants screen loads', async () => {
    await page.click('.nav-item[data-view="tenants"]');
    await page.waitForTimeout(2000);
    await page.waitForSelector('.table-wrap, .state-empty', { timeout: 10000 });
  });

  await check('Revenue screen loads', async () => {
    await page.click('.nav-item[data-view="revenue"]');
    await page.waitForTimeout(2000);
    await page.waitForSelector('.metric, .card, .state-empty', { timeout: 10000 });
  });

  await check('Plans screen loads', async () => {
    await page.click('.nav-item[data-view="plans"]');
    await page.waitForTimeout(2000);
    await page.waitForSelector('.state-empty', { timeout: 10000 });
  });

  await check('Usage screen loads', async () => {
    await page.click('.nav-item[data-view="usage"]');
    await page.waitForTimeout(2000);
    await page.waitForSelector('.table-wrap, .state-empty', { timeout: 10000 });
  });

  await check('Health screen loads', async () => {
    await page.click('.nav-item[data-view="health"]');
    await page.waitForTimeout(2000);
    await page.waitForSelector('.card, .state-empty', { timeout: 10000 });
  });

  await check('Integrations screen loads', async () => {
    await page.click('.nav-item[data-view="integrations"]');
    await page.waitForTimeout(2000);
    await page.waitForSelector('.state-empty', { timeout: 10000 });
  });

  await check('Audit screen loads', async () => {
    await page.click('.nav-item[data-view="audit"]');
    await page.waitForTimeout(2000);
    await page.waitForSelector('.table-wrap, .state-empty', { timeout: 10000 });
  });

  await check('Settings screen loads', async () => {
    await page.click('.nav-item[data-view="settings"]');
    await page.waitForTimeout(2000);
    await page.waitForSelector('.state-empty', { timeout: 10000 });
  });

  const passed = results.filter(r => r.status === 'PASS').length;
  const failed = results.filter(r => r.status === 'FAIL');
  console.log(`\n=== SUPER ADMIN RESULTS: ${passed}/${results.length} PASSED ===`);
  if (failed.length) {
    console.log('\nFAILED:');
    failed.forEach(f => console.log(`  ✗ ${f.name}: ${f.error}`));
  }

  await browser.close();
  process.exit(failed.length ? 1 : 0);
}

run().catch(e => { console.error(e); process.exit(1); });
