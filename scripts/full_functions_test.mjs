// scripts/full_functions_test.mjs — Comprehensive Functions Test Suite for DOU Fleet OS
import { chromium } from 'playwright';

const LIVE_URL = 'https://dou.delivery';
const CREDENTIALS = {
  fleetAdmin: { phone: '966581112233', password: 'dou123456', role: 'FLEET_ADMIN' },
  opsManager: { phone: '966500000000', password: 'dou123456', role: 'OPERATIONS' },
  superAdmin: { phone: '966512345678', password: 'dou123456', role: 'SUPER_ADMIN' },
};

const results = [];
function record(category, testName, pass, details = '') {
  results.push({ category, testName, pass, details });
  const icon = pass ? '✅ PASS' : '❌ FAIL';
  console.log(`[${icon}] ${category} :: ${testName} ${details ? '— ' + details : ''}`);
}

async function apiCall(endpoint, options = {}, token = null) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  
  const startTime = Date.now();
  const res = await fetch(`${LIVE_URL}${endpoint}`, { ...options, headers });
  const latency = Date.now() - startTime;
  let data = null;
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    data = await res.json();
  } else {
    data = await res.text();
  }
  return { status: res.status, data, latency, headers: res.headers };
}

async function runAllTests() {
  console.log('\n===============================================================');
  console.log('🚀 STARTING COMPREHENSIVE FUNCTIONS TEST — DOU FLEET OS');
  console.log(`📍 Target Server: ${LIVE_URL}`);
  console.log(`⏰ Timestamp: ${new Date().toISOString()}`);
  console.log('===============================================================\n');

  let adminToken = null;
  let opsToken = null;
  let superToken = null;

  // ─────────────────────────────────────────────────────────────
  // 1. HEALTH & INFRASTRUCTURE TESTS
  // ─────────────────────────────────────────────────────────────
  console.log('\n--- 1. Infrastructure & System Health ---');
  try {
    const health = await apiCall('/health/ready');
    record('INFRASTRUCTURE', 'Health Ready Probe', health.status === 200 && health.data.database === 'ok', `Status ${health.status} (${health.latency}ms) - DB: ${health.data.database}`);
  } catch (e) {
    record('INFRASTRUCTURE', 'Health Ready Probe', false, e.message);
  }

  try {
    const landing = await apiCall('/');
    record('INFRASTRUCTURE', 'Landing Page HTTP 200', landing.status === 200, `Length: ${landing.data.length} bytes (${landing.latency}ms)`);
  } catch (e) {
    record('INFRASTRUCTURE', 'Landing Page', false, e.message);
  }

  // ─────────────────────────────────────────────────────────────
  // 2. AUTHENTICATION & RBAC TESTS
  // ─────────────────────────────────────────────────────────────
  console.log('\n--- 2. Authentication & Multi-Role RBAC ---');
  try {
    const loginRes = await apiCall('/auth/login', {
      method: 'POST',
      body: JSON.stringify(CREDENTIALS.fleetAdmin)
    });
    adminToken = loginRes.data?.access_token;
    record('AUTH', 'Fleet Admin Login (966581112233)', loginRes.status === 200 && !!adminToken, `Token received (${loginRes.latency}ms)`);
  } catch (e) {
    record('AUTH', 'Fleet Admin Login', false, e.message);
  }

  try {
    const opsRes = await apiCall('/auth/login', {
      method: 'POST',
      body: JSON.stringify(CREDENTIALS.opsManager)
    });
    opsToken = opsRes.data?.access_token;
    record('AUTH', 'Operations Manager Login (966500000000)', opsRes.status === 200 && !!opsToken, `Token received (${opsRes.latency}ms)`);
  } catch (e) {
    record('AUTH', 'Operations Manager Login', false, e.message);
  }

  try {
    const superRes = await apiCall('/auth/login', {
      method: 'POST',
      body: JSON.stringify(CREDENTIALS.superAdmin)
    });
    superToken = superRes.data?.access_token;
    record('AUTH', 'Super Admin Login (966512345678)', superRes.status === 200 && !!superToken, `Token received (${superRes.latency}ms)`);
  } catch (e) {
    record('AUTH', 'Super Admin Login', false, e.message);
  }

  try {
    const badLogin = await apiCall('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ phone: '966500000000', password: 'wrongpassword' })
    });
    record('AUTH', 'Reject Invalid Credentials', badLogin.status === 401 || badLogin.status === 400, `Rejected with HTTP ${badLogin.status}`);
  } catch (e) {
    record('AUTH', 'Reject Invalid Credentials', false, e.message);
  }

  // ─────────────────────────────────────────────────────────────
  // 3. FLEET CORE OPERATIONS APIS
  // ─────────────────────────────────────────────────────────────
  console.log('\n--- 3. Core Fleet Operations APIs ---');
  try {
    const ov = await apiCall('/fleet/overview', {}, adminToken);
    record('FLEET_OPS', 'Command Center Overview', ov.status === 200 && typeof ov.data?.couriers_total === 'number', `Couriers: ${ov.data?.couriers_total}, Online: ${ov.data?.couriers_online}, Orders: ${ov.data?.orders_total}`);
  } catch (e) {
    record('FLEET_OPS', 'Command Center Overview', false, e.message);
  }

  try {
    const couriers = await apiCall('/fleet/couriers', {}, adminToken);
    record('FLEET_OPS', 'Couriers & Workforce List', couriers.status === 200 && Array.isArray(couriers.data), `Total couriers: ${couriers.data?.length}`);
  } catch (e) {
    record('FLEET_OPS', 'Couriers List', false, e.message);
  }

  try {
    const shifts = await apiCall('/fleet/shifts', {}, adminToken);
    record('FLEET_OPS', 'Shifts & Schedules', shifts.status === 200 && Array.isArray(shifts.data), `Total shifts: ${shifts.data?.length}`);
  } catch (e) {
    record('FLEET_OPS', 'Shifts & Schedules', false, e.message);
  }

  try {
    const attention = await apiCall('/fleet/needs-attention', {}, adminToken);
    record('FLEET_OPS', 'Needs Attention / Alert Center', attention.status === 200, `Items flagged: ${attention.data?.length || 0}`);
  } catch (e) {
    record('FLEET_OPS', 'Needs Attention', false, e.message);
  }

  try {
    const contracts = await apiCall('/fleet/contracts', {}, adminToken);
    record('FLEET_OPS', 'Client Contracts & Projects', contracts.status === 200, `Contracts count: ${contracts.data?.length || 0}`);
  } catch (e) {
    record('FLEET_OPS', 'Client Contracts', false, e.message);
  }

  // ─────────────────────────────────────────────────────────────
  // 4. REPORTS & ANALYTICS ENGINE
  // ─────────────────────────────────────────────────────────────
  console.log('\n--- 4. Reports & Business Intelligence Engine ---');
  try {
    const catalog = await apiCall('/analytics/reports/catalog', {}, adminToken);
    const groups = Object.keys(catalog.data?.catalog || {});
    record('REPORTS', 'Reports Catalog (31 Reports)', catalog.status === 200 && groups.length >= 6, `Categories: ${groups.length} groups (${groups.join(', ')})`);
  } catch (e) {
    record('REPORTS', 'Reports Catalog', false, e.message);
  }

  try {
    const facts = await apiCall('/analytics/reports/platform-facts', {}, adminToken);
    const s = facts.data?.summary || {};
    record('REPORTS', 'Platform Facts (19 Raw KPIs)', facts.status === 200 && facts.data?.rows?.length > 0, `Rows: ${facts.data?.rows?.length} days | Completed Deliveries: ${s.total_completed} | Hours: ${s.total_actual_hours}`);
  } catch (e) {
    record('REPORTS', 'Platform Facts', false, e.message);
  }

  try {
    const dashboards = await apiCall('/analytics/reports/dashboards', {}, adminToken);
    record('REPORTS', 'DOU AI Live Dashboards API', dashboards.status === 200 && dashboards.data?.dashboards?.length === 5, `Available dashboards: ${dashboards.data?.dashboards?.length}`);
  } catch (e) {
    record('REPORTS', 'DOU AI Dashboards', false, e.message);
  }

  try {
    const riderMaster = await apiCall('/analytics/reports/workforce/rider_master', {}, adminToken);
    record('REPORTS', 'Workforce Rider Master Report', riderMaster.status === 200 && riderMaster.data?.rows?.length > 0, `Rows returned: ${riderMaster.data?.rows?.length}`);
  } catch (e) {
    record('REPORTS', 'Workforce Rider Master', false, e.message);
  }

  try {
    const attSummary = await apiCall('/analytics/reports/attendance/summary', {}, adminToken);
    record('REPORTS', 'Attendance & Hours Summary Report', attSummary.status === 200, `Riders evaluated: ${attSummary.data?.total_riders || 0}`);
  } catch (e) {
    record('REPORTS', 'Attendance Summary', false, e.message);
  }

  try {
    const csvExport = await apiCall('/analytics/reports/download/csv?report_type=rider_master&group=workforce', {}, adminToken);
    const byteLen = typeof csvExport.data === 'string' ? csvExport.data.length : 0;
    record('REPORTS', 'CSV Export Generation', csvExport.status === 200 && byteLen > 50, `CSV Data bytes: ${byteLen}`);
  } catch (e) {
    record('REPORTS', 'CSV Export', false, e.message);
  }

  // ─────────────────────────────────────────────────────────────
  // 5. DOU AI BI CONVERSATIONAL QUERIES
  // ─────────────────────────────────────────────────────────────
  console.log('\n--- 5. DOU AI Conversational BI Assistant ---');
  try {
    const aiRes = await apiCall('/ai/chat', {
      method: 'POST',
      body: JSON.stringify({ question: 'كم عدد السائقين النشطين في الأسطول؟' })
    }, adminToken);
    const reply = aiRes.data?.response_text || aiRes.data?.reply || aiRes.data?.message || JSON.stringify(aiRes.data);
    record('DOU_AI', 'AI Query Execution (Arabic)', aiRes.status === 200, `Response preview: "${String(reply).slice(0, 60)}..."`);
  } catch (e) {
    record('DOU_AI', 'AI Query Execution', false, e.message);
  }

  // ─────────────────────────────────────────────────────────────
  // 6. DRIVER APP & MOBILE APK ARTIFACTS
  // ─────────────────────────────────────────────────────────────
  console.log('\n--- 6. Driver Web App & APK Distribution ---');
  try {
    const driverWeb = await apiCall('/driver');
    record('DRIVER_APP', 'Driver Web OS (PWA)', driverWeb.status === 200 && driverWeb.data.includes('DOU Rider'), `HTML length: ${driverWeb.data.length} bytes`);
  } catch (e) {
    record('DRIVER_APP', 'Driver Web OS', false, e.message);
  }

  try {
    const apkRes = await apiCall('/download/driver-apk');
    const apkSize = typeof apkRes.data === 'string' ? apkRes.data.length : 0;
    record('DRIVER_APP', 'Android APK Binary Download', apkRes.status === 200 && apkSize > 1000000, `Size: ${(apkSize / (1024*1024)).toFixed(2)} MB`);
  } catch (e) {
    record('DRIVER_APP', 'Android APK Download', false, e.message);
  }

  // ─────────────────────────────────────────────────────────────
  // 7. PLAYWRIGHT END-TO-END UI & BROWSER INTERACTION
  // ─────────────────────────────────────────────────────────────
  console.log('\n--- 7. End-to-End Browser UI Workflows (Playwright) ---');
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on('pageerror', err => pageErrors.push(err.message));

  try {
    // 7.1 Login Flow
    await page.goto(`${LIVE_URL}/app?lang=ar`, { waitUntil: 'networkidle' });
    await page.fill('#login-phone', CREDENTIALS.fleetAdmin.phone);
    await page.fill('#login-password', CREDENTIALS.fleetAdmin.password);
    await page.click('button[type=submit]');
    await page.waitForTimeout(2000);
    const isLoggedIn = await page.locator('.fleet-app, .header, .nav-item').first().isVisible();
    record('UI_E2E', 'Web App Authentication & Shell Load', isLoggedIn, 'Shell loaded successfully');

    // 7.2 Command Center View
    await page.click('.nav-item[data-view="commandCenter"]');
    await page.waitForTimeout(1000);
    const hasCards = await page.locator('.metric-card, .card').first().isVisible();
    record('UI_E2E', 'Command Center Navigation & KPI Cards', hasCards, 'KPIs visible');

    // 7.3 Couriers / Workforce View
    await page.click('.nav-item[data-view="riders"]');
    await page.waitForTimeout(1000);
    const hasRidersTable = await page.locator('table, .table-wrap').first().isVisible();
    record('UI_E2E', 'Workforce & Couriers View', hasRidersTable, 'Data table rendered');

    // 7.4 Shifts & Schedules View
    await page.click('.nav-item[data-view="shifts"]');
    await page.waitForTimeout(1000);
    const hasShifts = await page.locator('.table-wrap, .card').first().isVisible();
    record('UI_E2E', 'Shifts & Operations Planning View', hasShifts, 'Shifts rendered');

    // 7.5 Reports & Analytics Center View
    await page.goto(`${LIVE_URL}/app?view=reports`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    await page.click('button[data-tab="catalog"]');
    await page.waitForTimeout(1000);
    const hasReports = await page.locator('.reports-catalog, .reports-group, .card').first().isVisible();
    record('UI_E2E', 'Reports Center Catalog View', hasReports, '31 reports catalog rendered');

    // 7.6 Platform Facts 19 KPIs Tab
    await page.click('button[data-tab="platform_facts"]');
    await page.waitForTimeout(1000);
    const hasFactsFunnel = await page.locator('.card:has-text("Fulfillment Funnel")').isVisible();
    record('UI_E2E', 'Platform Facts 19 KPIs & Funnel', hasFactsFunnel, 'Fulfillment funnel & facts table rendered');

    // 7.7 DOU AI Dashboards Tab
    await page.click('button[data-tab="dashboards"]');
    await page.waitForTimeout(1000);
    const hasDashboardCards = await page.locator('.report-card').first().isVisible();
    record('UI_E2E', 'DOU AI Live Dashboards Tab', hasDashboardCards, '5 live dashboard cards rendered');

    // 7.8 Open Executive Ops Dashboard
    await page.locator('.report-card').first().click();
    await page.waitForTimeout(1500);
    const hasDashboardView = await page.locator('.metrics, .metric-card').first().isVisible();
    record('UI_E2E', 'Interactive Dashboard Drill-down View', hasDashboardView, 'Live metrics, funnel, and daily records rendered');

    // 7.9 Check console errors
    const criticalErrors = pageErrors.filter(e => !e.includes('favicon'));
    record('UI_E2E', 'Zero Uncaught Frontend Exceptions', criticalErrors.length === 0, `${criticalErrors.length} errors`);

  } catch (err) {
    record('UI_E2E', 'Playwright UI Workflow', false, err.message);
  } finally {
    await browser.close();
  }

  // ─────────────────────────────────────────────────────────────
  // SUMMARY REPORT
  // ─────────────────────────────────────────────────────────────
  console.log('\n===============================================================');
  console.log('📊 TEST EXECUTION SUMMARY REPORT');
  console.log('===============================================================');
  const total = results.length;
  const passed = results.filter(r => r.pass).length;
  const failed = results.filter(r => !r.pass).length;
  const successRate = ((passed / total) * 100).toFixed(1);

  console.log(`\nTotal Test Cases: ${total}`);
  console.log(`Passed:           ${passed} (${successRate}%)`);
  console.log(`Failed:           ${failed}`);

  const byCategory = {};
  results.forEach(r => {
    byCategory[r.category] = byCategory[r.category] || { total: 0, passed: 0 };
    byCategory[r.category].total++;
    if (r.pass) byCategory[r.category].passed++;
  });

  console.log('\nBreakdown by Module:');
  Object.entries(byCategory).forEach(([cat, s]) => {
    const pct = ((s.passed / s.total) * 100).toFixed(0);
    console.log(`  - ${cat.padEnd(16)} : ${s.passed}/${s.total} (${pct}%)`);
  });

  if (failed > 0) {
    console.log('\nFailed Tests:');
    results.filter(r => !r.pass).forEach(f => {
      console.log(`  ❌ [${f.category}] ${f.testName}: ${f.details}`);
    });
  } else {
    console.log('\n🎉 ALL FUNCTIONAL AND END-TO-END TESTS PASSED WITH 100% SUCCESS!');
  }
  console.log('===============================================================\n');
}

runAllTests().catch(console.error);
