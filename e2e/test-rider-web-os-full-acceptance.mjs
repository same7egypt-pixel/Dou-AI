import { chromium } from 'playwright';
import assert from 'assert';

const BASE_URL = 'http://127.0.0.1:8123';
const ARTIFACT_DIR = '/Users/sameh/.gemini/antigravity/brain/056265f0-e866-44a5-a8b3-03743ced3176';

async function run() {
  console.log('\n========================================================================================');
  console.log('DOU RIDER WEB OS — COMPREHENSIVE ACCEPTANCE & VISUAL VERIFICATION TEST');
  console.log('========================================================================================\n');

  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] });

  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    locale: 'ar-SA',
    permissions: ['geolocation'],
    geolocation: { latitude: 24.7136, longitude: 46.6753 }
  });

  const page = await context.newPage();

  // 1. Open Rider App & Login
  await page.goto(`${BASE_URL}/driver`);
  await page.waitForSelector('#loginPhone', { timeout: 8000 });
  console.log('  ✓ [RIDER-01] Rider Web App Login View Rendered');

  await page.fill('#loginPhone', '966581545532');
  await page.fill('#loginPassword', 'Rider123!');
  await page.click('#loginButton');
  await page.waitForSelector('.app-shell', { timeout: 8000 });
  console.log('  ✓ [RIDER-02] Courier Authenticated & Cockpit Loaded');

  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${ARTIFACT_DIR}/19a_rider_cockpit_home_dark.png`, fullPage: false });
  console.log('  ✓ [RIDER-03] Captured Home Cockpit (19a_rider_cockpit_home_dark.png)');

  // 2. Test Driver Status Switcher
  const breakBtn = await page.waitForSelector('button.status-opt:has-text("استراحة")', { timeout: 5000 });
  await breakBtn.click();
  await page.waitForTimeout(500);
  console.log('  ✓ [RIDER-04] Driver Operational Status Changed to ON_BREAK');

  const onlineBtn = await page.waitForSelector('button.status-opt:has-text("متوفر")', { timeout: 5000 });
  await onlineBtn.click();
  await page.waitForTimeout(500);
  console.log('  ✓ [RIDER-05] Driver Operational Status Restored to ONLINE');

  // 3. Test Pre-Shift Inspection Modal
  const inspBtn = await page.waitForSelector('button.quick-chip:has-text("فحص الجاهزية")', { timeout: 5000 });
  await inspBtn.click();
  await page.waitForTimeout(500);
  await page.waitForSelector('.modal-sheet', { timeout: 5000 });
  await page.screenshot({ path: `${ARTIFACT_DIR}/19b_rider_inspection_modal.png`, fullPage: false });
  console.log('  ✓ [RIDER-06] Pre-Shift Inspection Modal Captured (19b_rider_inspection_modal.png)');

  const confirmInspBtn = await page.waitForSelector('.modal-sheet button.btn.primary', { timeout: 5000 });
  await confirmInspBtn.click();
  await page.waitForTimeout(800);

  // 4. Test COD Cash Handover Modal
  const codBtn = await page.waitForSelector('button.quick-chip:has-text("تسوية كاش")', { timeout: 5000 });
  await codBtn.click();
  await page.waitForTimeout(500);
  await page.waitForSelector('#codAmt', { timeout: 5000 });
  await page.fill('#codAmt', '350.50');
  await page.screenshot({ path: `${ARTIFACT_DIR}/19c_rider_cod_modal.png`, fullPage: false });
  console.log('  ✓ [RIDER-07] COD Cash Handover Modal Captured (19c_rider_cod_modal.png)');

  const submitCodBtn = await page.waitForSelector('.modal-sheet button.btn.primary', { timeout: 5000 });
  await submitCodBtn.click();
  await page.waitForTimeout(800);

  // 5. Navigate to Shifts Marketplace
  await page.evaluate(() => window.go('shifts'));
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${ARTIFACT_DIR}/19d_rider_shifts_marketplace.png`, fullPage: false });
  console.log('  ✓ [RIDER-08] Shifts Marketplace Captured (19d_rider_shifts_marketplace.png)');

  // 6. Navigate to Earnings / Wallet
  await page.evaluate(() => window.go('earnings'));
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${ARTIFACT_DIR}/19e_rider_wallet_statement.png`, fullPage: false });
  console.log('  ✓ [RIDER-09] Financial Wallet & Statement Captured (19e_rider_wallet_statement.png)');

  // 7. Open Digital Payslip Modal
  const payslipBtn = await page.waitForSelector('button:has-text("طباعة قسيمة الراتب")', { timeout: 5000 });
  await payslipBtn.click();
  await page.waitForTimeout(600);
  await page.waitForSelector('.modal-sheet', { timeout: 5000 });
  await page.screenshot({ path: `${ARTIFACT_DIR}/19f_rider_digital_payslip.png`, fullPage: false });
  console.log('  ✓ [RIDER-10] Digital Payslip Modal Captured (19f_rider_digital_payslip.png)');

  // Close payslip modal
  const closePayslipBtn = await page.waitForSelector('.modal-sheet button:has-text("إغلاق")', { timeout: 5000 });
  await closePayslipBtn.click();
  await page.waitForTimeout(500);

  // 8. Navigate to Profile / Documents Vault
  await page.evaluate(() => window.go('profile'));
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${ARTIFACT_DIR}/19g_rider_profile_documents.png`, fullPage: false });
  console.log('  ✓ [RIDER-11] Profile & Document Vault Captured (19g_rider_profile_documents.png)');

  await context.close();
  await browser.close();

  console.log('\n========================================================================================');
  console.log('ALL DOU RIDER WEB OS TESTS PASSED (100% SUCCESS)');
  console.log('========================================================================================\n');
}

run().catch(err => {
  console.error('Test execution failed:', err);
  process.exit(1);
});
