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

  await check('Login page renders', async () => {
    await page.goto(`${BASE}/app/v2/`);
    await page.waitForSelector('#login-form', { timeout: 5000 });
  });

  await check('Login with valid credentials', async () => {
    await page.fill('#login-phone', '966511111111');
    await page.fill('#login-password', 'Company123!');
    await page.click('button[type="submit"]');
    await page.waitForSelector('.fleet-app', { timeout: 5000 });
  });

  await check('Command Center loads with KPIs', async () => {
    await page.click('.nav-item[data-view="commandCenter"]');
    await page.waitForSelector('.metric', { timeout: 5000 });
  });

  await check('Riders screen loads', async () => {
    await page.click('.nav-item[data-view="riders"]');
    await page.waitForSelector('.table-wrap, .state-empty', { timeout: 5000 });
  });

  await check('Rider 360 opens', async () => {
    await page.evaluate(() => {
      if (typeof window.openRider360 === 'function') {
        window.openRider360(1);
      } else {
        throw new Error('openRider360 not defined');
      }
    });
    await page.waitForSelector('#r360-select', { timeout: 5000 });
  });

  for (const tab of ['profile', 'documents', 'shifts', 'attendance', 'performance', 'targets', 'payroll', 'leave']) {
    await check(`Rider 360 ${tab} tab loads`, async () => {
      await page.click(`.tab[data-tab="${tab}"]`);
      await page.waitForSelector('.tab-pane .card, .tab-pane .table-wrap, .tab-pane .state-empty, .tab-pane .cards', { timeout: 5000 });
    });
  }

  const otherViews = [
    { view: 'shifts', selector: '.table-wrap, .state-empty' },
    { view: 'needsAttention', selector: '.card, .state-empty' },
    { view: 'capacity', selector: '.metric, .state-empty' },
    { view: 'reports', selector: '.reports-catalog, .state-empty' },
    { view: 'payroll', selector: '.metric, .card, .state-empty' },
    { view: 'douai', selector: '.ai-shell' },
  ];

  for (const { view, selector } of otherViews) {
    await check(`${view} screen loads`, async () => {
      await page.click(`.nav-item[data-view="${view}"]`);
      await page.waitForSelector(selector, { timeout: 5000 });
    });
  }

  await check('DOU AI sends message', async () => {
    await page.fill('#ai-input', 'ما الذي يحتاج انتباهي اليوم؟');
    await page.click('#ai-send');
    await page.waitForSelector('.ai-msg.assistant', { timeout: 10000 });
  });

  const passed = results.filter(r => r.status === 'PASS').length;
  const failed = results.filter(r => r.status === 'FAIL');
  console.log(`\n=== RESULTS: ${passed}/${results.length} PASSED ===`);
  if (failed.length) {
    console.log('\nFAILED:');
    failed.forEach(f => console.log(`  ✗ ${f.name}: ${f.error}`));
  }

  await browser.close();
  process.exit(failed.length ? 1 : 0);
}

run().catch(e => { console.error(e); process.exit(1); });
