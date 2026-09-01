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
  page.on('requestfailed', req => {
    console.log('[REQUEST FAILED]', req.url(), req.failure()?.errorText);
  });

  console.log('=== DEBUG LOGIN ===');
  await page.goto(`${BASE}/app/v2/`);
  await page.waitForSelector('#login-form', { timeout: 5000 });
  console.log('Login form visible');

  // Fill and submit
  await page.fill('#login-phone', '966511111111');
  await page.fill('#login-password', 'Company123!');
  await page.click('button[type="submit"]');

  // Wait for either fleet-app or error
  await page.waitForTimeout(3000);

  const appVisible = await page.isVisible('.fleet-app').catch(() => false);
  const errorVisible = await page.isVisible('.error-banner').catch(() => false);
  const stillLogin = await page.isVisible('#login-form').catch(() => false);

  console.log(`fleet-app visible: ${appVisible}`);
  console.log(`error-banner visible: ${errorVisible}`);
  console.log(`login-form still visible: ${stillLogin}`);

  if (errorVisible) {
    const errText = await page.textContent('.error-banner');
    console.log('Error text:', errText);
  }

  // Check what URL we're on
  console.log('Current URL:', page.url());

  await browser.close();
}

run().catch(e => { console.error(e); process.exit(1); });
