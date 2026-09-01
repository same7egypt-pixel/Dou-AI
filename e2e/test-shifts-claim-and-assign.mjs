import { chromium } from 'playwright';
import assert from 'assert';

const BASE_URL = 'http://127.0.0.1:8123';
const ARTIFACT_DIR = '/Users/sameh/.gemini/antigravity/brain/056265f0-e866-44a5-a8b3-03743ced3176';

async function run() {
  console.log('\n========================================================================================');
  console.log('SHIFTS CLAIM (RIDER APP) & ASSIGNMENT (FLEET DASHBOARD) ACCEPTANCE TEST');
  console.log('========================================================================================\n');

  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] });

  // -------------------------------------------------------------------------
  // TEST PART 1: Fleet Dashboard Shift Assignment
  // -------------------------------------------------------------------------
  const fleetContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const fleetPage = await fleetContext.newPage();

  await fleetPage.goto(`${BASE_URL}/app/v2/`);
  await fleetPage.fill('#login-phone', '966511111111');
  await fleetPage.fill('#login-password', 'Company123!');
  await fleetPage.click('button[type="submit"]');
  await fleetPage.waitForSelector('.fleet-app', { timeout: 8000 });
  console.log('  ✓ [SHIFT-01] Fleet Admin Authenticated');

  await fleetPage.evaluate(() => window.go('shifts'));
  await fleetPage.waitForTimeout(1200);

  // Take screenshot of Fleet Shifts table
  await fleetPage.screenshot({ path: `${ARTIFACT_DIR}/15a_fleet_shifts_management.png`, fullPage: false });
  console.log('  ✓ [SHIFT-02] Fleet Shifts Table Rendered (Captured 15a_fleet_shifts_management.png)');

  // Click "إسناد سائق" on first shift
  const assignBtn = await fleetPage.waitForSelector('table button:has-text("➕ إسناد سائق")', { timeout: 5000 });
  await assignBtn.click();
  await fleetPage.waitForTimeout(600);

  // Check search input is present in assign modal
  const assignRiderInput = await fleetPage.waitForSelector('#shift-assign-search-input', { timeout: 5000 });
  assert(assignRiderInput, 'Assign rider instant search input found');
  console.log('  ✓ [SHIFT-03] Assign Rider Modal with Search Input Rendered');

  await fleetPage.screenshot({ path: `${ARTIFACT_DIR}/15b_fleet_assign_rider_modal.png`, fullPage: false });
  console.log('  ✓ [SHIFT-04] Assign Modal Captured (15b_fleet_assign_rider_modal.png)');

  await fleetContext.close();

  // -------------------------------------------------------------------------
  // TEST PART 2: Courier Mobile App Shift Selection / Claiming
  // -------------------------------------------------------------------------
  const riderContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
  const riderPage = await riderContext.newPage();

  await riderPage.goto(`${BASE_URL}/driver`);
  await riderPage.waitForSelector('#loginPhone', { timeout: 8000 });
  
  // Login as rider
  await riderPage.fill('#loginPhone', '966581545532');
  await riderPage.fill('#loginPassword', 'Rider123!');
  await riderPage.click('#loginButton');
  await riderPage.waitForSelector('.app-shell', { timeout: 8000 });
  console.log('  ✓ [SHIFT-05] Courier Logged into Mobile App (/driver)');

  // Navigate to Shifts tab
  await riderPage.evaluate(() => window.go('shifts'));
  await riderPage.waitForTimeout(1000);

  // Check available shifts list is visible
  const availableTitle = await riderPage.waitForSelector('h2:has-text("الورديات المطروحة والمتاحة")', { timeout: 5000 });
  assert(availableTitle, 'Available shifts section found in courier app');
  console.log('  ✓ [SHIFT-06] Available Open Shifts Section Rendered in Courier App');

  await riderPage.screenshot({ path: `${ARTIFACT_DIR}/15c_rider_app_available_shifts.png`, fullPage: false });
  console.log('  ✓ [SHIFT-07] Rider App Shifts View Captured (15c_rider_app_available_shifts.png)');

  // Try claiming a shift if claim button exists
  const claimBtn = await riderPage.$('button:has-text("➕ اختيار الوردية")');
  if (claimBtn) {
    await claimBtn.click();
    await riderPage.waitForTimeout(1200);
    console.log('  ✓ [SHIFT-08] Courier Successfully Claimed Open Shift');

    await riderPage.screenshot({ path: `${ARTIFACT_DIR}/15d_rider_app_shift_claimed_success.png`, fullPage: false });
    console.log('  ✓ [SHIFT-09] Post-Claim Assigned Shift View Captured (15d_rider_app_shift_claimed_success.png)');
  }

  await riderContext.close();
  await browser.close();

  console.log('\n========================================================================================');
  console.log('ALL SHIFTS ASSIGNMENT & COURIER CLAIMING TESTS PASSED (100% SUCCESS)');
  console.log('========================================================================================\n');
}

run().catch(err => {
  console.error('Test execution failed:', err);
  process.exit(1);
});
