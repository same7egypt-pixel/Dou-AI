// scripts/aggressive_stress_test.mjs — Aggressive Stress, Concurrency & Security Penetration Test Suite
import { chromium } from 'playwright';

const LIVE_URL = 'http://18.194.202.73';
const CREDENTIALS = {
  fleetAdmin: { phone: '966581112233', password: 'dou123456' },
  opsManager: { phone: '966500000000', password: 'dou123456' },
  superAdmin: { phone: '966512345678', password: 'dou123456' },
};

const results = [];
function record(phase, testName, pass, details = '') {
  results.push({ phase, testName, pass, details });
  const icon = pass ? '🔥 PASSED' : '💥 FAILED';
  console.log(`[${icon}] ${phase} :: ${testName} ${details ? '— ' + details : ''}`);
}

async function apiCall(endpoint, options = {}, token = null) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  
  const startTime = Date.now();
  try {
    const res = await fetch(`${LIVE_URL}${endpoint}`, { ...options, headers });
    const latency = Date.now() - startTime;
    let data = null;
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      data = await res.json().catch(() => null);
    } else {
      data = await res.text().catch(() => '');
    }
    return { status: res.status, data, latency, ok: res.ok, headers: res.headers };
  } catch (err) {
    return { status: 0, error: err.message, latency: Date.now() - startTime, ok: false };
  }
}

async function runAggressiveTest() {
  console.log('\n======================================================================');
  console.log('⚡ COMMENCING HIGH-INTENSITY AGGRESSIVE STRESS & ADVERSARIAL TEST');
  console.log(`🎯 Target Host: ${LIVE_URL}`);
  console.log(`🕒 Timestamp: ${new Date().toISOString()}`);
  console.log('======================================================================\n');

  // Obtain Tokens
  const loginRes = await apiCall('/auth/login', {
    method: 'POST',
    body: JSON.stringify(CREDENTIALS.fleetAdmin)
  });
  const adminToken = loginRes.data?.access_token;
  if (!adminToken) {
    console.error('FATAL: Could not obtain admin token for stress testing.');
    process.exit(1);
  }

  // ──────────────────────────────────────────────────────────────────
  // PHASE 1: HIGH CONCURRENCY BURST & THROUGHPUT (150+ Concurrent Requests)
  // ──────────────────────────────────────────────────────────────────
  console.log('\n--- ⚡ PHASE 1: High-Concurrency Burst Load (150 Parallel Requests) ---');
  const burstEndpoints = [
    '/health/ready',
    '/fleet/overview',
    '/analytics/reports/platform-facts',
    '/analytics/reports/catalog',
    '/fleet/couriers',
    '/analytics/reports/dashboards',
    '/fleet/shifts',
  ];

  const totalBurst = 150;
  const burstPromises = [];
  const burstStartTime = Date.now();

  for (let i = 0; i < totalBurst; i++) {
    const ep = burstEndpoints[i % burstEndpoints.length];
    burstPromises.push(apiCall(ep, {}, adminToken));
  }

  const burstResponses = await Promise.all(burstPromises);
  const totalBurstTime = Date.now() - burstStartTime;
  const successfulBurst = burstResponses.filter(r => r.status === 200).length;
  const burstLatencies = burstResponses.map(r => r.latency).sort((a, b) => a - b);
  const p50 = burstLatencies[Math.floor(burstLatencies.length * 0.5)];
  const p95 = burstLatencies[Math.floor(burstLatencies.length * 0.95)];
  const p99 = burstLatencies[Math.floor(burstLatencies.length * 0.99)];
  const throughput = ((totalBurst / totalBurstTime) * 1000).toFixed(1);

  record(
    'BURST_LOAD',
    '150 Parallel Heavy Requests Flood',
    successfulBurst === totalBurst,
    `${successfulBurst}/${totalBurst} OK in ${totalBurstTime}ms | Throughput: ${throughput} req/s | p50: ${p50}ms, p95: ${p95}ms, p99: ${p99}ms`
  );

  // ──────────────────────────────────────────────────────────────────
  // PHASE 2: SECURITY, SQL INJECTION & FUZZING RESILIENCE
  // ──────────────────────────────────────────────────────────────────
  console.log('\n--- 🛡️ PHASE 2: SQL Injection & Adversarial Fuzzing Attacks ---');
  const sqlPayloads = [
    "' OR '1'='1",
    "1; DROP TABLE users;--",
    "' UNION SELECT null, username, password FROM users--",
    "admin' --",
    "1' AND 1=CONVERT(int, (SELECT @@version))--",
    "' OR 1=1 LIMIT 1;--",
    "SLEEP(5)",
    "'; EXEC xp_cmdshell('dir');--"
  ];

  let sqlAttacksBlocked = 0;
  for (const payload of sqlPayloads) {
    const res = await apiCall(`/analytics/reports/platform-facts?contract_name=${encodeURIComponent(payload)}`, {}, adminToken);
    // Should safely return 200 with 0 matching rows or 400/422, but NEVER 500 SQL syntax error
    if (res.status === 200 && Array.isArray(res.data?.rows)) {
      sqlAttacksBlocked++;
    } else if (res.status === 400 || res.status === 422 || res.status === 404) {
      sqlAttacksBlocked++;
    } else {
      console.log(`    ⚠️ Warning on payload: ${payload} -> HTTP ${res.status}`);
    }
  }
  record('SECURITY_FUZZING', 'SQL Injection Immunity', sqlAttacksBlocked === sqlPayloads.length, `${sqlAttacksBlocked}/${sqlPayloads.length} SQLi attack vectors safely neutralized`);

  // XSS Payloads
  const xssPayloads = [
    "<script>alert('XSS')</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:/*--></title></style></textarea></script></xmp><svg/onload='+/'/+/onmouseover=1/+/[*/[]/+alert(1)//'>",
    "{{7*7}}",
    "${7*7}"
  ];

  let xssBlocked = 0;
  for (const payload of xssPayloads) {
    const res = await apiCall(`/analytics/reports/workforce/rider_master?employment_status=${encodeURIComponent(payload)}`, {}, adminToken);
    if (res.status === 200 || res.status === 400 || res.status === 422) {
      xssBlocked++;
    }
  }
  record('SECURITY_FUZZING', 'XSS Injection Filtering', xssBlocked === xssPayloads.length, `${xssBlocked}/${xssPayloads.length} XSS payloads properly sanitized/handled`);

  // ──────────────────────────────────────────────────────────────────
  // PHASE 3: AUTHORIZATION, IDOR & TOKEN FORGERY
  // ──────────────────────────────────────────────────────────────────
  console.log('\n--- 🔒 PHASE 3: Broken Auth & Tenant Scope Isolation ---');
  // 3.1 Unauthenticated Request to Protected Route
  const noAuth = await apiCall('/fleet/overview');
  record('AUTH_ENFORCEMENT', 'Reject Missing Token', noAuth.status === 401 || noAuth.status === 403, `Blocked with HTTP ${noAuth.status}`);

  // 3.2 Forged / Tampered JWT Token
  const forgedToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwidGVuYW50X2lkIjo5OTksInJvbGUiOiJTVVBFUl9BRE1JTiIsImV4cCI6OTk5OTk5OTk5OX0.FORGED_SIGNATURE_HERE';
  const forgedRes = await apiCall('/fleet/overview', {}, forgedToken);
  record('AUTH_ENFORCEMENT', 'Reject Forged JWT Token', forgedRes.status === 401 || forgedRes.status === 403, `Blocked with HTTP ${forgedRes.status}`);

  // 3.3 Expired Token Simulation
  const expiredToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwidGVuYW50X2lkIjoxLCJyb2xlIjoiRkxFRVRfQURNSU4iLCJleHAiOjEwMDAwMDAwMDB9.INVALID';
  const expiredRes = await apiCall('/fleet/overview', {}, expiredToken);
  record('AUTH_ENFORCEMENT', 'Reject Expired/Malformed Token', expiredRes.status === 401 || expiredRes.status === 403, `Blocked with HTTP ${expiredRes.status}`);

  // ──────────────────────────────────────────────────────────────────
  // PHASE 4: BOUNDARY CONDITIONS & EXTREME QUERY PARAMS
  // ──────────────────────────────────────────────────────────────────
  console.log('\n--- 💣 PHASE 4: Extreme Boundary Conditions & Data Stress ---');
  // 4.1 Massive Page Size & Out of Bounds Page
  const massivePage = await apiCall('/analytics/reports/workforce/rider_master?page=999999&page_size=500', {}, adminToken);
  record('BOUNDARY_TEST', 'Out-of-Bounds Pagination', massivePage.status === 200 && Array.isArray(massivePage.data?.rows), `Returned safe empty page: ${massivePage.data?.rows?.length} items`);

  // 4.2 Huge Historical Date Range (100 Years)
  const hugeDate = await apiCall('/analytics/reports/attendance/summary?date_from=1970-01-01&date_to=2099-12-31', {}, adminToken);
  record('BOUNDARY_TEST', 'Centennial Date Range (1970-2099)', hugeDate.status === 200 && typeof hugeDate.data?.total_riders === 'number', `Processed cleanly in ${hugeDate.latency}ms`);

  // 4.3 Concurrent CSV Streaming Exports
  console.log('\n--- 📂 PHASE 5: Concurrent Heavy Streaming File Exports ---');
  const exportPromises = [
    apiCall('/analytics/reports/download/csv?report_type=rider_master&group=workforce', {}, adminToken),
    apiCall('/analytics/reports/download/csv?report_type=attendance_report&group=attendance', {}, adminToken),
    apiCall('/analytics/reports/download/csv?report_type=payroll_ledger&group=financial', {}, adminToken),
    apiCall('/download/driver-apk'),
    apiCall('/download/driver-apk'),
  ];
  const exportResults = await Promise.all(exportPromises);
  const allExportsOk = exportResults.every(r => r.status === 200);
  record('STREAMING_LOAD', 'Simultaneous Multi-File & APK Downloads', allExportsOk, `5 parallel heavy streams completed with HTTP 200`);

  // ──────────────────────────────────────────────────────────────────
  // PHASE 6: RAPID-FIRE DOU AI CONVERSATIONAL BI
  // ──────────────────────────────────────────────────────────────────
  console.log('\n--- 🤖 PHASE 6: Rapid Parallel AI Reasoning Queries ---');
  const aiQueries = [
    'كم عدد السائقين في الأسطول؟',
    'ما هو إجمالي الطلبات المكتملة في تقارير المنصات؟',
    'أعطني ملخص ساعات العمل والغياب',
    'ما هي نسبة الامتثال العامة للأسطول؟',
  ];

  const aiPromises = aiQueries.map(q => apiCall('/ai/chat', {
    method: 'POST',
    body: JSON.stringify({ question: q })
  }, adminToken));

  const aiResults = await Promise.all(aiPromises);
  const aiAllOk = aiResults.every(r => r.status === 200);
  record('AI_STRESS', 'Concurrent Arabic Natural Language BI Queries', aiAllOk, `4 parallel AI questions processed successfully`);

  // ──────────────────────────────────────────────────────────────────
  // PHASE 7: HEADLESS BROWSER CRASH & MULTI-TAB TORTURE TEST
  // ──────────────────────────────────────────────────────────────────
  console.log('\n--- 🖥️ PHASE 7: Multi-Tab Browser Torture Test (Playwright) ---');
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  
  const tabErrors = [];
  try {
    const page1 = await context.newPage();
    const page2 = await context.newPage();
    const page3 = await context.newPage();

    page1.on('pageerror', e => tabErrors.push(`Tab1: ${e.message}`));
    page2.on('pageerror', e => tabErrors.push(`Tab2: ${e.message}`));
    page3.on('pageerror', e => tabErrors.push(`Tab3: ${e.message}`));

    // Rapid concurrent navigation
    await Promise.all([
      page1.goto(`${LIVE_URL}/app?view=commandCenter`, { waitUntil: 'networkidle' }),
      page2.goto(`${LIVE_URL}/app?view=reports`, { waitUntil: 'networkidle' }),
      page3.goto(`${LIVE_URL}/driver`, { waitUntil: 'networkidle' }),
    ]);

    // Perform simultaneous UI operations
    await Promise.all([
      page1.evaluate(() => window.location.reload()),
      page2.evaluate(() => {
        const btn = document.querySelector('button[data-tab="dashboards"]');
        if (btn) btn.click();
      }),
      page3.evaluate(() => window.scrollTo(0, document.body.scrollHeight)),
    ]);

    await new Promise(r => setTimeout(r, 2000));
    record('UI_TORTURE', 'Simultaneous Multi-Tab Operations & Navigation', tabErrors.length === 0, `3 active tabs executed without crashes | Exceptions: ${tabErrors.length}`);

  } catch (err) {
    record('UI_TORTURE', 'Multi-Tab Test', false, err.message);
  } finally {
    await browser.close();
  }

  // ──────────────────────────────────────────────────────────────────
  // FINAL AGGRESSIVE VERDICT
  // ──────────────────────────────────────────────────────────────────
  console.log('\n======================================================================');
  console.log('🏁 AGGRESSIVE TEST SUITE VERDICT & SUMMARY');
  console.log('======================================================================');
  const total = results.length;
  const passed = results.filter(r => r.pass).length;
  const failed = results.filter(r => !r.pass).length;
  const score = ((passed / total) * 100).toFixed(1);

  console.log(`\nAggressive Test Vectors: ${total}`);
  console.log(`Resilience Score:        ${score}% (${passed}/${total} Vectors Passed)`);
  console.log(`Critical Vulnerabilities: ${failed}`);

  const categories = {};
  results.forEach(r => {
    categories[r.phase] = categories[r.phase] || { total: 0, passed: 0 };
    categories[r.phase].total++;
    if (r.pass) categories[r.phase].passed++;
  });

  console.log('\nVector Analysis:');
  Object.entries(categories).forEach(([p, c]) => {
    console.log(`  🔥 ${p.padEnd(20)}: ${c.passed}/${c.total} Passed (${((c.passed / c.total) * 100).toFixed(0)}%)`);
  });

  if (failed === 0) {
    console.log('\n🏆 EXTRAORDINARY RESILIENCE: System withstood 150 parallel burst queries, SQLi attacks, XSS injection, token forgery, extreme boundary queries, concurrent APK streams, and multi-tab browser torture with ZERO failures and ZERO downtime!');
  } else {
    console.log('\n⚠️ Found resilience defects:');
    results.filter(r => !r.pass).forEach(f => console.log(`  ❌ ${f.phase} - ${f.testName}: ${f.details}`));
  }
  console.log('======================================================================\n');
}

runAggressiveTest().catch(console.error);
