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

  root.innerHTML = '';
  
  const screen = document.createElement('div');
  screen.className = 'login-screen';

  const langContainer = document.createElement('div');
  langContainer.style.cssText = 'position:absolute;top:20px;left:20px;z-index:10;';

  const langBtn = document.createElement('button');
  langBtn.id = 'login-lang-btn';
  langBtn.className = 'btn btn-ghost btn-small';
  langBtn.style.cssText = 'font-weight:700;font-size:12px;background:rgba(255,255,255,0.08);color:#fff;border-radius:20px;padding:6px 14px;border:1px solid rgba(255,255,255,0.2);cursor:pointer';
  langBtn.textContent = `🌐 ${nextLangLabel}`;
  langBtn.addEventListener('click', () => {
    toggleLang();
    renderLogin(error);
  });
  langContainer.appendChild(langBtn);
  screen.appendChild(langContainer);

  const card = document.createElement('div');
  card.className = 'login-card';

  const logo = document.createElement('div');
  logo.className = 'login-logo';
  logo.textContent = 'DOU';
  card.appendChild(logo);

  const h1 = document.createElement('h1');
  h1.textContent = 'Fleet Partners';
  card.appendChild(h1);

  const sub = document.createElement('p');
  sub.className = 'login-sub';
  sub.textContent = t('سجل دخول شركتك اللوجستية');
  card.appendChild(sub);

  if (error) {
    const errDiv = document.createElement('div');
    errDiv.className = 'error-banner';
    errDiv.textContent = error;
    card.appendChild(errDiv);
  }

  const form = document.createElement('form');
  form.id = 'login-form';

  const lblPhone = document.createElement('label');
  lblPhone.textContent = t('رقم الجوال (بمفتاح الدولة)');
  form.appendChild(lblPhone);

  const inpPhone = document.createElement('input');
  inpPhone.id = 'login-phone';
  inpPhone.dir = 'ltr';
  inpPhone.placeholder = '9665xxxxxxxx';
  inpPhone.required = true;
  form.appendChild(inpPhone);

  const lblPass = document.createElement('label');
  lblPass.textContent = t('كلمة المرور (8 أحرف)');
  form.appendChild(lblPass);

  const inpPass = document.createElement('input');
  inpPass.id = 'login-password';
  inpPass.type = 'password';
  inpPass.dir = 'ltr';
  inpPass.minLength = 8;
  inpPass.required = true;
  form.appendChild(inpPass);

  const submitBtn = document.createElement('button');
  submitBtn.type = 'submit';
  submitBtn.className = 'btn btn-primary btn-full';
  submitBtn.style.cssText = 'background: #ff5500; color: #fff; border: none; border-radius: 12px; padding: 12px 20px; font-weight: 700; font-size: 14px; cursor: pointer; width: 100%; margin-top: 14px; box-shadow: 0 4px 14px rgba(255, 85, 0, 0.35); transition: all 0.2s;';
  submitBtn.textContent = t('دخول الشركة');
  form.appendChild(submitBtn);

  card.appendChild(form);

  const foot = document.createElement('p');
  foot.className = 'login-foot';
  foot.textContent = t('الحسابات الجديدة يفعّلها فريق DOU');
  card.appendChild(foot);

  screen.appendChild(card);
  root.appendChild(screen);

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

