import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:8123';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();

await page.goto(`${BASE}/app/v2/`);
await page.waitForLoadState('networkidle');

// Print page structure
const html = await page.evaluate(() => document.body.innerHTML.substring(0, 3000));
console.log('PAGE HTML:', html);

await browser.close();
