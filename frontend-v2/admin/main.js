// Super Admin entry point
import { api } from '../shared/api/client.js';
import { requireAuth, renderLogin } from '../shared/auth/guard.js';
import { renderShell, registerViewLoaders } from './shell.js';
import { loadOverview } from './views/overview.js';
import { loadTenants } from './views/tenants.js?v=20260831-2';
import { loadFlexBookings } from './views/flexBookings.js';
import { loadRevenue, loadPlans, loadUsage, loadHealth, loadIntegrations, loadAudit, loadSettings } from './views/platform.js';
import { initLang, startAutoTranslate } from '../shared/i18n/i18n.js';

initLang();
startAutoTranslate();

function customizeLogin() {
  document.querySelector('.login-sub').textContent = 'سجل دخول إدارة المنصة';
  document.querySelector('h1').textContent = 'Super Admin';
  document.querySelector('.login-foot').textContent = 'لوحة محمية بفريق DOU — الدخول بـX-Admin-Key أو JWT';
}

async function startApp() {
  const me = await requireAuth();
  if (!me) {
    renderLogin();
    customizeLogin();
    return;
  }
  registerViewLoaders({
    overview: loadOverview,
    tenants: loadTenants,
    flexBookings: loadFlexBookings,
    revenue: loadRevenue,
    plans: loadPlans,
    usage: loadUsage,
    health: loadHealth,
    integrations: loadIntegrations,
    audit: loadAudit,
    settings: loadSettings,
  });
  renderShell();
}

window.__bootApp = startApp;

const token = api.getToken();
if (token) {
  startApp();
} else {
  // Customize login for Super Admin
  renderLogin();
  customizeLogin();
}
