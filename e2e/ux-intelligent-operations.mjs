// e2e/ux-intelligent-operations.mjs — Playwright Browser Acceptance Test Suite for UI/UX & Intelligent Operations
import { chromium } from 'playwright';

const BASE_URL = 'http://127.0.0.1:8123';
const ACCOUNTS = {
  companyAdmin: { phone: '966511111111', password: 'Company123!' },
  operations: { phone: '966522222222', password: 'Ops123456!' },
  supervisor: { phone: '966533333333', password: 'Super1234!' },
  finance: { phone: '966577777777', password: 'Finance123!' },
};

const results = [];
function record(testId, status, details = '') {
  results.push({ testId, status, details });
  const icon = status === 'PASS' ? '✓' : '✗';
  console.log(`  ${icon} ${testId} — ${details}`);
}

async function login(page, { phone, password }) {
  await page.goto(`${BASE_URL}/app/v2/`);
  await page.waitForSelector('#login-phone', { timeout: 10000 });
  await page.fill('#login-phone', phone);
  await page.fill('#login-password', password);
  await page.click('button[type="submit"]');
  await page.waitForSelector('.fleet-app', { timeout: 10000 });
  return { success: true };
}

async function run() {
  console.log('\n=== DOU FLEET OS: UI/UX & INTELLIGENT OPERATIONS ACCEPTANCE ===\n');

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
    // -----------------------------------------------------------------
    // PART 1: DESIGN SYSTEM & VISUAL TOKENS
    // -----------------------------------------------------------------
    console.log('--- PART 1: DESIGN SYSTEM & VISUAL INTEGRITY ---\n');
    await login(page, ACCOUNTS.companyAdmin);
    record('UX-01: Admin login & app shell render', 'PASS', 'App shell mounted');

    // Check RTL direction
    const dir = await page.evaluate(() => document.body.getAttribute('direction') || window.getComputedStyle(document.body).direction);
    record('UX-02: RTL layout & Arabic typography', dir === 'rtl' ? 'PASS' : 'FAIL', `Direction: ${dir}`);

    // Check Design System Tokens
    const designTokens = await page.evaluate(() => {
      const style = window.getComputedStyle(document.documentElement);
      return {
        aiAccent: style.getPropertyValue('--ai').trim(),
        primaryNav: style.getPropertyValue('--nav').trim(),
        blueBrand: style.getPropertyValue('--blue').trim(),
        greenStatus: style.getPropertyValue('--green').trim(),
        redStatus: style.getPropertyValue('--red').trim(),
      };
    });
    record('UX-03: Design system color tokens present', (designTokens.aiAccent && designTokens.blueBrand) ? 'PASS' : 'FAIL', `AI: ${designTokens.aiAccent}, Blue: ${designTokens.blueBrand}`);

    // -----------------------------------------------------------------
    // PART 2: COMMAND CENTER ("ماذا يحدث؟ وماذا أفعل؟")
    // -----------------------------------------------------------------
    console.log('\n--- PART 2: COMMAND CENTER & OPERATIONAL STATUS ---\n');
    await page.click('.nav-item[data-view="commandCenter"]');
    await page.waitForSelector('.ops-status-bar', { timeout: 5000 });

    const statusBar = await page.$('.ops-status-bar');
    const statusText = await page.textContent('.ops-status-pill');
    record('UX-04: Live operational status bar rendered', (statusBar && statusText) ? 'PASS' : 'FAIL', `Status: ${statusText.trim()}`);

    // Check Contextual AI Prompt Chips in Command Center
    const aiChips = await page.$$('.ai-prompt-bar .ai-chip');
    record('UX-05: Contextual AI prompt chips in Command Center', aiChips.length >= 3 ? 'PASS' : 'FAIL', `Found ${aiChips.length} prompt chips`);

    // Check Clickable KPI Metric Drill-down: Click "غائبون اليوم" -> navigates to shifts
    const absentCard = await page.$('.metric:has-text("غائبون اليوم")');
    if (absentCard) {
      await absentCard.click();
      await page.waitForSelector('.tab[data-subtab]', { timeout: 5000 });
      const currentCrumb = await page.textContent('#crumb');
      record('UX-06: Clickable KPI drill-down to Shifts', currentCrumb.includes('الورديات') ? 'PASS' : 'FAIL', `Navigated to: ${currentCrumb}`);
    } else {
      record('UX-06: Clickable KPI drill-down to Shifts', 'FAIL', 'Card not found');
    }

    // Return to Command Center and check Priority Action Queue
    await page.click('.nav-item[data-view="commandCenter"]');
    await page.waitForSelector('.priority-action-card, .state-empty', { timeout: 5000 });
    const actionCards = await page.$$('.priority-action-card');
    record('UX-07: Prioritized Action Queue rendered', actionCards.length > 0 ? 'PASS' : 'FAIL', `Found ${actionCards.length} action items`);

    // -----------------------------------------------------------------
    // PART 3: CONTEXTUAL AI ASSISTANT DRAWER (CROSS-PRODUCT)
    // -----------------------------------------------------------------
    console.log('\n--- PART 3: CONTEXTUAL AI ASSISTANT DRAWER ---\n');
    const drawerBtn = await page.$('#btn-open-ai-drawer');
    record('UX-08: Global Assistant button in TopBar', drawerBtn ? 'PASS' : 'FAIL', 'TopBar trigger present');

    if (drawerBtn) {
      await drawerBtn.click();
      await page.waitForSelector('#ai-drawer.open', { timeout: 5000 });
      const drawerContext = await page.textContent('#ai-drawer-context');
      record('UX-09: Contextual Assistant Drawer opens with screen context', drawerContext.includes('مركز القيادة') ? 'PASS' : 'FAIL', `Context: ${drawerContext.trim()}`);

      // Click a contextual chip inside drawer to query AI
      const firstDrawerChip = await page.$('#ai-drawer-prompts-wrap .ai-chip');
      if (firstDrawerChip) {
        const chipText = await firstDrawerChip.textContent();
        await firstDrawerChip.click();
        await page.waitForSelector('#ai-drawer-messages .ai-msg.assistant', { timeout: 8000 });
        const aiResponseText = await page.textContent('#ai-drawer-messages .ai-msg.assistant:last-child');
        record('UX-10: Contextual query executed and rendered in Drawer', aiResponseText.length > 10 ? 'PASS' : 'FAIL', `Query: "${chipText}", Response: ${aiResponseText.slice(0, 50)}...`);
      } else {
        record('UX-10: Contextual query executed and rendered in Drawer', 'FAIL', 'Drawer chip not found');
      }

      // Close drawer
      await page.click('#ai-drawer .btn-close');
      await page.waitForTimeout(400);
      const isDrawerOpen = await page.evaluate(() => document.getElementById('ai-drawer')?.classList.contains('open'));
      record('UX-11: Assistant Drawer closes cleanly', !isDrawerOpen ? 'PASS' : 'FAIL', 'Drawer dismissed');
    }

    // -----------------------------------------------------------------
    // PART 4: SHIFTS VIEW CONTEXTUAL ASSISTANCE
    // -----------------------------------------------------------------
    console.log('\n--- PART 4: SHIFTS & ATTENDANCE CONTEXTUAL UX ---\n');
    await page.click('.nav-item[data-view="shifts"]');
    await page.waitForSelector('.tabs', { timeout: 5000 });

    // Open drawer on shifts view and verify context switches to shifts
    await page.click('#btn-open-ai-drawer');
    await page.waitForSelector('#ai-drawer.open', { timeout: 5000 });
    const shiftsDrawerContext = await page.textContent('#ai-drawer-context');
    record('UX-12: Drawer updates context dynamically on Shifts view', shiftsDrawerContext.includes('الورديات') ? 'PASS' : 'FAIL', `Context: ${shiftsDrawerContext.trim()}`);
    await page.click('#ai-drawer .btn-close');
    await page.waitForTimeout(300);

    // -----------------------------------------------------------------
    // PART 5: PAYROLL FINANCIAL CLARITY & CURRENCY FORMATTING
    // -----------------------------------------------------------------
    console.log('\n--- PART 5: PAYROLL & FINANCIAL TRANSPARENCY ---\n');
    await page.click('.nav-item[data-view="payroll"]');
    await page.waitForSelector('.cards', { timeout: 5000 });
    const payrollMetrics = await page.$$('.metric');
    const grossText = await page.textContent('.metric:first-child b');
    record('UX-13: Payroll metric cards rendered with currency', (payrollMetrics.length === 4 && grossText.includes('ر.س')) ? 'PASS' : 'FAIL', `Gross: ${grossText}`);

    const payrollPrompts = await page.$$('.ai-prompt-bar .ai-chip');
    record('UX-14: Financial contextual queries rendered in Payroll view', payrollPrompts.length >= 1 ? 'PASS' : 'FAIL', `Found ${payrollPrompts.length} financial chips`);

    // -----------------------------------------------------------------
    // PART 6: FULL DOU AI SCREEN WITH STRUCTURED VERIFIED DATA
    // -----------------------------------------------------------------
    console.log('\n--- PART 6: DEDICATED DOU AI SCREEN ---\n');
    await page.click('.nav-item[data-view="douai"]');
    await page.waitForSelector('.ai-shell', { timeout: 5000 });
    const aiShell = await page.$('.ai-shell');
    record('UX-15: Full DOU AI workspace rendered', aiShell ? 'PASS' : 'FAIL', 'Conversational BI layout loaded');

    // Click suggested prompt on full screen
    const promptBtn = await page.$('.ai-prompt:has-text("ما الذي يحتاج انتباهي اليوم؟")');
    if (promptBtn) {
      await promptBtn.click();
      await page.waitForSelector('#ai-messages .ai-msg.assistant', { timeout: 8000 });
      const fullResponse = await page.textContent('#ai-messages .ai-msg.assistant:last-child');
      const meta = await page.textContent('#ai-messages .ai-meta');
      record('UX-16: DOU AI answers with verified latency & source metadata', (fullResponse && meta.includes('المصدر')) ? 'PASS' : 'FAIL', `Meta: ${meta}`);
    } else {
      record('UX-16: DOU AI answers with verified latency & source metadata', 'FAIL', 'Prompt button not found');
    }

    // -----------------------------------------------------------------
    // PART 7: ERROR INTEGRITY
    // -----------------------------------------------------------------
    console.log('\n--- PART 7: ERROR INTEGRITY ---\n');
    const unexpectedErrors = consoleErrors.filter(e => !e.includes('favicon') && !e.includes('test-seed'));
    record(
      'UX-17: Zero unexpected JS console errors',
      unexpectedErrors.length === 0 ? 'PASS' : 'FAIL',
      `${unexpectedErrors.length} errors: ${unexpectedErrors.slice(0, 3).join(', ')}`
    );
    record(
      'UX-18: Zero page runtime errors',
      pageErrors.length === 0 ? 'PASS' : 'FAIL',
      `${pageErrors.length} errors`
    );

  } catch (err) {
    console.error('Test run failed with unhandled exception:', err);
    record('FATAL', 'FAIL', err.message);
  } finally {
    await browser.close();
  }

  // Summary
  const passed = results.filter(r => r.status === 'PASS').length;
  const failed = results.filter(r => r.status === 'FAIL').length;
  console.log(`\n=== UX & INTELLIGENT OPERATIONS SUMMARY ===\n`);
  console.log(`Total: ${results.length}`);
  console.log(`Passed: ${passed}`);
  console.log(`Failed: ${failed}`);

  if (failed > 0) {
    process.exit(1);
  }
}

run();
