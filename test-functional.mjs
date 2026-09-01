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
    await page.waitForSelector('#login-form', { timeout: 5000 });
    await page.fill('#login-phone', phone);
    await page.fill('#login-password', pass);
    await page.click('button[type="submit"]');
    await page.waitForSelector('.fleet-app', { timeout: 5000 });
    return true;
}

async function run() {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    const consoleErrors = [];
    page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });

    try {
        // 1. Login
        const loggedIn = await login(page);
        record('Login as Company Admin', loggedIn);
        if (!loggedIn) throw new Error('Login failed');

        // 2. Navigate to Riders
        await page.click('.nav-item[data-view="riders"]');
        await page.waitForSelector('.table-wrap, .state-empty', { timeout: 5000 });

        // 3. Check riders table has rows
        await page.waitForSelector('.table-wrap table tbody tr', { timeout: 5000 });
        const riderRows = await page.$$('.table-wrap table tbody tr');
        record(`Riders table populated (${riderRows.length} rows)`, riderRows.length > 0, `${riderRows.length} rows`);

        // 4. Click on a rider to open Rider 360
        await page.click('.table-wrap table tbody tr:first-child button');
        await page.waitForSelector('#r360-select', { timeout: 5000 });
        record('Rider 360 opens', true);

        // 5. Check all 8 tabs
        for (const tab of ['profile', 'documents', 'shifts', 'attendance', 'performance', 'targets', 'payroll', 'leave']) {
            await page.click(`.tab[data-tab="${tab}"]`);
            await page.waitForSelector('.tab-pane .card, .tab-pane .table-wrap, .tab-pane .state-empty, .tab-pane .cards', { timeout: 5000 });
        }
        record('Rider 360 all 8 tabs load', true);

        // 6. Navigate to Shifts
        await page.click('.nav-item[data-view="shifts"]');
        await page.waitForSelector('.table-wrap, .state-empty', { timeout: 5000 });
        const shiftRows = await page.$$('.table-wrap table tbody tr');
        record(`Shifts screen populated (${shiftRows.length} shifts)`, shiftRows.length > 0, `${shiftRows.length} shifts`);

        // 7. Navigate to Command Center
        await page.click('.nav-item[data-view="commandCenter"]');
        await page.waitForSelector('.metric', { timeout: 5000 });
        const metrics = await page.$$('.metric');
        record(`Command Center KPIs (${metrics.length} metrics)`, metrics.length > 0, `${metrics.length} metrics`);

        // 8. Navigate to DOU AI
        await page.click('.nav-item[data-view="douai"]');
        await page.waitForSelector('.ai-shell', { timeout: 5000 });
        await page.fill('#ai-input', 'كم عدد السائقين؟');
        await page.click('#ai-send');
        await page.waitForSelector('.ai-msg.assistant', { timeout: 10000 });
        record('DOU AI returns response', true);

        // 9. Refresh persistence
        await page.reload();
        await page.waitForSelector('.fleet-app', { timeout: 5000 });
        record('Session persists after refresh', true);

        // 10. Console errors check
        const realErrors = consoleErrors.filter(e => !e.includes('favicon'));
        record('No console errors', realErrors.length === 0, `${realErrors.length} errors`);

    } catch (err) {
        record('Test execution', false, err.message);
    } finally {
        await browser.close();
    }

    console.log('\n=== SUMMARY ===');
    const passed = results.filter(r => r.pass).length;
    const failed = results.filter(r => !r.pass);
    console.log(`Total: ${results.length}, Passed: ${passed}, Failed: ${failed.length}`);
    if (failed.length) {
        console.log('\nFailed:');
        failed.forEach(f => console.log(`  ✗ ${f.name}: ${f.detail}`));
    }
}

run().catch(err => console.error('Fatal:', err));
