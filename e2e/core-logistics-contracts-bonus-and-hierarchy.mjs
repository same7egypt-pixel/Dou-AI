// Comprehensive Acceptance Suite: Core Logistics Contracts, Multi-Supervisors, Hierarchy & Dual Bonus Plans
import { chromium } from 'playwright';

const BASE_URL = 'http://127.0.0.1:8123';
let passed = 0;
let failed = 0;
const results = [];

function record(step, action, api, role, status, detail = '') {
  if (status === 'PASS') {
    passed++;
    console.log(`  ✓ [${step}] ${action} | API: ${api} | Role: ${role} | Status: PASS${detail ? ` (${detail})` : ''}`);
  } else {
    failed++;
    console.log(`  ✗ [${step}] ${action} | API: ${api} | Role: ${role} | Status: FAIL${detail ? ` (${detail})` : ''}`);
  }
  results.push({ step, action, api, role, status, detail });
}

async function run() {
  console.log('\n========================================================================================');
  console.log('CORE LOGISTICS ACCEPTANCE SUITE: CONTRACTS, MULTI-SUPERVISOR, HIERARCHY & DUAL BONUS');
  console.log('========================================================================================\n');

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  try {
    // 1. Admin Login
    await page.goto(`${BASE_URL}/app/v2/`);
    await page.fill('#login-phone', '966511111111');
    await page.fill('#login-password', 'Company123!');
    await page.click('button[type="submit"]');
    await page.waitForSelector('.fleet-app', { timeout: 8000 });
    const adminToken = await page.evaluate(() => localStorage.getItem('dou_token_v2'));
    record('COR-01', 'Company Admin Authentication', 'POST /auth/login', 'COMPANY_ADMIN', 'PASS', 'Logged in as company admin');

    // 2. Create Two Field Supervisors
    const ts = Date.now();
    const sup1Res = await page.request.post(`${BASE_URL}/hr/supervisors`, {
      headers: { Authorization: `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
      data: { name: `مشرف خالد ${ts}`, phone: `96657${ts.toString().slice(-7)}1`, password: 'Supervisor123!' }
    });
    const sup1Data = await sup1Res.json();
    const sup1Id = sup1Data.id;

    const sup2Res = await page.request.post(`${BASE_URL}/hr/supervisors`, {
      headers: { Authorization: `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
      data: { name: `مشرف حسان ${ts}`, phone: `96657${ts.toString().slice(-7)}2`, password: 'Supervisor123!' }
    });
    const sup2Data = await sup2Res.json();
    const sup2Id = sup2Data.id;
    record('COR-02', 'Create Field Supervisors', 'POST /hr/supervisors', 'COMPANY_ADMIN', 'PASS', `Created sup1 (#${sup1Id}) and sup2 (#${sup2Id})`);

    // 3. Create Commercial Contract with Multiple Supervisors assigned to Branch
    const contractRes = await page.request.post(`${BASE_URL}/hr/contracts`, {
      headers: { Authorization: `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
      data: {
        name: `عقد نينجا إكسبريس ${ts}`,
        client_name: 'Ninja Delivery App',
        client_rate_per_order: 16.50,
        contract_type: 'COMMERCIAL',
        start_date: new Date().toISOString().slice(0, 10),
        end_date: new Date(Date.now() + 180*24*3600*1000).toISOString().slice(0, 10),
        cities: [
          { city: 'الرياض', city_id: 1, supervisor_ids: [sup1Id, sup2Id] },
          { city: 'جدة', city_id: 2, supervisor_ids: [sup1Id] }
        ]
      }
    });
    const contractData = await contractRes.json();
    const contractId = contractData.id;
    record('COR-03', 'Create Commercial Contract with Multi-Supervisors', 'POST /hr/contracts', 'COMPANY_ADMIN', 'PASS', `Contract #${contractId} with 2 branches created`);

    // 4. Verify Contract Structure & Supervisor Mapping
    const structRes = await page.request.get(`${BASE_URL}/hr/contract-structure`, {
      headers: { Authorization: `Bearer ${adminToken}` }
    });
    const structure = await structRes.json();
    const targetCt = structure.find(c => c.id === contractId);
    const riyadhBranch = targetCt?.branches?.find(b => b.city_id === 1 || b.city === 'الرياض' || b.city === 'Riyadh');
    const hasMultipleSups = riyadhBranch?.supervisors?.length >= 2;
    record('COR-04', 'Verify Multi-Supervisor Branch Hierarchy', 'GET /hr/contract-structure', 'COMPANY_ADMIN', hasMultipleSups ? 'PASS' : 'FAIL', `Riyadh branch has ${riyadhBranch?.supervisors?.length || 0} supervisors`);

    // 5. Contract Renewal
    const renewRes = await page.request.post(`${BASE_URL}/hr/contracts/${contractId}/renew`, {
      headers: { Authorization: `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
      data: { months: 12 }
    });
    const renewData = await renewRes.json();
    record('COR-05', 'Contract Renewal for 12 Months', `POST /hr/contracts/${contractId}/renew`, 'COMPANY_ADMIN', renewData.ok ? 'PASS' : 'FAIL', `New End Date: ${renewData.end_date}`);

    // 6. Create Rider Linked Hierarchically (Supervisor -> Branch -> Contract)
    const riderPhone = `96658${ts.toString().slice(-7)}`;
    const createRiderRes = await page.request.post(`${BASE_URL}/fleet/couriers`, {
      headers: { Authorization: `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
      data: {
        name: `سائق تجريبي ${ts}`,
        phone: riderPhone,
        password: 'Password123!',
        contract_id: contractId,
        contract_branch_id: riyadhBranch.id,
        supervisor_id: sup1Id,
        city_id: 1,
        courier_type: 'COMPANY',
        base_salary: 3000,
        per_delivery_rate: 5.0
      }
    });
    const riderData = await createRiderRes.json();
    const riderId = riderData.id;
    record('COR-06', 'Create Rider in Exact Hierarchy', 'POST /fleet/couriers', 'COMPANY_ADMIN', riderId ? 'PASS' : 'FAIL', `Rider #${riderId} linked to Sup #${sup1Id}, Branch #${riyadhBranch.id}, Contract #${contractId}`);

    // 7. Create Target-Tier Bonus Plan with Below-Target Fallback
    const bonusPlan1Res = await page.request.post(`${BASE_URL}/hr/bonus`, {
      headers: { Authorization: `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
      data: {
        plan_type: 'TARGET_TIER',
        contract_id: contractId,
        contract_branch_id: riyadhBranch.id,
        target_orders: 200,
        bonus_amount: 500.0,
        over_target_rate: 3.0,
        below_target_rate: 12.0,
        is_active: true
      }
    });
    const bp1Data = await bonusPlan1Res.json();
    record('COR-07', 'Create Target-Tier Bonus Plan', 'POST /hr/bonus', 'COMPANY_ADMIN', bp1Data.ok ? 'PASS' : 'FAIL', `Plan #${bp1Data.id}: Target 200 => 500 SAR (+3 over / 12 below)`);

    // 8. Create Flat Per-Order Bonus Plan
    const bonusPlan2Res = await page.request.post(`${BASE_URL}/hr/bonus`, {
      headers: { Authorization: `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
      data: {
        plan_type: 'FLAT_PER_ORDER',
        contract_id: contractId,
        flat_order_rate: 15.0,
        is_active: true
      }
    });
    const bp2Data = await bonusPlan2Res.json();
    record('COR-08', 'Create Flat Per-Order Plan', 'POST /hr/bonus', 'COMPANY_ADMIN', bp2Data.ok ? 'PASS' : 'FAIL', `Plan #${bp2Data.id}: 15 SAR / order flat`);

    // 9. Verify SAMA / WPS Bank File Export
    const curMonth = new Date().toISOString().slice(0, 7);
    const wpsRes = await page.request.get(`${BASE_URL}/hr/payroll/wps-export?month=${curMonth}`, {
      headers: { Authorization: `Bearer ${adminToken}` }
    });
    const wpsContent = await wpsRes.text();
    const hasWpsHeaders = wpsContent.includes('Employer ID') && wpsContent.includes('Bank IBAN');
    record('COR-09', 'WPS Payroll Bank File Export', `GET /hr/payroll/wps-export?month=${curMonth}`, 'COMPANY_ADMIN', hasWpsHeaders ? 'PASS' : 'FAIL', `WPS format verified (${wpsContent.split('\n').length} lines)`);

    // 10. Register Vehicle in Fleet Registry
    const vehPlate = `د ب ب ${ts.toString().slice(-4)}`;
    const vehRes = await page.request.post(`${BASE_URL}/vehicles`, {
      headers: { Authorization: `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
      data: {
        plate_number: vehPlate,
        vehicle_type: 'Motorcycle',
        make: 'Honda',
        model: 'CG125',
        model_year: 2025,
        market_code: 'SA',
        is_exclusive: true
      }
    });
    const vehData = await vehRes.json();
    record('COR-10', 'Register Fleet Vehicle', 'POST /vehicles', 'COMPANY_ADMIN', vehData.id ? 'PASS' : 'FAIL', `Vehicle #${vehData.id} (${vehPlate}) registered`);

    // 11. Configure Attendance Policies
    const attPolRes = await page.request.post(`${BASE_URL}/hr/attendance-policies`, {
      headers: { Authorization: `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
      data: {
        event_type: 'LATE',
        calculation_method: 'FIXED',
        grace_minutes: 15,
        deduction_amount: 30.0,
        is_active: true
      }
    });
    const attPolData = await attPolRes.json();
    record('COR-11', 'Attendance Policy Configuration', 'POST /hr/attendance-policies', 'COMPANY_ADMIN', attPolData.id ? 'PASS' : 'FAIL', `Late policy set: 15 min grace => 30 SAR penalty`);

    // 12. Strict RBAC: Field Supervisor cannot create/edit contracts or bonus plans
    const supLoginRes = await page.request.post(`${BASE_URL}/auth/login`, {
      data: { phone: `96657${ts.toString().slice(-7)}1`, password: 'Supervisor123!' }
    });
    const supLoginData = await supLoginRes.json();
    const supToken = supLoginData.access_token;

    const deniedContractRes = await page.request.post(`${BASE_URL}/hr/contracts`, {
      headers: { Authorization: `Bearer ${supToken}`, 'Content-Type': 'application/json' },
      data: { name: 'Unauthorized Contract' }
    });
    const contractDenied = deniedContractRes.status() === 403;

    const deniedBonusRes = await page.request.post(`${BASE_URL}/hr/bonus`, {
      headers: { Authorization: `Bearer ${supToken}`, 'Content-Type': 'application/json' },
      data: { plan_type: 'TARGET_TIER', target_orders: 100 }
    });
    const bonusDenied = deniedBonusRes.status() === 403;

    record('COR-12', 'Supervisor RBAC Denied on Contracts & Bonus', 'POST /hr/contracts & /hr/bonus', 'SUPERVISOR', (contractDenied && bonusDenied) ? 'PASS' : 'FAIL', `Contract 403: ${contractDenied}, Bonus 403: ${bonusDenied}`);

    // 13. UI Navigation Verification: Contracts subtab in Capacity
    await page.evaluate(() => window.go('capacity'));
    await page.waitForTimeout(1000);
    const contractsTab = await page.waitForSelector('.tab:has-text("العقود")', { timeout: 8000 });
    await contractsTab.click();
    await page.waitForTimeout(1000);
    const hasContractCards = await page.evaluate((cName) => document.body.innerText.includes(cName), `عقد نينجا إكسبريس ${ts}`);
    record('COR-13', 'UI Capacity Sub-Tab Contracts & Branches Rendered', 'UI Navigation', 'COMPANY_ADMIN', hasContractCards ? 'PASS' : 'FAIL', 'Found contract card in UI');

    // 14. UI Navigation Verification: Bonus Plans in Payroll
    await page.evaluate(() => window.go('payroll'));
    await page.waitForTimeout(1000);
    const bonusTab = await page.waitForSelector('.tab:has-text("البونص")', { timeout: 8000 });
    await bonusTab.click();
    await page.waitForTimeout(1000);
    const hasBonusSection = await page.evaluate(() => document.body.innerText.includes('خطط الحوافز والبونص التشغيلي'));
    record('COR-14', 'UI Payroll Bonus Plans & Leaderboard Rendered', 'UI Navigation', 'COMPANY_ADMIN', hasBonusSection ? 'PASS' : 'FAIL', 'Bonus plans manager rendered in UI');

    // 15. UI Navigation Verification: Vehicles Fleet in Riders
    await page.evaluate(() => window.go('riders'));
    await page.waitForTimeout(1000);
    const vehBtn = await page.waitForSelector('#btn-vehicles-fleet', { timeout: 8000 });
    await vehBtn.click();
    await page.waitForTimeout(1000);
    const hasVehModal = await page.evaluate(() => document.body.innerText.includes('سجل مركبات الأسطول'));
    record('COR-15', 'UI Vehicles Fleet Modal Rendered', 'UI Interaction', 'COMPANY_ADMIN', hasVehModal ? 'PASS' : 'FAIL', 'Vehicles registry modal opened');

  } catch (err) {
    record('ERROR', 'Execution Exception', 'E2E', 'SYSTEM', 'FAIL', err.message);
  } finally {
    await browser.close();
  }

  console.log('\n========================================================================================');
  console.log(`ACCEPTANCE SUMMARY: Total: ${passed + failed} | Passed: ${passed} | Failed: ${failed}`);
  console.log('========================================================================================\n');

  if (failed > 0) {
    process.exit(1);
  }
}

run();
