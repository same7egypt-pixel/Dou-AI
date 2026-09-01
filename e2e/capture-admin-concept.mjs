import { chromium } from 'playwright';

const ARTIFACT_DIR = '/Users/sameh/.gemini/antigravity/brain/056265f0-e866-44a5-a8b3-03743ced3176';

async function run() {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });

  await page.goto(`file://${ARTIFACT_DIR}/admin_dashboard_concept.html`);
  await page.waitForTimeout(600);

  // 1. Overview tab screenshot
  await page.screenshot({ path: `${ARTIFACT_DIR}/20a_admin_master_mission_control.png`, fullPage: false });
  console.log('  ✓ [ADMIN-01] Captured 20a_admin_master_mission_control.png');

  // 2. Tenants tab screenshot
  await page.click('#tab-btn-tenants');
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${ARTIFACT_DIR}/20b_admin_tenants_multi_tenant.png`, fullPage: false });
  console.log('  ✓ [ADMIN-02] Captured 20b_admin_tenants_multi_tenant.png');

  // 3. Billing tab screenshot
  await page.click('#tab-btn-billing');
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${ARTIFACT_DIR}/20c_admin_saas_billing.png`, fullPage: false });
  console.log('  ✓ [ADMIN-03] Captured 20c_admin_saas_billing.png');

  // 4. Audit tab screenshot
  await page.click('#tab-btn-audit');
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${ARTIFACT_DIR}/20d_admin_audit_governance.png`, fullPage: false });
  console.log('  ✓ [ADMIN-04] Captured 20d_admin_audit_governance.png');

  await browser.close();
  console.log('  ✓ Admin Concept Visuals Captured Successfully');
}

run().catch(console.error);
