// e2e/metabase-reports-acceptance.mjs — Acceptance Suite for Metabase Interactive Reports & AI Integration
import { chromium } from 'playwright';

const BASE_URL = 'http://127.0.0.1:8123';
const ACCOUNTS = {
  companyAdmin: { phone: '966511111111', password: 'Company123!' },
};

const results = [];
function record(testId, status, details = '') {
  results.push({ testId, status, details });
  const icon = status === 'PASS' ? '✓' : '✗';
  console.log(`  ${icon} ${testId} — ${details}`);
}

async function run() {
  console.log('\n=== DOU FLEET OS: METABASE & ADVANCED REPORTS ACCEPTANCE ===\n');

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    locale: 'ar-SA',
  });
  const page = await context.newPage();

  const consoleErrors = [];
  const pageErrors = [];

  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', err => {
    pageErrors.push(err.message);
  });

  try {
    // 1. Login
    await page.goto(`${BASE_URL}/app/v2/`);
    await page.waitForSelector('#login-phone', { timeout: 10000 });
    await page.fill('#login-phone', ACCOUNTS.companyAdmin.phone);
    await page.fill('#login-password', ACCOUNTS.companyAdmin.password);
    await page.click('button[type="submit"]');
    await page.waitForSelector('.fleet-app', { timeout: 10000 });
    record('REP-01: Admin login', 'PASS', 'Logged in successfully');

    // 2. Navigate to Reports view
    await page.click('.nav-item[data-view="reports"]');
    await page.waitForSelector('.tabs', { timeout: 5000 });
    record('REP-02: Reports Center navigation', 'PASS', 'Reports view loaded');

    // 3. Verify sub-tabs
    const subTabs = await page.$$('.tab[data-tab]');
    record('REP-03: Reports sub-tabs present', subTabs.length >= 3 ? 'PASS' : 'FAIL', `Found ${subTabs.length} sub-tabs`);

    // 4. Test Catalog domain groups
    await page.waitForSelector('.reports-catalog', { timeout: 5000 });
    const groups = await page.$$('.reports-group');
    record('REP-04: Report Catalog domain groups rendered', groups.length >= 6 ? 'PASS' : 'FAIL', `Found ${groups.length} groups`);

    // 5. Open a report detail (e.g. Rider Master Report)
    const firstReportBtn = await page.$('.report-card');
    if (firstReportBtn) {
      await firstReportBtn.click();
      await page.waitForSelector('#report-result-area', { timeout: 5000 });
      const hasTable = await page.$('#report-result-area .table-wrap table');
      record('REP-05: Report detail table loaded with live data', hasTable ? 'PASS' : 'FAIL', 'Live data table rendered');

      // Check export buttons
      const exportBtns = await page.$$('button:has-text("تصدير")');
      record('REP-06: Export buttons present in report detail', exportBtns.length >= 2 ? 'PASS' : 'FAIL', `Found ${exportBtns.length} export actions`);

      // Return to catalog
      await page.click('button:has-text("← العودة للكتالوج")');
      await page.waitForSelector('.reports-catalog', { timeout: 5000 });
      record('REP-07: Return to catalog button works', 'PASS', 'Catalog restored');
    }

    // 6. Test Metabase Dashboards sub-tab
    await page.click('.tab[data-tab="dashboards"]');
    await page.waitForSelector('.card:has-text("Metabase")', { timeout: 5000 });
    const dashboardCards = await page.$$('.card button:has-text("عرض اللوحة التفاعلية")');
    record('REP-08: Metabase Dashboards catalog loaded', dashboardCards.length >= 4 ? 'PASS' : 'FAIL', `Found ${dashboardCards.length} dashboards`);

    // Open an interactive embedded dashboard
    if (dashboardCards.length > 0) {
      await dashboardCards[0].click();
      await page.waitForSelector('iframe', { timeout: 5000 });
      const iframeSrc = await page.getAttribute('iframe', 'src');
      record('REP-09: Metabase signed JWT embed iframe rendered', (iframeSrc && iframeSrc.includes('/embed/dashboard/')) ? 'PASS' : 'FAIL', `Embed URL: ${iframeSrc?.slice(0, 50)}...`);
    }

    // 7. Test AI BI Queries sub-tab
    await page.click('.tab[data-tab="ai_queries"]');
    await page.waitForSelector('.report-card-title', { timeout: 5000 });
    const aiQueryBtn = await page.$('.report-card:first-child');
    if (aiQueryBtn) {
      await aiQueryBtn.click();
      await page.waitForSelector('#ai-drawer.open', { timeout: 5000 });
      await page.waitForSelector('#ai-drawer-messages .ai-msg.assistant', { timeout: 8000 });
      const aiResponse = await page.textContent('#ai-drawer-messages .ai-msg.assistant:last-child');
      record('REP-10: One-click AI BI query from Reports executes in Drawer', aiResponse.length > 10 ? 'PASS' : 'FAIL', `Response: ${aiResponse.slice(0, 50)}...`);
      await page.click('#ai-drawer .btn-close');
    }

    // 8. Error Integrity
    const unexpectedErrors = consoleErrors.filter(e => !e.includes('favicon') && !e.includes('localhost:3000'));
    record('REP-11: Zero unexpected JS console errors', unexpectedErrors.length === 0 ? 'PASS' : 'FAIL', `${unexpectedErrors.length} errors`);
    record('REP-12: Zero page runtime errors', pageErrors.length === 0 ? 'PASS' : 'FAIL', `${pageErrors.length} errors`);

  } catch (err) {
    console.error('Test run failed:', err);
    record('FATAL', 'FAIL', err.message);
  } finally {
    await browser.close();
  }

  const passed = results.filter(r => r.status === 'PASS').length;
  const failed = results.filter(r => r.status === 'FAIL').length;
  console.log(`\n=== METABASE & REPORTS ACCEPTANCE SUMMARY ===\n`);
  console.log(`Total: ${results.length}`);
  console.log(`Passed: ${passed}`);
  console.log(`Failed: ${failed}`);

  if (failed > 0) process.exit(1);
}

run();
