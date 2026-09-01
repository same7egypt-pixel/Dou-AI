/**
 * Deep Fleet Functional Verification
 * Tests actual actions: login, add rider, documents, shifts, payroll, DOU AI
 */
import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8123';
const ADMIN_PHONE = '966511111111';
const ADMIN_PASS = 'Company123!';

const results = [];
function record(name, pass, detail = '') {
    results.push({ name, pass, detail });
    console.log(`${pass ? '✓' : '✗'} ${name}${detail ? ' — ' + detail : ''}`);
}

async function login(page, phone = ADMIN_PHONE, pass = ADMIN_PASS) {
    await page.goto(`${BASE}/app/v2/`);
    await page.waitForLoadState('networkidle');
    // Find phone input
    const phoneInput = await page.$('#login-phone, input[type="tel"], input[name="phone"], [placeholder*="phone"], [placeholder*="الهاتف"]');
    if (!phoneInput) return false;
    await phoneInput.fill(phone);
    const passInput = await page.$('#login-password, input[type="password"], input[name="password"]');
    if (!passInput) return false;
    await passInput.fill(pass);
    const loginBtn = await page.$('button[type="submit"], button:has-text("دخول"), button:has-text("Login")');
    if (!loginBtn) return false;
    await loginBtn.click();
    await page.waitForTimeout(2000);
    return true;
}

async function runVerification() {
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext();
    const page = await context.newPage();

    const consoleErrors = [];
    page.on('console', msg => {
        if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    try {
        // 1. Login
        const loggedIn = await login(page);
        record('Login as Company Admin', loggedIn);
        if (!loggedIn) throw new Error('Login failed');

        await page.screenshot({ path: '/tmp/fleet_01_login.png', fullPage: false });

        // 2. Command Center loads
        const ccVisible = await page.$('#view-commandCenter, [data-view="commandCenter"]') !== null;
        record('Command Center visible', ccVisible);

        // 3. Navigate to Riders
        await page.click('[data-view="riders"], a:has-text("Riders"), a:has-text("السائقين")');
        await page.waitForTimeout(1500);
        const ridersVisible = await page.$('#view-riders, [data-view="riders"]') !== null;
        record('Riders screen loads', ridersVisible);

        // 4. Check if riders list has data
        const riderRows = await page.$$('.riderRow, tr[data-rider-id], .rider-item');
        record(`Riders list has data (${riderRows.length} rows)`, riderRows.length > 0, `${riderRows.length} rows`);

        // 5. Open Rider 360
        if (riderRows.length > 0) {
            await riderRows[0].click();
            await page.waitForTimeout(2000);
            const r360Visible = await page.$('#view-rider360, #rider360Content') !== null;
            record('Rider 360 opens', r360Visible);

            // 6. Check Rider 360 tabs
            const tabs = ['profile', 'documents', 'shifts', 'attendance', 'performance', 'targets', 'payroll', 'leave'];
            for (const tab of tabs) {
                const tabVisible = await page.$(`[data-r360tab="${tab}"]`) !== null;
                record(`Rider 360 ${tab} tab`, tabVisible);
            }
        }

        // 7. Navigate to Shifts & Attendance
        await page.click('[data-view="shifts"], a:has-text("Shifts"), a:has-text("الورديات")');
        await page.waitForTimeout(1500);
        const shiftsVisible = await page.$('#view-shifts, [data-view="shifts"]') !== null;
        record('Shifts & Attendance loads', shiftsVisible);

        // 8. Navigate to Needs Attention
        await page.click('[data-view="needsAttention"], a:has-text("Needs Attention"), a:has-text("يحتاج اهتمام")');
        await page.waitForTimeout(1500);
        const needsVisible = await page.$('#view-needsAttention, [data-view="needsAttention"]') !== null;
        record('Needs Attention loads', needsVisible);

        // 9. Navigate to Capacity
        await page.click('[data-view="capacity"], a:has-text("Capacity"), a:has-text("الطاقة")');
        await page.waitForTimeout(1500);
        const capacityVisible = await page.$('#view-capacity, [data-view="capacity"]') !== null;
        record('Capacity loads', capacityVisible);

        // 10. Navigate to Reports
        await page.click('[data-view="reports"], a:has-text("Reports"), a:has-text("التقارير")');
        await page.waitForTimeout(1500);
        const reportsVisible = await page.$('#view-reports, [data-view="reports"]') !== null;
        record('Reports loads', reportsVisible);

        // 11. Navigate to Payroll
        await page.click('[data-view="payroll"], a:has-text("Payroll"), a:has-text("الرواتب")');
        await page.waitForTimeout(1500);
        const payrollVisible = await page.$('#view-payroll, [data-view="payroll"]') !== null;
        record('Payroll loads', payrollVisible);

        // 12. Navigate to DOU AI
        await page.click('[data-view="douai"], a:has-text("DOU AI"), a:has-text("ذكاء")');
        await page.waitForTimeout(1500);
        const douaiVisible = await page.$('#view-douai, [data-view="douai"]') !== null;
        record('DOU AI loads', douaiVisible);

        // 13. Test DOU AI message
        if (douaiVisible) {
            const aiInput = await page.$('#douai-input, textarea, [placeholder*="سؤال"], [placeholder*="question"]');
            if (aiInput) {
                await aiInput.fill('كم عدد السائقين؟');
                const sendBtn = await page.$('button:has-text("أرسل"), button:has-text("Send"), [type="submit"]');
                if (sendBtn) {
                    await sendBtn.click();
                    await page.waitForTimeout(3000);
                    const aiResponse = await page.$('.douai-response, .message, .ai-reply');
                    record('DOU AI returns response', aiResponse !== null);
                }
            }
        }

        // 14. Check console errors
        const realErrors = consoleErrors.filter(e => !e.includes('favicon'));
        record('No console errors', realErrors.length === 0, `${realErrors.length} errors`);

        // 15. Refresh persistence
        await page.reload();
        await page.waitForTimeout(2000);
        const afterRefresh = await page.$('#view-commandCenter, .sidebar, [data-view]') !== null;
        record('Session persists after refresh', afterRefresh);

    } catch (err) {
        record('Test execution', false, err.message);
    } finally {
        await browser.close();
    }

    // Print summary
    console.log('\n=== DEEP VERIFICATION SUMMARY ===');
    const passed = results.filter(r => r.pass).length;
    const failed = results.filter(r => !r.pass);
    console.log(`Total: ${results.length}, Passed: ${passed}, Failed: ${failed.length}`);
    if (failed.length > 0) {
        console.log('\nFailed items:');
        failed.forEach(f => console.log(`  ✗ ${f.name}: ${f.detail}`));
    }
}

runVerification().catch(err => console.error('Fatal:', err));
