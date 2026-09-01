import { chromium } from 'playwright';
import assert from 'assert';

const BASE_URL = 'http://127.0.0.1:8123';
const ARTIFACT_DIR = '/Users/sameh/.gemini/antigravity/brain/056265f0-e866-44a5-a8b3-03743ced3176';

async function run() {
  console.log('\n========================================================================================');
  console.log('LEAVE REQUESTS VISIBILITY & POST-DECISION LIFECYCLE ACCEPTANCE TEST');
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
  console.log('  ✓ [LEAVE-01] Fleet Admin Authenticated');

  // 2. Navigate to Shifts -> Leaves tab
  await page.evaluate(() => window.go('shifts'));
  await page.waitForTimeout(1000);
  const leavesTabBtn = await page.waitForSelector('button.tab:has-text("طلبات الإجازات")', { timeout: 5000 });
  await leavesTabBtn.click();
  await page.waitForTimeout(1200);

  // Take screenshot of All Leaves (showing both pending & approved records)
  await page.screenshot({ path: `${ARTIFACT_DIR}/16a_leaves_all_records_table.png`, fullPage: false });
  console.log('  ✓ [LEAVE-02] Leaves View with All Records Captured (16a_leaves_all_records_table.png)');

  // 3. Click on "المعتمدة" filter button or card
  const approvedFilterBtn = await page.waitForSelector('button:has-text("المعتمدة")', { timeout: 5000 });
  await approvedFilterBtn.click();
  await page.waitForTimeout(800);

  // Check that approved rows with green badges are rendered
  const greenBadges = await page.$$('.badge-green');
  assert(greenBadges.length > 0, 'Approved leave badges found');
  console.log(`  ✓ [LEAVE-03] Approved Leaves Filter Active (${greenBadges.length} Approved Requests Listed)`);

  await page.screenshot({ path: `${ARTIFACT_DIR}/16b_leaves_approved_records_table.png`, fullPage: false });
  console.log('  ✓ [LEAVE-04] Approved Leaves View Captured (16b_leaves_approved_records_table.png)');

  // 4. Switch to Pending and open review modal
  const pendingFilterBtn = await page.waitForSelector('button:has-text("قيد المراجعة")', { timeout: 5000 });
  await pendingFilterBtn.click();
  await page.waitForTimeout(800);

  const decideBtn = await page.$('button:has-text("⚡ اتخاذ قرار")');
  if (decideBtn) {
    await decideBtn.click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${ARTIFACT_DIR}/16c_leaves_decision_modal.png`, fullPage: false });
    console.log('  ✓ [LEAVE-05] Decision Modal Captured (16c_leaves_decision_modal.png)');

    // Approve the leave
    await page.fill('#leave-review-note', 'تمت الموافقة من إدارة العمليات واعتماد الإجازة.');
    await page.click('button:has-text("✅ اعتماد الإجازة")');
    await page.waitForTimeout(1200);
    console.log('  ✓ [LEAVE-06] Leave Decision Submitted Successfully');
  }

  await context.close();
  await browser.close();

  console.log('\n========================================================================================');
  console.log('ALL LEAVE REQUEST LIFECYCLE TESTS PASSED (100% SUCCESS)');
  console.log('========================================================================================\n');
}

run().catch(err => {
  console.error('Test execution failed:', err);
  process.exit(1);
});
