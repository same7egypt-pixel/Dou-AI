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

  // Take screenshot of clean table
  await page.screenshot({ path: path.join(ARTIFACT_DIR, '08b_payroll_bonus_plans_clean.png') });
  console.log('✓ 08b_payroll_bonus_plans_clean.png saved');

  // Open Add Bonus Plan Modal
  const addBtn = await page.waitForSelector('button:has-text("إضافة خطة بونص")', { timeout: 8000 });
  await addBtn.click();
  await page.waitForTimeout(800);

  // Take screenshot of redesigned modal
  await page.screenshot({ path: path.join(ARTIFACT_DIR, '08c_add_bonus_plan_redesigned_modal.png') });
  console.log('✓ 08c_add_bonus_plan_redesigned_modal.png saved');

  await browser.close();
}

run();
