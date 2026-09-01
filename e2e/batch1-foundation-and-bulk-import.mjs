// E2E Acceptance Test Suite for Batch 1: Scope Resolver, Ingestion Templates & Bulk Upload Workflow
import { chromium } from 'playwright';

const BASE_URL = 'http://127.0.0.1:8123';
const TEST_TIMEOUT = 30000;

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
  console.log('\n=== BATCH 1: FOUNDATION, SCOPE RESOLVER & BULK INGESTION ACCEPTANCE ===\n');
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
    // 1. Admin Login & Session
    await page.goto(`${BASE_URL}/app/v2/`);
    await page.fill('#login-phone', '966511111111');
    await page.fill('#login-password', 'Company123!');
    await page.click('button[type="submit"]');
    await page.waitForSelector('.fleet-app', { timeout: 8000 });
    record('B1-01: Admin login & App mount', 'PASS', 'Mounted .fleet-app successfully');

    // 2. Download Template Endpoints Direct API Check
    const token = await page.evaluate(() => localStorage.getItem('dou_token_v2'));
    const riderTemplateRes = await page.request.get(`${BASE_URL}/fleet/imports/riders/template`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    record('B1-02: Rider CSV Template Download API', riderTemplateRes.status() === 200 ? 'PASS' : 'FAIL', `Status: ${riderTemplateRes.status()}, Content-Type: ${riderTemplateRes.headers()['content-type']}`);

    const perfTemplateRes = await page.request.get(`${BASE_URL}/fleet/imports/performance/template`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    record('B1-03: Performance CSV Template Download API', perfTemplateRes.status() === 200 ? 'PASS' : 'FAIL', `Status: ${perfTemplateRes.status()}, Content-Type: ${perfTemplateRes.headers()['content-type']}`);

    // 3. Navigate to Riders & Verify Action Buttons
    await page.click('.nav-item[data-view="riders"]');
    await page.waitForSelector('.table-wrap table', { timeout: 6000 });
    const bulkImportBtn = await page.$('button:has-text("استيراد جماعي")');
    const importHistoryBtn = await page.$('button:has-text("سجل الاستيراد")');
    record('B1-04: Bulk Import & History action buttons visible', (bulkImportBtn && importHistoryBtn) ? 'PASS' : 'FAIL', 'Found action buttons in header');

    // 4. Open Bulk Import Modal
    await bulkImportBtn.click();
    await page.waitForSelector('.modal-overlay .import-tab-content', { timeout: 5000 });
    const modalVisible = await page.$('.modal-overlay');
    record('B1-05: Bulk Import Modal rendered', modalVisible ? 'PASS' : 'FAIL', 'Modal overlay opened with import workflow');

    // 5. Test Import Preview API directly with valid CSV
    const timestamp = Date.now();
    const validCsv = `name,mobile,initial_password,national_id_or_iqama,nationality,city,branch,contract_or_project,supervisor
Bulk Driver ${timestamp},9665${timestamp.toString().slice(-8)},Pass12345!,1099887766,SA,Riyadh,Riyadh,Main Contract,Ahmed Supervisor`;
    
    const previewRes = await page.request.post(`${BASE_URL}/fleet/imports/riders/preview`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      data: { csv_text: validCsv, file_name: `test_batch_${timestamp}.csv` }
    });
    const previewData = await previewRes.json();
    record('B1-06: Bulk Rider Import Preview API', previewRes.status() === 200 && previewData.total_rows >= 1 ? 'PASS' : 'FAIL', `Total rows: ${previewData.total_rows}, Valid: ${previewData.valid_rows}, Batch ID: ${previewData.id}`);

    // 6. Test Import Confirmation API
    const confirmRes = await page.request.post(`${BASE_URL}/fleet/imports/riders/${previewData.id}/confirm`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    const confirmData = await confirmRes.json();
    record('B1-07: Bulk Rider Import Confirm API', confirmRes.status() === 200 ? 'PASS' : 'FAIL', `Status: ${confirmRes.status()}, Result: ${JSON.stringify(confirmData.result || {})}`);

    // Close modal
    const closeBtn = await page.$('.modal-overlay .btn-close');
    if (closeBtn) await closeBtn.click();

    // 7. Open Import History Modal
    await page.click('button:has-text("سجل الاستيراد")');
    await page.waitForSelector('.modal-overlay table, .modal-overlay .state-empty', { timeout: 5000 });
    const historyTable = await page.$('.modal-overlay table');
    record('B1-08: Import History Modal loaded', historyTable ? 'PASS' : 'FAIL', 'History batches table rendered');
    const closeHistoryBtn = await page.$('.modal-overlay .btn-close');
    if (closeHistoryBtn) await closeHistoryBtn.click();

    // 8. Test Platform Operator Mode
    // Update tenant to DELIVERY_PLATFORM in memory / test client
    const isPlatformCheck = await page.evaluate(async () => {
      const { appStore, isDeliveryPlatform } = await import('/frontend-v2/shared/state/store.js');
      const current = appStore.get();
      appStore.set({
        tenant: { ...current.tenant, customer_type: 'DELIVERY_PLATFORM' },
        operators: [
          { id: 1, operator_tenant_id: 101, name: 'مشغل الرياض السريع' },
          { id: 2, operator_tenant_id: 102, name: 'مشغل جدة اللوجستي' }
        ]
      });
      const { renderShell } = await import('/frontend-v2/fleet/shell.js');
      renderShell();
      return isDeliveryPlatform();
    });
    await page.waitForSelector('#topbar-operator-select', { timeout: 5000 });
    const opSelectVisible = await page.$('#topbar-operator-select');
    record('B1-09: Platform Operator Selector rendered in TopBar', (isPlatformCheck && opSelectVisible) ? 'PASS' : 'FAIL', 'Found #topbar-operator-select when customer_type is DELIVERY_PLATFORM');

    // 9. Error Integrity
    record('B1-10: Zero unexpected JS console errors', consoleErrors.length === 0 ? 'PASS' : 'FAIL', `${consoleErrors.length} errors: ${consoleErrors.join('; ')}`);
    record('B1-11: Zero page runtime errors', pageErrors.length === 0 ? 'PASS' : 'FAIL', `${pageErrors.length} errors`);

  } catch (err) {
    console.error('Test execution exception:', err);
    record('B1-FATAL', 'FAIL', err.message);
  } finally {
    await browser.close();
  }

  console.log(`\n=== BATCH 1 SUMMARY ===`);
  console.log(`Total: ${passed + failed}`);
  console.log(`Passed: ${passed}`);
  console.log(`Failed: ${failed}`);
  if (failed > 0) process.exit(1);
}

run();
