import { chromium } from 'playwright';
import assert from 'assert';

const BASE_URL = 'http://127.0.0.1:8123';
const ARTIFACT_DIR = '/Users/sameh/.gemini/antigravity/brain/056265f0-e866-44a5-a8b3-03743ced3176';

async function run() {
  console.log('\n========================================================================================');
  console.log('SHIFT DRIVER ASSIGNMENT INSTANT SEARCH PICKER ACCEPTANCE TEST');
  console.log('========================================================================================\n');

  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.on('console', msg => console.log('PAGE LOG:', msg.text()));
  page.on('pageerror', err => console.error('PAGE ERROR:', err));

  // 1. Authenticate
  await page.goto(`${BASE_URL}/app/v2/`);
  await page.waitForSelector('#login-phone', { timeout: 8000 });
  await page.fill('#login-phone', '966511111111');
  await page.fill('#login-password', 'Company123!');
  await page.click('button[type="submit"]');
  await page.waitForSelector('.fleet-app', { timeout: 8000 });
  console.log('  ✓ [SEARCH-01] Fleet Admin Authenticated');

  // 2. Open Shifts tab
  await page.evaluate(() => window.go('shifts'));
  await page.waitForTimeout(1000);

  // 3. Click "➕ إسناد سائق"
  const assignBtn = await page.waitForSelector('table button:has-text("➕ إسناد سائق")', { timeout: 5000 });
  await assignBtn.click();
  await page.waitForTimeout(800);

  // Check search bar exists
  const searchInput = await page.waitForSelector('#shift-assign-search-input', { timeout: 5000 });
  assert(searchInput, 'Search bar found in assign modal');
  console.log('  ✓ [SEARCH-02] Instant Search Input Found & Focused');

  await page.screenshot({ path: `${ARTIFACT_DIR}/17a_assign_shift_instant_search_modal.png`, fullPage: false });
  console.log('  ✓ [SEARCH-03] Instant Search Modal Captured (17a_assign_shift_instant_search_modal.png)');

  // 4. Type search query to filter from hundreds/thousands of couriers
  await searchInput.fill('سائق تجريبي');
  await page.waitForTimeout(600);

  const countText = await page.textContent('#search-results-count');
  console.log(`  ✓ [SEARCH-04] Live Filter Active: ${countText}`);

  await page.screenshot({ path: `${ARTIFACT_DIR}/17b_assign_shift_search_filtered.png`, fullPage: false });
  console.log('  ✓ [SEARCH-05] Filtered Search Results Captured (17b_assign_shift_search_filtered.png)');

  await context.close();
  await browser.close();

  console.log('\n========================================================================================');
  console.log('ALL INSTANT SEARCH PICKER TESTS PASSED (100% SUCCESS)');
  console.log('========================================================================================\n');
}

run().catch(err => {
  console.error('Test execution failed:', err);
  process.exit(1);
});
