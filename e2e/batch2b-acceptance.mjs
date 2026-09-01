// e2e/batch2b-acceptance.mjs — DOU Fleet OS Batch 2B (Rider Leaves & Central Approvals Queue)
import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8123';

const ACCOUNTS = {
  companyAdmin: { phone: '966511111111', password: 'Company123!', role: 'COMPANY_ADMIN' },
  operations: { phone: '966522222222', password: 'Ops123456!', role: 'OPERATIONS' },
  supervisor: { phone: '966533333333', password: 'Super1234!', role: 'SUPERVISOR' },
};

let totalTests = 0;
let passedTests = 0;
let failedTests = 0;
let blockedTests = 0;
const results = [];
const consoleErrors = [];
const pageErrors = [];

function record(name, status, detail = '', evidence = '') {
  totalTests++;
  const result = { name, status, detail, evidence };
  results.push(result);
  
  if (status === 'PASS') {
    passedTests++;
    console.log(`  ✓ ${name}${detail ? ' — ' + detail : ''}`);
  } else if (status === 'FAIL') {
    failedTests++;
    console.log(`  ✗ ${name}${detail ? ' — ' + detail : ''}`);
  } else {
    blockedTests++;
    console.log(`  ⊘ ${name} — BLOCKED: ${detail}`);
  }
}

async function captureApiCall(page, urlSubstring, method, actionFn) {
  let matchedResponse = null;
  const handler = async (response) => {
    try {
      if (response.url().includes(urlSubstring) && (method ? response.request().method() === method : true)) {
        matchedResponse = response;
      }
    } catch (_e) {}
  };
  page.on('response', handler);
  await actionFn();
  for (let i = 0; i < 30; i++) {
    if (matchedResponse) break;
    await page.waitForTimeout(100);
  }
  page.off('response', handler);
  if (!matchedResponse) return { status: 0, body: null, error: 'No matching response' };
  return {
    status: matchedResponse.status(),
    body: await matchedResponse.json().catch(() => null),
  };
}

async function login(page, account) {
  try {
    await page.goto(`${BASE}/app/v2/`);
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await page.goto(`${BASE}/app/v2/`);
    await page.waitForSelector('#login-form', { timeout: 5000 });
    
    await page.fill('#login-phone', account.phone);
    await page.fill('#login-password', account.password);
    
    const [response] = await Promise.all([
      page.waitForResponse(r => r.url().includes('/auth/login') && r.request().method() === 'POST'),
      page.click('button[type="submit"]')
    ]);
    
    if (response.status() !== 200) return { success: false, status: response.status() };
    await page.waitForSelector('.fleet-app', { timeout: 5000 });
    return { success: true, status: 200 };
  } catch (e) {
    return { success: false, error: e.message };
  }
}

async function runBatch2BAcceptance() {
  console.log('\n=== BATCH 2B: RIDER LEAVES & CENTRAL APPROVALS QUEUE ===\n');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', err => {
    pageErrors.push(err.message);
  });

  try {
    // -----------------------------------------------------------------
    // PART 1: RIDER 360 LEAVES TAB
    // -----------------------------------------------------------------
    console.log('--- PART 1: RIDER 360 LEAVE MANAGEMENT (COMPANY ADMIN) ---\n');
    const adminLogin = await login(page, ACCOUNTS.companyAdmin);
    record('B2B-01: Admin login', adminLogin.success ? 'PASS' : 'FAIL', `Status: ${adminLogin.status}`);

    // Navigate to Riders list and open Rider 360
    await page.click('.nav-item[data-view="riders"]');
    await page.waitForSelector('.table-wrap table tbody tr button', { timeout: 5000 });
    
    await page.click('.table-wrap table tbody tr:first-child button');
    await page.waitForSelector('#r360-select', { timeout: 5000 });
    record('B2B-02: Rider 360 loaded', 'PASS', 'Opened rider profile');

    // Wait for tabs to render
    await page.waitForSelector('.tab[data-tab="leave"]', { timeout: 5000 });
    await page.click('.tab[data-tab="leave"]');
    await page.waitForSelector('#rider360-leave-wrap', { timeout: 5000 });
    record('B2B-03: Rider 360 Leave tab opened', 'PASS', 'Leave view container rendered');

    // Check KPI metrics
    await page.waitForSelector('#rider-leave-metrics .metric', { timeout: 5000 });
    const riderLeaveMetrics = await page.$$('#rider-leave-metrics .metric');
    record('B2B-04: Rider leave entitlement KPI cards rendered', riderLeaveMetrics.length === 4 ? 'PASS' : 'FAIL', `${riderLeaveMetrics.length} metrics found`);

    // Click + طلب إجازة
    await page.waitForSelector('#btn-request-leave', { timeout: 5000 });
    const requestLeaveBtn = await page.$('#btn-request-leave');
    record('B2B-05: Request Leave button visible', requestLeaveBtn ? 'PASS' : 'FAIL', 'Button found');

    const uniqueLeaveReason = `إجازة استثنائية لاختبار ${Date.now()}`;
    if (requestLeaveBtn) {
      await requestLeaveBtn.click();
      await page.waitForSelector('#request-leave-form', { timeout: 5000 });
      record('B2B-06: Request Leave modal opened', 'PASS', 'Form modal rendered');

      // Fill form with non-overlapping future dates using dynamic offset
      const dayOffset = 30 + (Math.floor(Date.now() / 1000) % 200);
      const fromDateObj = new Date(Date.now() + dayOffset * 86400000);
      const toDateObj = new Date(Date.now() + (dayOffset + 3) * 86400000);
      const fromIso = fromDateObj.toISOString().split('T')[0];
      const toIso = toDateObj.toISOString().split('T')[0];

      await page.fill('#leave-from-date', fromIso);
      await page.fill('#leave-to-date', toIso);
      await page.fill('#leave-reason', uniqueLeaveReason);

      const createLeaveResp = await captureApiCall(page, '/leave/requests', 'POST', () => {
        page.click('#request-leave-form button[type="submit"]');
      });
      record('B2B-07: Create Leave Request API', createLeaveResp.status === 201 ? 'PASS' : 'FAIL', `Status: ${createLeaveResp.status}`);

      await page.waitForTimeout(1200);
      const newLeaveRow = await page.$(`table tbody tr:has-text("${uniqueLeaveReason}")`);
      record('B2B-08: New leave request appears in rider table', newLeaveRow ? 'PASS' : 'FAIL', `Found row for "${uniqueLeaveReason}"`);

      const openModal = await page.$('.modal-overlay');
      if (openModal) {
        const closeBtn = await page.$('.modal-overlay .btn-close');
        if (closeBtn) await closeBtn.click();
        await page.waitForTimeout(500);
      }
    }

    // -----------------------------------------------------------------
    // PART 2: CENTRAL LEAVE APPROVALS QUEUE (SHIFTS VIEW)
    // -----------------------------------------------------------------
    console.log('\n--- PART 2: CENTRAL LEAVE APPROVALS QUEUE ---\n');
    await page.click('.nav-item[data-view="shifts"]');
    await page.waitForSelector('.tabs', { timeout: 5000 });

    const leavesTabBtn = await page.$('.tab[data-subtab="leaves"]');
    record('B2B-09: Central Leaves subtab exists in Shifts view', leavesTabBtn ? 'PASS' : 'FAIL', 'Found leaves tab button');

    if (leavesTabBtn) {
      await leavesTabBtn.click();
      await page.waitForSelector('#leave-status-filter', { timeout: 5000 });
      await page.waitForSelector('#central-leave-metrics .metric', { timeout: 5000 });

      const centralMetrics = await page.$$('#central-leave-metrics .metric');
      record('B2B-10: Central leave KPI metrics cards rendered', centralMetrics.length === 4 ? 'PASS' : 'FAIL', `${centralMetrics.length} metrics found`);

      await page.waitForSelector('#central-leave-table-wrap table tbody tr', { timeout: 5000 });
      const centralTable = await page.$('#central-leave-table-wrap .table-wrap');
      record('B2B-11: Central leave requests table rendered', centralTable ? 'PASS' : 'FAIL', 'Table container rendered');

      // Find the pending request to review
      const reviewLeaveBtn = await page.$(`#central-leave-table-wrap table tbody tr:has-text("${uniqueLeaveReason}") button:has-text("مراجعة واتخاذ قرار")`) ||
                             await page.$('#central-leave-table-wrap table tbody tr button:has-text("مراجعة واتخاذ قرار")');

      if (reviewLeaveBtn) {
        await reviewLeaveBtn.click();
        await page.waitForSelector('.review-leave-modal', { timeout: 5000 });
        record('B2B-12: Central Leave Decision Modal opened', 'PASS', 'Modal rendered');

        await page.fill('#leave-review-note', 'تمت الموافقة الإدارية والتحقق من التغطية الميدانية');
        const decideResp = await captureApiCall(page, '/leave/requests/', 'POST', () => {
          page.click('.review-leave-modal button:has-text("اعتماد الإجازة")');
        });
        record('B2B-13: Approve Leave Decision API', decideResp.status === 200 ? 'PASS' : 'FAIL', `Status: ${decideResp.status}`);

        await page.waitForTimeout(1200);

        const openModal2 = await page.$('.modal-overlay');
        if (openModal2) {
          const closeBtn2 = await page.$('.modal-overlay .btn-close');
          if (closeBtn2) await closeBtn2.click();
          await page.waitForTimeout(500);
        }

        // Switch to APPROVED filter
        await page.selectOption('#leave-status-filter', 'APPROVED');
        await page.waitForTimeout(800);
        await page.waitForSelector('#central-leave-table-wrap table tbody tr:has-text("معتمد")', { timeout: 5000 });
        const approvedRow = await page.$('#central-leave-table-wrap table tbody tr:has-text("معتمد")');
        record('B2B-14: Approved leave appears in Approved filter', approvedRow ? 'PASS' : 'FAIL', 'Found approved leave badge');
      } else {
        record('B2B-12: Central Leave Decision Modal opened', 'BLOCKED', 'No reviewable leave found');
        record('B2B-13: Approve Leave Decision API', 'BLOCKED', 'Skipped');
        record('B2B-14: Approved leave appears in filter', 'BLOCKED', 'Skipped');
      }
    }

    // -----------------------------------------------------------------
    // PART 3: RE-CHECK RIDER 360 ENTITLEMENT UPDATED
    // -----------------------------------------------------------------
    console.log('\n--- PART 3: BALANCE REFLECTION IN RIDER 360 ---\n');
    await page.click('.nav-item[data-view="riders"]');
    await page.waitForSelector('.table-wrap table tbody tr button', { timeout: 5000 });
    await page.click('.table-wrap table tbody tr:first-child button');
    await page.waitForSelector('#r360-select', { timeout: 5000 });
    await page.waitForSelector('.tab[data-tab="leave"]', { timeout: 5000 });
    await page.click('.tab[data-tab="leave"]');
    await page.waitForSelector('#rider-leave-metrics', { timeout: 5000 });

    await page.waitForSelector(`table tbody tr:has-text("${uniqueLeaveReason}") span:has-text("معتمد")`, { timeout: 5000 });
    const approvedInRider360 = await page.$(`table tbody tr:has-text("${uniqueLeaveReason}") span:has-text("معتمد")`);
    record('B2B-15: Leave approval reflected in Rider 360', approvedInRider360 ? 'PASS' : 'FAIL', 'Approved status badge found in profile');

    // -----------------------------------------------------------------
    // PART 4: SUPERVISOR ACCESS SCOPE
    // -----------------------------------------------------------------
    console.log('\n--- PART 4: SUPERVISOR RBAC ---\n');
    await login(page, ACCOUNTS.supervisor);
    await page.click('.nav-item[data-view="shifts"]');
    await page.waitForSelector('.tabs', { timeout: 5000 });
    const supLeavesTab = await page.$('.tab[data-subtab="leaves"]');
    record('B2B-16: Supervisor can view leave requests tab', supLeavesTab ? 'PASS' : 'FAIL', 'Leaves tab accessible');

    // -----------------------------------------------------------------
    // PART 5: CONSOLE & PAGE ERROR INTEGRITY
    // -----------------------------------------------------------------
    console.log('\n--- PART 5: ERROR INTEGRITY ---\n');
    const realConsoleErrors = consoleErrors.filter(e => 
      !e.includes('favicon') && !e.includes('net::ERR') && !e.includes('404') && !e.includes('401') && !e.includes('403')
    );
    record('B2B-17: Zero unexpected JS console errors', realConsoleErrors.length === 0 ? 'PASS' : 'FAIL', `${realConsoleErrors.length} errors: ${realConsoleErrors.join('; ')}`);
    record('B2B-18: Zero page runtime errors', pageErrors.length === 0 ? 'PASS' : 'FAIL', `${pageErrors.length} errors`);

  } catch (err) {
    record('FATAL', 'FAIL', err.message, err.stack || '');
  } finally {
    await browser.close();
  }

  console.log('\n=== BATCH 2B SUMMARY ===\n');
  console.log(`Total: ${totalTests}`);
  console.log(`Passed: ${passedTests}`);
  console.log(`Failed: ${failedTests}`);
  console.log(`Blocked: ${blockedTests}`);

  return { totalTests, passedTests, failedTests, blockedTests };
}

runBatch2BAcceptance().then(res => {
  if (res.failedTests > 0) process.exit(1);
  process.exit(0);
}).catch(err => {
  console.error(err);
  process.exit(1);
});
