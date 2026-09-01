import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8123';

const results = [];
function record(name, pass, detail = '') {
    results.push({ name, pass, detail });
    console.log(`${pass ? '✓' : '✗'} ${name}${detail ? ' — ' + detail : ''}`);
}

async function login(page, phone, pass) {
    await page.goto(`${BASE}/app/v2/`);
    await page.waitForSelector('#login-form', { timeout: 5000 });
    await page.fill('#login-phone', phone);
    await page.fill('#login-password', pass);
    await page.click('button[type="submit"]');
    await page.waitForSelector('.fleet-app', { timeout: 5000 });
    return true;
}

async function runRole(name, phone, pass, checks) {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    try {
        await login(page, phone, pass);
        record(`${name} login`, true);
        for (const check of checks) {
            try {
                await check(page);
            } catch (e) {
                record(check.name, false, e.message);
            }
        }
    } catch (e) {
        record(`${name} login`, false, e.message);
    } finally {
        await browser.close();
    }
}

async function run() {
    // Company Admin
    await runRole('Company Admin', '966511111111', 'Company123!', [
        async (page) => {
            await page.click('.nav-item[data-view="riders"]');
            await page.waitForSelector('.table-wrap', { timeout: 5000 });
            const rows = await page.$$('.table-wrap table tbody tr');
            record('  Riders visible', rows.length > 0, `${rows.length} rows`);
        },
        async (page) => {
            await page.click('.nav-item[data-view="commandCenter"]');
            await page.waitForSelector('.metric', { timeout: 5000 });
            const m = await page.$$('.metric');
            record('  Command Center KPIs', m.length > 0, `${m.length} metrics`);
        },
        async (page) => {
            await page.click('.nav-item[data-view="payroll"]');
            await page.waitForSelector('.metric, .card', { timeout: 5000 });
            record('  Payroll loads', true);
        },
    ]);

    // Operations
    await runRole('Operations', '966522222222', 'Ops123456!', [
        async (page) => {
            await page.click('.nav-item[data-view="riders"]');
            await page.waitForSelector('.table-wrap', { timeout: 5000 });
            record('  Riders accessible', true);
        },
        async (page) => {
            await page.click('.nav-item[data-view="shifts"]');
            await page.waitForSelector('.table-wrap', { timeout: 5000 });
            record('  Shifts accessible', true);
        },
    ]);

    // Finance
    await runRole('Finance', '966577777777', 'Finance123!', [
        async (page) => {
            await page.click('.nav-item[data-view="payroll"]');
            await page.waitForSelector('.metric, .card', { timeout: 5000 });
            record('  Payroll accessible', true);
        },
        async (page) => {
            await page.click('.nav-item[data-view="reports"]');
            await page.waitForSelector('.reports-catalog, .state-empty', { timeout: 5000 });
            record('  Reports accessible', true);
        },
    ]);

    // Supervisor
    await runRole('Supervisor', '966533333333', 'Super1234!', [
        async (page) => {
            await page.click('.nav-item[data-view="riders"]');
            await page.waitForSelector('.table-wrap', { timeout: 5000 });
            const rows = await page.$$('.table-wrap table tbody tr');
            record('  Supervisor sees riders', rows.length > 0, `${rows.length} rows (scoped)`);
        },
    ]);

    // Sidebar check
    {
        const browser = await chromium.launch({ headless: true });
        const page = await browser.newPage();
        await login(page, '966511111111', 'Company123!');
        const navItems = await page.$$('.nav-item');
        const views = await page.evaluate(() => Array.from(document.querySelectorAll('.nav-item')).map(n => n.dataset.view));
        record('Sidebar has 8 items', navItems.length === 8, `${navItems.length} items: ${views.join(', ')}`);
        await browser.close();
    }

    console.log('\n=== COMPREHENSIVE SUMMARY ===');
    const passed = results.filter(r => r.pass).length;
    const failed = results.filter(r => !r.pass);
    console.log(`Total: ${results.length}, Passed: ${passed}, Failed: ${failed.length}`);
    if (failed.length) {
        console.log('\nFailed:');
        failed.forEach(f => console.log(`  ✗ ${f.name}: ${f.detail}`));
    }
}

run().catch(err => console.error('Fatal:', err));
