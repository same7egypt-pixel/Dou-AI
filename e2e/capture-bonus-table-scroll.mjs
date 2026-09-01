import { chromium } from 'playwright';
import path from 'path';

const BASE_URL = 'http://127.0.0.1:8123';
const ARTIFACT_DIR = '/Users/sameh/.gemini/antigravity/brain/056265f0-e866-44a5-a8b3-03743ced3176';

async function run() {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  await page.goto(`${BASE_URL}/app/v2/`);
  await page.fill('#login-phone', '966511111111');
  await page.fill('#login-password', 'Company123!');
  await page.click('button[type="submit"]');
  await page.waitForSelector('.fleet-app', { timeout: 8000 });

  // Navigate to payroll
  await page.evaluate(() => window.go('payroll'));
  await page.waitForTimeout(1000);
  
  // Click Bonus tab
  const bonusTab = await page.waitForSelector('.tab:has-text("البونص")', { timeout: 8000 });
  await bonusTab.click();
  await page.waitForTimeout(1000);

  // Scroll down to bonus plans table
  await page.evaluate(() => {
    const el = document.querySelector('.card:last-child');
    if (el) el.scrollIntoView();
  });
  await page.waitForTimeout(500);

  // Take screenshot of scrolled view showing bonus plans table
  await page.screenshot({ path: path.join(ARTIFACT_DIR, '08d_payroll_bonus_plans_table_scrolled.png') });
  console.log('✓ 08d_payroll_bonus_plans_table_scrolled.png saved');

  await browser.close();
}

run();
