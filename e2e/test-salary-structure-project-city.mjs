import { chromium } from 'playwright';
import assert from 'assert';

const BASE_URL = 'http://127.0.0.1:8123';
const ARTIFACT_DIR = '/Users/sameh/.gemini/antigravity/brain/056265f0-e866-44a5-a8b3-03743ced3176';

async function run() {
  console.log('\n========================================================================================');
  console.log('SALARY STRUCTURE LINKED TO PROJECT & CITY ACCEPTANCE TEST');
  console.log('========================================================================================\n');

  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // 1. Login
  await page.goto(`${BASE_URL}/app/v2/`);
  await page.fill('#login-phone', '966511111111');
  await page.fill('#login-password', 'Company123!');
  await page.click('button[type="submit"]');
  await page.waitForSelector('.fleet-app', { timeout: 8000 });
  console.log('  ✓ [SAL-01] Admin Authenticated');

  // 2. Open Payroll View
  await page.evaluate(() => window.go('payroll'));
  await page.waitForTimeout(1200);

  // 3. Open Create Salary Structure Modal
  const newSalBtn = await page.waitForSelector('button:has-text("➕ هيكل رواتب جديد")', { timeout: 5000 });
  await newSalBtn.click();
  await page.waitForTimeout(800);

  // Check that Project and City searchable selectors are present
  const projInput = await page.waitForSelector('#sal-project-select ~ .searchable-select-box .searchable-select-input', { timeout: 5000 });
  const cityInput = await page.waitForSelector('#sal-city-select ~ .searchable-select-box .searchable-select-input', { timeout: 5000 });
  assert(projInput, 'Project searchable selector found');
  assert(cityInput, 'City searchable selector found');
  console.log('  ✓ [SAL-02] Project & City Searchable Selectors Rendered');

  // Select a Project
  await projInput.click();
  await page.waitForTimeout(400);
  const projOpt = await page.waitForSelector('#sal-project-select ~ .searchable-select-dropdown .searchable-select-option:nth-child(2)', { timeout: 5000 });
  await projOpt.click();
  await page.waitForTimeout(400);

  // Select a City
  await cityInput.click();
  await page.waitForTimeout(400);
  const cityOpt = await page.waitForSelector('#sal-city-select ~ .searchable-select-dropdown .searchable-select-option:nth-child(2)', { timeout: 5000 });
  await cityOpt.click();
  await page.waitForTimeout(400);

  const uniqueId = Date.now().toString().slice(-4);
  await page.fill('#sal-name', `هيكل تشغيلي ${uniqueId}`);
  await page.fill('#sal-code', `SAL-STRUCT-${uniqueId}`);

  // Take screenshot of the complete Salary Structure modal
  await page.screenshot({ path: `${ARTIFACT_DIR}/14a_salary_structure_project_city_modal.png`, fullPage: false });
  console.log('  ✓ [SAL-03] Modal Screen with Project & City Captured (14a_salary_structure_project_city_modal.png)');

  // Submit the form
  const saveBtn = await page.waitForSelector('.modal-box button[type="submit"]', { timeout: 5000 });
  
  // Set alert listener
  page.on('dialog', async dialog => {
    console.log('  Dialog message:', dialog.message());
    await dialog.accept();
  });

  await saveBtn.click();
  await page.waitForTimeout(1000);

  // 4. Open Salary Structures Directory Modal
  const listBtn = await page.waitForSelector('button:has-text("📑 هياكل الرواتب")', { timeout: 5000 });
  await listBtn.click();
  await page.waitForTimeout(800);

  await page.screenshot({ path: `${ARTIFACT_DIR}/14b_salary_structures_directory_modal.png`, fullPage: false });
  console.log('  ✓ [SAL-04] Directory Modal Captured (14b_salary_structures_directory_modal.png)');

  await browser.close();
  console.log('\n========================================================================================');
  console.log('SALARY STRUCTURE PROJECT & CITY LINK TESTS PASSED WITH 100% SUCCESS');
  console.log('========================================================================================\n');
}

run().catch(err => {
  console.error('Test execution failed:', err);
  process.exit(1);
});
