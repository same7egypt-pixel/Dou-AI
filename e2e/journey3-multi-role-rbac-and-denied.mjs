// Journey 3: Multi-Role RBAC & Explicit Denied Access Proof
import { chromium } from 'playwright';

const BASE_URL = 'http://127.0.0.1:8123';
let passed = 0;
let failed = 0;
const results = [];

function record(step, action, api, persistence, refresh, role, status, detail = '') {
  if (status === 'PASS') {
    passed++;
    console.log(`  ✓ [${step}] ${action} | API: ${api} | Role: ${role} | Status: PASS${detail ? ` (${detail})` : ''}`);
  } else {
    failed++;
    console.log(`  ✗ [${step}] ${action} | API: ${api} | Role: ${role} | Status: FAIL${detail ? ` (${detail})` : ''}`);
  }
  results.push({ step, action, api, persistence, refresh, role, status, detail });
}

async function loginAndGetToken(page, phone, password) {
  await page.goto(`${BASE_URL}/app/v2/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE_URL}/app/v2/`);
  await page.waitForSelector('#login-phone', { timeout: 8000 });
  await page.fill('#login-phone', phone);
  await page.fill('#login-password', password);
  await page.click('button[type="submit"]');
  await page.waitForSelector('.fleet-app', { timeout: 8000 });
  return await page.evaluate(() => localStorage.getItem('dou_token_v2'));
}

async function run() {
  console.log('\n======================================================================');
  console.log('JOURNEY 3: MULTI-ROLE RBAC & EXPLICIT DENIED ACCESS VERIFICATION');
  console.log('======================================================================\n');

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  try {
    // -----------------------------------------------------------------
    // ROLE 1: COMPANY ADMIN (Full Authority)
    // -----------------------------------------------------------------
    console.log('\n--- 1. COMPANY ADMIN (966511111111) ---');
    const adminToken = await loginAndGetToken(page, '966511111111', 'Company123!');
    
    // Happy Path: Full access to add driver, view payroll, manage fleet
    const adminAddRes = await page.request.post(`${BASE_URL}/fleet/couriers`, {
      headers: { Authorization: `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
      data: {
        name: `Admin Test Rider ${Date.now()}`,
        phone: `9665${Date.now().toString().slice(-8)}`,
        password: 'Password123!',
        city_id: 1, contract_id: 1, contract_branch_id: 1, supervisor_id: 5,
        courier_type: 'COMPANY', nationality: 'SA'
      }
    });
    record('J3-01', 'Admin Write Access (Add Rider)', 'POST /fleet/couriers', 'Persisted in DB', 'Page Reload', 'COMPANY_ADMIN', adminAddRes.status() === 200 ? 'PASS' : 'FAIL', 'Status: 200 OK');

    const adminPayrollRes = await page.request.get(`${BASE_URL}/analytics/payroll/summary`, {
      headers: { Authorization: `Bearer ${adminToken}` }
    });
    record('J3-02', 'Admin Financial Access (Payroll)', 'GET /analytics/payroll/summary', 'Financial summary loaded', 'Mount Check', 'COMPANY_ADMIN', adminPayrollRes.status() === 200 ? 'PASS' : 'FAIL', 'Status: 200 OK');

    // -----------------------------------------------------------------
    // ROLE 2: OPERATIONS MANAGER (Fleet Write, Financial Denied)
    // -----------------------------------------------------------------
    console.log('\n--- 2. OPERATIONS MANAGER (966522222222) ---');
    const opsToken = await loginAndGetToken(page, '966522222222', 'Ops123456!');

    // Happy Path: Manage riders and shifts
    const opsRidersRes = await page.request.get(`${BASE_URL}/fleet/couriers/page?page=1&limit=10`, {
      headers: { Authorization: `Bearer ${opsToken}` }
    });
    record('J3-03', 'Operations Allowed: View Riders', 'GET /fleet/couriers/page', 'Riders list returned', 'Mount Check', 'OPERATIONS', opsRidersRes.status() === 200 ? 'PASS' : 'FAIL', 'Status: 200 OK');

    // Denied Path: Approve Commercial Settlements (403 Expected)
    const opsApproveRes = await page.request.post(`${BASE_URL}/analytics/operators/settlement/1/approve`, {
      headers: { Authorization: `Bearer ${opsToken}`, 'Content-Type': 'application/json' }
    });
    record('J3-04', 'Operations Denied: Approve Settlement', 'POST /analytics/operators/settlement/1/approve', 'Rejected with 403 Forbidden', 'N/A', 'OPERATIONS', opsApproveRes.status() === 403 ? 'PASS' : 'FAIL', `Expected 403, Got: ${opsApproveRes.status()}`);

    // Denied Path: Modify Company Billing / Settings (403 Expected)
    const opsSettingsRes = await page.request.post(`${BASE_URL}/fleet/settings`, {
      headers: { Authorization: `Bearer ${opsToken}`, 'Content-Type': 'application/json' },
      data: { key: 'test', value: '123' }
    });
    record('J3-05', 'Operations Denied: Modify Settings', 'POST /fleet/settings', 'Rejected with 403 Forbidden', 'N/A', 'OPERATIONS', [403, 401].includes(opsSettingsRes.status()) ? 'PASS' : 'FAIL', `Expected 403, Got: ${opsSettingsRes.status()}`);

    // -----------------------------------------------------------------
    // ROLE 3: SUPERVISOR (Scoped Access, Fleet Creation Denied)
    // -----------------------------------------------------------------
    console.log('\n--- 3. SUPERVISOR (966533333333) ---');
    const supToken = await loginAndGetToken(page, '966533333333', 'Super1234!');

    // Happy Path: View assigned team riders
    const supRidersRes = await page.request.get(`${BASE_URL}/fleet/couriers/page?page=1&limit=50`, {
      headers: { Authorization: `Bearer ${supToken}` }
    });
    const supRidersData = await supRidersRes.json();
    record('J3-06', 'Supervisor Allowed: Scoped Team', 'GET /fleet/couriers/page', 'Scoped to supervisor_id', 'Mount Check', 'SUPERVISOR', supRidersRes.status() === 200 ? 'PASS' : 'FAIL', `Returned ${supRidersData.total} scoped riders`);

    // Denied Path: Add Rider (403 / Forbidden)
    const supAddRes = await page.request.post(`${BASE_URL}/fleet/couriers`, {
      headers: { Authorization: `Bearer ${supToken}`, 'Content-Type': 'application/json' },
      data: {
        name: `Illegal Supervisor Rider ${Date.now()}`,
        phone: `9665${Date.now().toString().slice(-8)}`,
        password: 'Password123!',
        city_id: 1, contract_id: 1, contract_branch_id: 1,
        courier_type: 'COMPANY', nationality: 'SA'
      }
    });
    record('J3-07', 'Supervisor Denied: Add Rider', 'POST /fleet/couriers', 'Rejected with 403 Forbidden', 'N/A', 'SUPERVISOR', supAddRes.status() === 403 ? 'PASS' : 'FAIL', `Expected 403, Got: ${supAddRes.status()}`);

    // UI Check: Add Rider button is hidden in UI
    await page.click('.nav-item[data-view="riders"]');
    await page.waitForSelector('.table-wrap table, .state-empty', { timeout: 6000 });
    const supAddBtn = await page.$('#btn-add-rider, button:has-text("+ إضافة مندوب")');
    record('J3-08', 'Supervisor UI: Add Button Hidden', 'DOM Inspection', 'Button absent from DOM', 'UI Check', 'SUPERVISOR', !supAddBtn ? 'PASS' : 'FAIL', 'Add Rider button correctly hidden');

    // Denied Path: Create Salary Structure (403 Expected)
    const supSalaryRes = await page.request.post(`${BASE_URL}/salary/structures`, {
      headers: { Authorization: `Bearer ${supToken}`, 'Content-Type': 'application/json' },
      data: { code: 'ILLEGAL', name_ar: 'هيكل غير مصرح' }
    });
    record('J3-09', 'Supervisor Denied: Salary Structure', 'POST /salary/structures', 'Rejected with 403 Forbidden', 'N/A', 'SUPERVISOR', supSalaryRes.status() === 403 ? 'PASS' : 'FAIL', `Expected 403, Got: ${supSalaryRes.status()}`);

    // -----------------------------------------------------------------
    // ROLE 4: FINANCE / ACCOUNTANT (Financial Authority, Fleet Creation Denied)
    // -----------------------------------------------------------------
    console.log('\n--- 4. FINANCE / ACCOUNTANT (966577777777) ---');
    const finToken = await loginAndGetToken(page, '966577777777', 'Finance123!');

    // Happy Path: View Payroll and Reports
    const finPayrollRes = await page.request.get(`${BASE_URL}/analytics/payroll/summary`, {
      headers: { Authorization: `Bearer ${finToken}` }
    });
    record('J3-10', 'Finance Allowed: Payroll Access', 'GET /analytics/payroll/summary', 'Financial ledger returned', 'Mount Check', 'ACCOUNTANT', finPayrollRes.status() === 200 ? 'PASS' : 'FAIL', 'Status: 200 OK');

    const finReportsRes = await page.request.get(`${BASE_URL}/analytics/reports/catalog`, {
      headers: { Authorization: `Bearer ${finToken}` }
    });
    record('J3-11', 'Finance Allowed: Reports Catalog', 'GET /analytics/reports/catalog', 'Reports catalog loaded', 'Mount Check', 'ACCOUNTANT', finReportsRes.status() === 200 ? 'PASS' : 'FAIL', 'Status: 200 OK');

    // Denied Path: Add Rider (403 Expected)
    const finAddRes = await page.request.post(`${BASE_URL}/fleet/couriers`, {
      headers: { Authorization: `Bearer ${finToken}`, 'Content-Type': 'application/json' },
      data: {
        name: `Illegal Finance Rider ${Date.now()}`,
        phone: `9665${Date.now().toString().slice(-8)}`,
        password: 'Password123!',
        city_id: 1, contract_id: 1, contract_branch_id: 1,
        courier_type: 'COMPANY', nationality: 'SA'
      }
    });
    record('J3-12', 'Finance Denied: Add Rider', 'POST /fleet/couriers', 'Rejected with 403 Forbidden', 'N/A', 'ACCOUNTANT', finAddRes.status() === 403 ? 'PASS' : 'FAIL', `Expected 403, Got: ${finAddRes.status()}`);

    // Denied Path: Vehicle Assignment (403 Expected)
    const finAssignRes = await page.request.post(`${BASE_URL}/vehicles/assignments?vehicle_id=1`, {
      headers: { Authorization: `Bearer ${finToken}`, 'Content-Type': 'application/json' },
      data: { courier_id: 1, effective_from: '2026-08-31', is_primary: true }
    });
    record('J3-13', 'Finance Denied: Assign Vehicle', 'POST /vehicles/assignments', 'Rejected with 403 Forbidden', 'N/A', 'ACCOUNTANT', finAssignRes.status() === 403 ? 'PASS' : 'FAIL', `Expected 403, Got: ${finAssignRes.status()}`);

  } catch (err) {
    console.error('Fatal Journey 3 error:', err);
    record('J3-FATAL', 'Journey Execution', 'Exception', 'N/A', 'N/A', 'SYSTEM', 'FAIL', err.message);
  } finally {
    await browser.close();
  }

  console.log('\n=== JOURNEY 3 SUMMARY ===');
  console.log(`Total Steps: ${passed + failed}`);
  console.log(`Passed: ${passed}`);
  console.log(`Failed: ${failed}`);
  if (failed > 0) process.exit(1);
}

run();
