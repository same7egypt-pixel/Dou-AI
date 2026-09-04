// Fleet OS entry point
import { api } from '../shared/api/client.js';
import { appStore } from '../shared/state/store.js';
import { requireAuth, renderLogin } from '../shared/auth/guard.js';
import { renderShell, registerViewLoaders, go } from './shell.js';
import { loadCommandCenter } from './views/commandCenter.js';
import { loadRiders } from './views/riders.js';
import { loadRider360 } from './views/rider360.js';
import { loadShifts } from './views/shifts.js';
import { loadNeedsAttention } from './views/needsAttention.js';
import { loadCapacity } from './views/capacity.js';
import { loadReports } from './views/reports.js';
import { loadPayroll } from './views/payroll.js';
const loadVendors = (c) => import('./views/vendors.js').then((m) => m.renderVendors(c));
const loadPlatformLink = (c) => import('./views/platformLink.js').then((m) => m.renderPlatformLink(c));
const loadIntegration = (c) => import('./views/integration.js').then((m) => m.renderIntegration(c));
const loadImports = (c) => import('./views/imports.js').then((m) => m.renderImports(c));
import { loadDouAI } from './views/douai.js';
const loadSettings = (c) => import('./views/settings.js').then((m) => m.loadSettings(c));
import { refreshNotificationCount } from '../shared/components/notifications.js';
import { initLang, startAutoTranslate } from '../shared/i18n/i18n.js';

initLang();
startAutoTranslate();

async function startApp() {
  const me = await requireAuth();
  if (!me) {
    renderLogin();
    return;
  }
  // An account with no tenant has nothing to draw here: every screen behind
  // this shell is tenant-scoped and answers 403. It used to render the full
  // sidebar anyway and fail ten times in a row. The server says where the
  // account belongs; send it there and say why.
  if (!me.tenant && Array.isArray(me.surfaces) && me.surfaces.length) {
    const target = me.surfaces[0];
    document.getElementById('app').innerHTML =
      `<div style="max-width:520px;margin:18vh auto;padding:28px;text-align:center;direction:rtl;
                   background:var(--card);border:1px solid var(--border);border-radius:16px">
         <div style="font-size:34px;margin-bottom:10px">🔀</div>
         <h2 style="margin:0 0 10px;font-size:18px">هذه ليست الشاشة المناسبة لحسابك</h2>
         <p style="font-size:13px;color:var(--muted);line-height:1.9;margin:0 0 20px">
           ${me.surface_notice || 'حسابك لا يتبع شركة، ولا توجد بيانات لعرضها هنا.'}
         </p>
         <a href="${target}" style="display:inline-block;padding:10px 22px;border-radius:10px;
            background:var(--primary);color:#fff;text-decoration:none;font-weight:700;font-size:13px">
           الانتقال إلى ${target}
         </a>
       </div>`;
    return;
  }
  const requested = new URLSearchParams(location.search).get('view');
  registerViewLoaders({
    commandCenter: loadCommandCenter,
    riders: loadRiders,
    imports: loadImports,
    rider360: loadRider360,
    shifts: loadShifts,
    needsAttention: loadNeedsAttention,
    capacity: loadCapacity,
    reports: loadReports,
    payroll: loadPayroll,
    vendors: loadVendors,
    platformLink: loadPlatformLink,
    integration: loadIntegration,
    douai: loadDouAI,
    settings: loadSettings,
  });
  renderShell();
  refreshNotificationCount();
  if (requested) go(requested);
}

// Expose for login handler
window.__bootApp = startApp;

// If already authenticated, start immediately
const token = api.getToken();
if (token) {
  startApp();
} else {
  renderLogin();
}
