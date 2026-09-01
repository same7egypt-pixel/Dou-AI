import { chromium } from 'playwright';

const BASE_URL = 'http://127.0.0.1:8123';
const ARTIFACT_DIR = '/Users/sameh/.gemini/antigravity/brain/056265f0-e866-44a5-a8b3-03743ced3176';

async function run() {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // 1. Login
  await page.goto(`${BASE_URL}/app/v2/`);
  await page.fill('#login-phone', '966511111111');
  await page.fill('#login-password', 'Company123!');
  await page.click('button[type="submit"]');
  await page.waitForSelector('.fleet-app', { timeout: 8000 });

  // 2. Riders Roster with Action Buttons
  await page.evaluate(() => window.go('riders'));
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${ARTIFACT_DIR}/10a_riders_crud_actions.png`, fullPage: false });
  console.log('Captured 10a_riders_crud_actions.png');

  // Open Edit Rider Modal
  const editRiderBtn = await page.$('table button:has-text("✏️ تعديل")');
  if (editRiderBtn) {
    await editRiderBtn.click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${ARTIFACT_DIR}/10b_edit_rider_modal.png`, fullPage: false });
    console.log('Captured 10b_edit_rider_modal.png');
    await page.evaluate(() => document.querySelectorAll('.modal-overlay').forEach(m => m.remove()));
    await page.waitForTimeout(400);
  }

  // 3. Vehicles Registry with Edit/Delete
  const vehBtn = await page.$('#btn-vehicles-fleet, button:has-text("سجل المركبات")');
  if (vehBtn) {
    await vehBtn.click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${ARTIFACT_DIR}/10c_vehicles_crud_modal.png`, fullPage: false });
    console.log('Captured 10c_vehicles_crud_modal.png');
    await page.evaluate(() => document.querySelectorAll('.modal-overlay').forEach(m => m.remove()));
    await page.waitForTimeout(400);
  }

  // 4. Capacity & Contracts with Full CRUD
  await page.evaluate(() => window.go('capacity'));
  await page.waitForTimeout(1000);
  const contractsTab = await page.$('.tab:has-text("العقود"), button:has-text("العقود")');
  if (contractsTab) {
    await contractsTab.click();
    await page.waitForTimeout(1000);
  }
  await page.screenshot({ path: `${ARTIFACT_DIR}/11a_contracts_crud_cards.png`, fullPage: false });
  console.log('Captured 11a_contracts_crud_cards.png');

  // Open Supervisors Management Modal
  const supMgmtBtn = await page.$('button:has-text("👔 إدارة المشرفين")');
  if (supMgmtBtn) {
    await supMgmtBtn.click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${ARTIFACT_DIR}/11c_supervisors_management_modal.png`, fullPage: false });
    console.log('Captured 11c_supervisors_management_modal.png');
    await page.evaluate(() => document.querySelectorAll('.modal-overlay').forEach(m => m.remove()));
    await page.waitForTimeout(400);
  }

  // Open Edit Contract Modal
  const editContractBtn = await page.$('.card button:has-text("✏️ تعديل")');
  if (editContractBtn) {
    await editContractBtn.click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${ARTIFACT_DIR}/11b_edit_contract_modal.png`, fullPage: false });
    console.log('Captured 11b_edit_contract_modal.png');
    await page.evaluate(() => document.querySelectorAll('.modal-overlay').forEach(m => m.remove()));
    await page.waitForTimeout(400);
  }

  // 5. Payroll Bonus Plans with Edit & Delete
  await page.evaluate(() => window.go('payroll'));
  await page.waitForTimeout(1000);
  const bonusSubTab = await page.$('.tab:has-text("البونص"), button:has-text("البونص")');
  if (bonusSubTab) {
    await bonusSubTab.click();
    await page.waitForTimeout(1000);
  }
  await page.screenshot({ path: `${ARTIFACT_DIR}/12a_bonus_plans_crud_table.png`, fullPage: false });
  console.log('Captured 12a_bonus_plans_crud_table.png');

  // Open Edit Bonus Modal
  const editBonusBtn = await page.$('table button:has-text("✏️ تعديل")');
  if (editBonusBtn) {
    await editBonusBtn.click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${ARTIFACT_DIR}/12b_edit_bonus_plan_modal.png`, fullPage: false });
    console.log('Captured 12b_edit_bonus_plan_modal.png');
    await page.evaluate(() => document.querySelectorAll('.modal-overlay').forEach(m => m.remove()));
  }

  await browser.close();
  console.log('All visual screenshots captured successfully.');
}

run().catch(err => {
  console.error('Visual capture error:', err);
  process.exit(1);
});
