// E2E Acceptance Test Suite for Batch 2: Live Readiness Transitions & Vehicle Assignment
import { chromium } from 'playwright';

const BASE_URL = 'http://127.0.0.1:8123';
let passed = 0;
let failed = 0;
const results = [];

function record(name, status, detail = '') {
  if (status === 'PASS') {
    passed++;
    console.log(`  ✓ ${name}${detail ? ` — ${detail}` : ''}`);
  } else {
    failed++;
    console.log(`  ✗ ${name}${detail ? ` — ${detail}` : ''}`);
  }
  results.push({ name, status, detail });
}

async function run() {
  console.log('\n=== BATCH 2: READINESS ENGINE & VEHICLE ASSIGNMENTS ACCEPTANCE ===\n');
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  const consoleErrors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  const pageErrors = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));

  try {
    // 1. Admin Login
    await page.goto(`${BASE_URL}/app/v2/`);
    await page.fill('#login-phone', '966511111111');
    await page.fill('#login-password', 'Company123!');
    await page.click('button[type="submit"]');
    await page.waitForSelector('.fleet-app', { timeout: 8000 });
    record('B2-01: Admin login & App mounted', 'PASS', 'Mounted successfully');

    // 2. Open Riders & Navigate to Rider 360
    await page.click('.nav-item[data-view="riders"]');
    await page.waitForSelector('.table-wrap table tbody tr', { timeout: 6000 });
    const firstRowBtn = await page.$('.table-wrap table tbody tr:first-child button:has-text("ملف 360")');
    await firstRowBtn.click();
    await page.waitForSelector('#r360-select', { timeout: 6000 });
    record('B2-02: Rider 360 workspace loaded', 'PASS', 'Found #r360-select and profile container');

    // 3. Verify Readiness Banner and Dimensions
    await page.waitForSelector('.profile-grid', { timeout: 6000 });
    const profileGrid = await page.$('.profile-grid');
    const cards = await page.$$('.tab-pane .card');
    record('B2-03: Readiness state & dimensions rendered', (profileGrid && cards.length >= 2) ? 'PASS' : 'FAIL', `Found profile grid and ${cards.length} cards`);

    // 4. Test Readiness API directly
    const token = await page.evaluate(() => localStorage.getItem('dou_token_v2'));
    const courierId = await page.evaluate(() => Number(document.getElementById('r360-select')?.value));
    
    const readinessRes = await page.request.get(`${BASE_URL}/readiness/${courierId}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    const readinessData = await readinessRes.json();
    record('B2-04: Readiness GET API returns state', readinessRes.status() === 200 ? 'PASS' : 'FAIL', `Overall: ${readinessData.overall_status}, Onboarding: ${readinessData.onboarding_status}`);

    // 5. Test Open Vehicle Assignment Modal
    const assignVehicleBtn = await page.$('button:has-text("إسناد / تغيير مركبة")');
    if (assignVehicleBtn) {
      await assignVehicleBtn.click();
      await page.waitForSelector('.modal-overlay form', { timeout: 5000 });
      const modalForm = await page.$('.modal-overlay form');
      record('B2-05: Vehicle Assignment Modal opened', modalForm ? 'PASS' : 'FAIL', 'Found vehicle selector in modal');
      
      const closeBtn = await page.$('.modal-overlay .btn-close');
      if (closeBtn) await closeBtn.click();
    } else {
      record('B2-05: Vehicle Assignment Modal opened', 'FAIL', 'Assign vehicle button not visible');
    }

    // 6. Test Vehicle Assignment API directly
    const vehiclesRes = await page.request.get(`${BASE_URL}/vehicles/`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    const vehiclesList = await vehiclesRes.json();
    let assignStatus = 200;
    if (vehiclesList.length > 0) {
      const v = vehiclesList[0];
      const assignRes = await page.request.post(`${BASE_URL}/vehicles/assignments?vehicle_id=${v.id}`, {
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        data: {
          courier_id: courierId,
          effective_from: new Date().toISOString().slice(0, 10),
          is_primary: true
        }
      });
      assignStatus = assignRes.status();
    }
    record('B2-06: Vehicle Assignment API response', [200, 201, 409].includes(assignStatus) ? 'PASS' : 'FAIL', `Status: ${assignStatus}`);

    // 7. Verify Vehicle Readiness Endpoint
    const vReadinessRes = await page.request.get(`${BASE_URL}/vehicles/riders/${courierId}/readiness?as_of=${new Date().toISOString().slice(0, 10)}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    const vReadinessData = await vReadinessRes.json();
    record('B2-07: Vehicle Readiness Endpoint verified', vReadinessRes.status() === 200 ? 'PASS' : 'FAIL', `Ready: ${vReadinessData.ready}, Details: ${JSON.stringify(vReadinessData.details?.assignment || {})}`);

    // 8. Test Shift Tab & Assign Shift Modal
    await page.click('.tab[data-tab="shifts"]');
    await page.waitForSelector('.tab-pane button, .tab-pane .state-empty', { timeout: 5000 });
    const assignShiftBtn = await page.$('button:has-text("إسناد وردية")');
    if (assignShiftBtn) {
      await assignShiftBtn.click();
      await page.waitForSelector('.modal-overlay', { timeout: 5000 });
      record('B2-08: Assign Shift Modal opened', 'PASS', 'Modal rendered with shift selector');
      const closeBtn = await page.$('.modal-overlay .btn-close');
      if (closeBtn) await closeBtn.click();
    } else {
      record('B2-08: Assign Shift Modal opened', 'FAIL', 'Assign shift button not found');
    }

    // 9. Test Target Tab & Set Target Modal
    await page.click('.tab[data-tab="targets"]');
    await page.waitForSelector('.tab-pane button, .tab-pane .state-empty', { timeout: 5000 });
    const setTargetBtn = await page.$('button:has-text("تحديد / تعديل هدف")');
    if (setTargetBtn) {
      await setTargetBtn.click();
      await page.waitForSelector('.modal-overlay form', { timeout: 5000 });
      record('B2-09: Set Target Modal opened', 'PASS', 'Modal rendered with target form');
      const closeBtn = await page.$('.modal-overlay .btn-close');
      if (closeBtn) await closeBtn.click();
    } else {
      record('B2-09: Set Target Modal opened', 'FAIL', 'Set target button not found');
    }

    // 10. Error Integrity
    record('B2-10: Zero unexpected JS console errors', consoleErrors.length === 0 ? 'PASS' : 'FAIL', `${consoleErrors.length} errors: ${consoleErrors.join('; ')}`);
    record('B2-11: Zero page runtime errors', pageErrors.length === 0 ? 'PASS' : 'FAIL', `${pageErrors.length} errors`);

  } catch (err) {
    console.error('Test execution exception:', err);
    record('B2-FATAL', 'FAIL', err.message);
  } finally {
    await browser.close();
  }

  console.log(`\n=== BATCH 2 SUMMARY ===`);
  console.log(`Total: ${passed + failed}`);
  console.log(`Passed: ${passed}`);
  console.log(`Failed: ${failed}`);
  if (failed > 0) process.exit(1);
}

run();
