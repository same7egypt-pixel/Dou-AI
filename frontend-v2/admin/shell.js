// Super Admin App Shell
import { api } from '../shared/api/client.js';
import { appStore } from '../shared/state/store.js';
import { el } from '../shared/components/ui.js';
import { t, getLang, toggleLang } from '../shared/i18n/i18n.js';

export const VIEWS = ['overview', 'tenants', 'tenantDetail', 'flexBookings', 'revenue', 'plans', 'usage', 'health', 'integrations', 'audit', 'settings'];

export const VIEW_LABELS_AR = {
  overview: 'لوحة القيادة', tenants: 'الشركات المشتركة', tenantDetail: 'تفاصيل الشركة',
  flexBookings: 'عقود المطاعم (DOU Flex)',
  revenue: 'التحصيل والإيرادات', plans: 'الباقات والأسعار', usage: 'الاستخدام والحدود',
  health: 'صحة المنصة', integrations: 'التكاملات', audit: 'سجل الإدارة', settings: 'إعدادات النظام',
};

export const VIEW_LABELS_EN = {
  overview: 'Dashboard Overview', tenants: 'Subscribed Companies', tenantDetail: 'Company Details',
  flexBookings: 'Restaurant Shifts (DOU Flex)',
  revenue: 'Revenue & Billing', plans: 'Plans & Pricing', usage: 'Usage & Limits',
  health: 'Platform Health', integrations: 'Integrations', audit: 'Audit Logs', settings: 'System Settings',
};

export const VIEW_LABELS = VIEW_LABELS_AR;

export const VIEW_ICONS = {
  overview: '▦', tenants: '🏢', tenantDetail: '🔍', flexBookings: '🏬', revenue: '💰',
  plans: '📋', usage: '📊', health: '♥', integrations: '🔗',
  audit: '📝', settings: '⚙',
};

let currentView = 'overview';
let viewLoaders = {};

export function registerViewLoaders(loaders) { viewLoaders = { ...viewLoaders, ...loaders }; }

export function renderShell() {
  const root = document.getElementById('app');
  root.innerHTML = '';
  root.className = 'fleet-app admin-app';
  root.append(renderSidebar(), el('main', { class: 'main-area' }, [renderTopBar(), el('div', { class: 'content-area', id: 'content-area' }, [])]));
  go(currentView);
}

function renderSidebar() {
  const isAr = getLang() === 'ar';
  const labels = isAr ? VIEW_LABELS_AR : VIEW_LABELS_EN;
  const nav = el('nav', { class: 'side-nav' });
  nav.append(el('div', { class: 'logo' }, [el('span', { class: 'logo-icon' }, '↗'), el('b', { text: 'DOU' }), el('small', { text: 'SUPER ADMIN' })]));
  const groups = isAr ? [
    { title: 'المنصة', views: ['overview', 'tenants', 'flexBookings'] },
    { title: 'المالية', views: ['revenue', 'plans', 'usage'] },
    { title: 'النظام', views: ['health', 'integrations', 'audit', 'settings'] },
  ] : [
    { title: 'PLATFORM', views: ['overview', 'tenants', 'flexBookings'] },
    { title: 'FINANCIALS', views: ['revenue', 'plans', 'usage'] },
    { title: 'SYSTEM', views: ['health', 'integrations', 'audit', 'settings'] },
  ];
  groups.forEach((g) => {
    nav.append(el('div', { class: 'nav-group' }, g.title));
    g.views.forEach((v) => nav.append(el('button', { class: `nav-item ${v === currentView ? 'active' : ''}`, 'data-view': v, onclick: () => go(v) }, [el('i', { text: VIEW_ICONS[v] }), el('span', { text: labels[v] || v })])));
  });
  return el('aside', { class: 'sidebar' }, [nav, renderUserCard()]);
}

function renderUserCard() {
  const isAr = getLang() === 'ar';
  const { user, tenant } = appStore.get();
  return el('div', { class: 'user-card' }, [
    el('div', { class: 'user-photo' }, '✓'),
    el('b', { text: user?.name || (isAr ? 'فريق DOU' : 'DOU Team') }),
    el('small', { text: tenant?.name || (isAr ? 'إدارة المنصة' : 'Platform Operations') }),
    el('button', { class: 'btn btn-ghost btn-small btn-full', onclick: () => { api.logout(); location.reload(); } }, isAr ? '🚪 خروج' : '🚪 Log Out'),
  ]);
}

function renderTopBar() {
  const isAr = getLang() === 'ar';
  const currentLang = getLang();
  const nextLangLabel = currentLang === 'ar' ? 'English (EN)' : 'العربية (AR)';
  const langToggleBtn = el('button', {
    class: 'btn btn-ghost btn-small',
    id: 'btn-toggle-lang-admin',
    style: 'font-weight:700;font-size:12px;border:1px solid var(--border);border-radius:20px;padding:5px 12px;cursor:pointer',
    title: currentLang === 'ar' ? 'Switch to English' : 'التحويل للغة العربية',
    onclick: () => {
      toggleLang();
    }
  }, `🌐 ${nextLangLabel}`);

  const labels = isAr ? VIEW_LABELS_AR : VIEW_LABELS_EN;
  return el('header', { class: 'top-bar' }, [
    el('div', { class: 'breadcrumb' }, ['DOU / Super Admin / ', el('b', { id: 'crumb', text: labels[currentView] || currentView })]),
    el('div', { class: 'top-actions', style: 'display:flex;gap:8px;align-items:center' }, [langToggleBtn]),
  ]);
}

export function go(view) {
  if (!VIEWS.includes(view)) return;
  currentView = view;
  const isAr = getLang() === 'ar';
  const labels = isAr ? VIEW_LABELS_AR : VIEW_LABELS_EN;
  document.querySelectorAll('.nav-item').forEach((n) => n.classList.toggle('active', n.dataset.view === view));
  const crumb = document.getElementById('crumb');
  if (crumb) crumb.textContent = labels[view] || view;
  const content = document.getElementById('content-area');
  if (!content) return;
  const loader = viewLoaders[view];
  if (loader) loader(content);
}
