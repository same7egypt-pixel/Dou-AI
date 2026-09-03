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
  const requested = new URLSearchParams(location.search).get('view');
  registerViewLoaders({
    commandCenter: loadCommandCenter,
    riders: loadRiders,
    rider360: loadRider360,
    shifts: loadShifts,
    needsAttention: loadNeedsAttention,
    capacity: loadCapacity,
    reports: loadReports,
    payroll: loadPayroll,
    vendors: loadVendors,
    platformLink: loadPlatformLink,
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
