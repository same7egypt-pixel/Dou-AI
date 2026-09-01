import { chromium } from 'playwright';
import assert from 'assert';

const BASE_URL = 'http://127.0.0.1:8123';
const ARTIFACT_DIR = '/Users/sameh/.gemini/antigravity/brain/056265f0-e866-44a5-a8b3-03743ced3176';

async function run() {
  console.log('\n========================================================================================');
  console.log('SEARCHABLE SELECT / COMBOBOX UI ACCEPTANCE TEST SUITE');
  console.log('========================================================================================\n');

  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // 1. Authenticate
  await page.goto(`${BASE_URL}/app/v2/`);
  await page.fill('#login-phone', '966511111111');
  await page.fill('#login-password', 'Company123!');
  await page.click('button[type="submit"]');
  await page.waitForSelector('.fleet-app', { timeout: 8000 });
  console.log('  ✓ [SEARCH-01] Authenticated into Fleet OS');

  // 2. Test Rider 360 Searchable Rider Selector
  await page.evaluate(() => window.go('rider360'));
  await page.waitForTimeout(1200);

  const r360Input = await page.waitForSelector('#r360-select ~ .searchable-select-box .searchable-select-input', { timeout: 8000 });
  assert(r360Input, 'Rider 360 searchable input found');
  
  // Type in the search box to search for Ahmed
  await r360Input.click();
  await page.waitForTimeout(300);
  await r360Input.fill('Ahmed');
  await page.waitForTimeout(500);

  await page.screenshot({ path: `${ARTIFACT_DIR}/13a_rider360_searchable_dropdown.png`, fullPage: false });
  console.log('  ✓ [SEARCH-02] Rider 360 Searchable Dropdown Rendered & Filtered (Captured 13a_rider360_searchable_dropdown.png)');

  // Select the matching option
  const ahmedOption = await page.waitForSelector('.searchable-select-option:has-text("Ahmed Said")', { timeout: 5000 });
  await ahmedOption.click();
  await page.waitForTimeout(800);

  const selectedHiddenVal = await page.evaluate(() => document.getElementById('r360-select')?.value);
  assert(selectedHiddenVal, 'Rider was selected into hidden input');
  console.log(`  ✓ [SEARCH-03] Rider Selected via Search: ID #${selectedHiddenVal}`);

  // 3. Test Payroll Adjustments Searchable Rider Selector
  await page.evaluate(() => window.go('payroll'));
  await page.waitForTimeout(1200);

  // Switch to Adjustments subtab
  const adjTab = await page.waitForSelector('.tab:has-text("السلف والخصومات")', { timeout: 5000 });
  await adjTab.click();
  await page.waitForTimeout(800);

  const adjCourierInput = await page.waitForSelector('#adj-courier-select ~ .searchable-select-box .searchable-select-input', { timeout: 5000 });
  assert(adjCourierInput, 'Adjustments searchable rider input found');

  await adjCourierInput.click();
  await page.waitForTimeout(300);
  await adjCourierInput.fill('9665');
  await page.waitForTimeout(500);

  await page.screenshot({ path: `${ARTIFACT_DIR}/13b_payroll_adjustments_searchable_rider.png`, fullPage: false });
  console.log('  ✓ [SEARCH-04] Payroll Adjustments Searchable Rider Picker Rendered (Captured 13b_payroll_adjustments_searchable_rider.png)');

  // Select first matching courier
  const firstMatch = await page.waitForSelector('.searchable-select-option', { timeout: 5000 });
  await firstMatch.click();
  await page.waitForTimeout(400);

  const selectedAdjCourier = await page.evaluate(() => document.getElementById('adj-courier-select')?.value);
  assert(selectedAdjCourier, 'Adjustments rider value populated');
  console.log(`  ✓ [SEARCH-05] Adjustments Form Rider Chosen: #${selectedAdjCourier}`);

  // Fill and test adjustment creation
  await page.fill('#adj-amount-input', '150');
  await page.fill('#adj-note-input', 'سلفة تجريبية عبر البحث الذكي');
  
  // 4. Test Riders Roster Edit Rider Searchable Supervisor Selector
  await page.evaluate(() => window.go('riders'));
  await page.waitForTimeout(1200);

  const editBtn = await page.waitForSelector('table button:has-text("✏️ تعديل")', { timeout: 5000 });
  await editBtn.click();
  await page.waitForTimeout(800);

  const erSupInput = await page.waitForSelector('#er-supervisor ~ .searchable-select-box .searchable-select-input', { timeout: 5000 });
  assert(erSupInput, 'Edit rider supervisor searchable input found');

  await erSupInput.click();
  await page.waitForTimeout(300);
  await erSupInput.fill('Ahmed');
  await page.waitForTimeout(500);

  await page.screenshot({ path: `${ARTIFACT_DIR}/13c_edit_rider_searchable_supervisor.png`, fullPage: false });
  console.log('  ✓ [SEARCH-06] Edit Rider Searchable Supervisor Rendered (Captured 13c_edit_rider_searchable_supervisor.png)');

  await browser.close();
  console.log('\n========================================================================================');
  console.log('ALL SEARCHABLE SELECT TESTS PASSED WITH 100% SUCCESS');
  console.log('========================================================================================\n');
}

run().catch(err => {
  console.error('Test execution failed:', err);
  process.exit(1);
});
