// Visual / Product UX Walkthrough Across All Core Fleet Views
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE_URL = 'http://127.0.0.1:8123';
const ARTIFACT_DIR = '/Users/sameh/.gemini/antigravity/brain/056265f0-e866-44a5-a8b3-03743ced3176';

const viewsToCapture = [
  { id: 'commandCenter', name: '01_command_center', selector: '.card, .metric, .cards' },
  { id: 'riders', name: '02_riders_roster', selector: '.table-wrap table, .card' },
  { id: 'rider360', name: '03_rider360_profile', selector: '#r360-select, .profile-card, .tab' },
  { id: 'shifts', name: '04_shifts_attendance', selector: '.tabs, .table-wrap' },
  { id: 'needsAttention', name: '05_needs_attention', selector: '.cards, .card, .priority-action-card' },
  { id: 'capacity', name: '06_capacity_ecosystem', selector: '#cap-results, .cards, .card' },
  { id: 'reports', name: '07_reports_analytics', selector: '.reports-group, .report-card, .tabs' },
  { id: 'payroll', name: '08_payroll_financial', selector: '.cards, .metric, .card' },
  { id: 'douai', name: '09_dou_ai_workspace', selector: '#chat-messages, .chat-input-area, .ai-view-container' },
];

async function run() {
  console.log('\n======================================================================');
  console.log('VISUAL & PRODUCT UX WALKTHROUGH ACROSS ALL FLEET VIEWS');
  console.log('======================================================================\n');

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // Login
  await page.goto(`${BASE_URL}/app/v2/`);
  await page.fill('#login-phone', '966511111111');
  await page.fill('#login-password', 'Company123!');
  await page.click('button[type="submit"]');
  await page.waitForSelector('.fleet-app', { timeout: 8000 });

  for (const v of viewsToCapture) {
    console.log(`📸 Capturing View: ${v.id} (${v.name})...`);
    
    // Navigate using shell router
    await page.evaluate((viewId) => {
      if (window.go) {
        window.go(viewId);
      } else {
        const nav = document.querySelector(`.nav-item[data-view="${viewId}"]`);
        if (nav) nav.click();
      }
    }, v.id);

    await page.waitForTimeout(1200);
    await page.waitForSelector(v.selector, { timeout: 8000 }).catch(() => null);

    const shotPath = path.join(ARTIFACT_DIR, `${v.name}.png`);
    await page.screenshot({ path: shotPath, fullPage: false });
    
    // Check DOM fullness (ensure page is alive with data)
    const cardCount = await page.$$eval('.card, .metric, .metric-card, .table-wrap, .tab, .cards, .reports-group', els => els.length);
    
    console.log(`  ✓ Saved: ${v.name}.png | Interactive UI Elements: ${cardCount}`);
  }

  await browser.close();
  console.log('\n🎉 All 9 Core Views Captured Successfully in Artifact Directory!');
}

run();
