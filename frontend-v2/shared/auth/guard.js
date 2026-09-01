// Auth guard + login view
import { api } from '../api/client.js';
import { appStore } from '../state/store.js';
import { t, getLang, toggleLang } from '../i18n/i18n.js';

export async function requireAuth() {
  const token = api.getToken();
  if (!token) return null;
  try {
    const me = await api.me();
    appStore.set({ user: me, tenant: me.tenant, role: me.role, permissions: me.permissions || [], ready: true });
    return me;
  } catch (e) {
    api.clearToken();
    return null;
  }
}

function esc(str) {
  return String(str || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function renderLogin(error = null) {
  const root = document.getElementById('app') || document.body;
  const currentLang = getLang();
  const nextLangLabel = currentLang === 'ar' ? 'English (EN)' : 'العربية (AR)';

  root.innerHTML = `
    <div class="login-screen">
      <div style="position:absolute;top:20px;left:20px;z-index:10;">
        <button id="login-lang-btn" class="btn btn-ghost btn-small" style="font-weight:700;font-size:12px;background:rgba(255,255,255,0.08);color:#fff;border-radius:20px;padding:6px 14px;border:1px solid rgba(255,255,255,0.2);cursor:pointer">
          🌐 ${nextLangLabel}
        </button>
      </div>
      <div class="login-card">
        <div class="login-logo">DOU</div>
        <h1>Fleet Partners</h1>
        <p class="login-sub">${t('سجل دخول شركتك اللوجستية')}</p>
        ${error ? `<div class="error-banner">${esc(error)}</div>` : ''}
        <form id="login-form">
          <label>${t('رقم الجوال (بمفتاح الدولة)')}</label>
          <input id="login-phone" dir="ltr" placeholder="9665xxxxxxxx" required />
          <label>${t('كلمة المرور (8 أحرف)')}</label>
          <input id="login-password" type="password" dir="ltr" minlength="8" required />
          <button type="submit" class="btn-primary full">${t('دخول الشركة')}</button>
        </form>
        <p class="login-foot">${t('الحسابات الجديدة يفعّلها فريق DOU')}</p>
      </div>
    </div>`;

  const langBtn = document.getElementById('login-lang-btn');
  if (langBtn) {
    langBtn.addEventListener('click', () => {
      toggleLang();
      renderLogin(error);
    });
  }

  document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const phone = document.getElementById('login-phone').value.trim();
    const password = document.getElementById('login-password').value;
    try {
      await api.login(phone, password);
      window.__bootApp();
    } catch (err) {
      renderLogin(err.message || (getLang() === 'ar' ? 'فشل الدخول. تحقق من البيانات.' : 'Login failed. Please check your credentials.'));
    }
  });
}

