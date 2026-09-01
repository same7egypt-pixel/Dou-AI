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

  // Toggle to Delivery Platform Mode
  const toggleModeBtn = await page.waitForSelector('#btn-toggle-operating-model', { timeout: 8000 });
  await toggleModeBtn.click();
  await page.waitForTimeout(1000);

  // Navigate to capacity
  await page.evaluate(() => window.go('capacity'));
  await page.waitForTimeout(1000);
  
  // Click 3PL Operators Tab
  const opTab = await page.waitForSelector('.tab:has-text("الشركات اللوجستية المشغلة")', { timeout: 8000 });
  await opTab.click();
  await page.waitForTimeout(1000);

  // Screenshot 3PL Operators Tab
  await page.screenshot({ path: path.join(ARTIFACT_DIR, '06c_platform_3pl_operators_tab.png') });
  console.log('✓ 06c_platform_3pl_operators_tab.png saved');

  // Open Add Operator Modal
  const addOpBtn = await page.waitForSelector('button:has-text("إضافة / ربط شركة لوجستية")', { timeout: 8000 });
  await addOpBtn.click();
  await page.waitForTimeout(800);

  // Screenshot modal
  await page.screenshot({ path: path.join(ARTIFACT_DIR, '06d_platform_add_operator_modal.png') });
  console.log('✓ 06d_platform_add_operator_modal.png saved');

  await browser.close();
}

run();
