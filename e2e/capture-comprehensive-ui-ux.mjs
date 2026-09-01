import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE_URL = 'http://127.0.0.1:8123';
const ARTIFACT_DIR = '/Users/sameh/.gemini/antigravity/brain/056265f0-e866-44a5-a8b3-03743ced3176';

async function run() {
  console.log('\n======================================================================');
  console.log('COMPREHENSIVE UI/UX CAPTURE & AUDIT ACROSS ALL MODULES & MODALS');
  console.log('======================================================================\n');

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // Login as Company Admin
  await page.goto(`${BASE_URL}/app/v2/`);
  await page.fill('#login-phone', '966511111111');
  await page.fill('#login-password', 'Company123!');
  await page.click('button[type="submit"]');
  await page.waitForSelector('.fleet-app', { timeout: 8000 });

  // 1. Command Center
  await page.evaluate(() => window.go('commandCenter'));
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, '01_command_center.png') });
  console.log('✓ 01_command_center.png');

  // 2. Riders Roster
  await page.evaluate(() => window.go('riders'));
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, '02_riders_roster.png') });
  console.log('✓ 02_riders_roster.png');

  // 2b. Add Rider Cascading Modal
  const addRiderBtn = await page.$('#btn-add-rider, button:has-text("+ إضافة سائق")');
  if (addRiderBtn) {
    await addRiderBtn.click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(ARTIFACT_DIR, '02b_add_rider_hierarchy_modal.png') });
    console.log('✓ 02b_add_rider_hierarchy_modal.png');
    await page.evaluate(() => document.querySelectorAll('.modal-overlay').forEach(m => m.remove()));
    await page.waitForTimeout(300);
  }

  // 2c. Vehicles Registry Modal
  const vehBtn = await page.$('#btn-vehicles-fleet, button:has-text("🚗 أسطول المركبات")');
  if (vehBtn) {
    await vehBtn.click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(ARTIFACT_DIR, '02c_vehicles_fleet_modal.png') });
    console.log('✓ 02c_vehicles_fleet_modal.png');
    await page.evaluate(() => document.querySelectorAll('.modal-overlay').forEach(m => m.remove()));
    await page.waitForTimeout(300);
  }

  // 3. Rider 360 Profile
  await page.evaluate(() => window.go('rider360'));
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, '03_rider360_profile.png') });
  console.log('✓ 03_rider360_profile.png');

  // 4. Shifts & Attendance
  await page.evaluate(() => window.go('shifts'));
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, '04_shifts_attendance.png') });
  console.log('✓ 04_shifts_attendance.png');

  // 4b. Attendance Policies Modal
  const attPolBtn = await page.$('#btn-attendance-policies, button:has-text("سياسات خصم الحضور")');
  if (attPolBtn) {
    await attPolBtn.click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(ARTIFACT_DIR, '04b_attendance_policies_modal.png') });
    console.log('✓ 04b_attendance_policies_modal.png');
    await page.evaluate(() => document.querySelectorAll('.modal-overlay').forEach(m => m.remove()));
    await page.waitForTimeout(300);
  }

  // 5. Needs Attention
  await page.evaluate(() => window.go('needsAttention'));
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, '05_needs_attention.png') });
  console.log('✓ 05_needs_attention.png');

  // 6. Capacity & Ecosystem - Subtab 1: Capacity Planning
  await page.evaluate(() => window.go('capacity'));
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, '06a_capacity_planning.png') });
  console.log('✓ 06a_capacity_planning.png');

  // 6b. Capacity - Subtab 2: Contracts & Operating Branches
  const contractsTab = await page.$('.tab:has-text("العقود")');
  if (contractsTab) {
    await contractsTab.click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(ARTIFACT_DIR, '06b_contracts_and_branches.png') });
    console.log('✓ 06b_contracts_and_branches.png');
  }

  // 7. Reports & Metabase BI - Subtab 1: Catalog
  await page.evaluate(() => window.go('reports'));
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, '07a_reports_catalog.png') });
  console.log('✓ 07a_reports_catalog.png');

  // 7b. Reports - Subtab 2: Metabase Dashboards
  const metabaseTab = await page.$('.tab:has-text("لوحات Metabase")');
  if (metabaseTab) {
    await metabaseTab.click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(ARTIFACT_DIR, '07b_reports_metabase_dashboards.png') });
    console.log('✓ 07b_reports_metabase_dashboards.png');
  }

  // 8. Payroll & Financial - Subtab 1: Payroll Summary & WPS
  await page.evaluate(() => window.go('payroll'));
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, '08a_payroll_summary_and_wps.png') });
  console.log('✓ 08a_payroll_summary_and_wps.png');

  // 8b. Payroll - Subtab 2: Bonus Plans & Leaderboard
  const bonusTab = await page.$('.tab:has-text("البونص")');
  if (bonusTab) {
    await bonusTab.click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(ARTIFACT_DIR, '08b_payroll_bonus_plans.png') });
    console.log('✓ 08b_payroll_bonus_plans.png');
  }

  // 9. DOU AI Workspace
  await page.evaluate(() => window.go('douai'));
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(ARTIFACT_DIR, '09_dou_ai_workspace.png') });
  console.log('✓ 09_dou_ai_workspace.png');

  await browser.close();
  console.log('\n🎉 Comprehensive visual suite captured successfully!');
}

run();
