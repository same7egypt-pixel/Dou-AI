// Settings — the account surface that only existed on the legacy dashboard.
//
// Company user management and change-password had live, working endpoints and
// no caller anywhere in this product: a company could not add an accountant,
// and an admin could not change their own password, without being sent to
// /static/fleet.html. This screen is what makes removing that screen safe.
import { api } from '../../shared/api/client.js';
import { appStore } from '../../shared/state/store.js';
import {
  el, loadingState, emptyState, errorState, table, badge, modal, metricCard,
  formRow, inputField, selectField, escapeHtml,
  money, showToast } from '../../shared/components/ui.js';
import { getLang } from '../../shared/i18n/i18n.js';

let activeTab = 'users';

const ROLE_LABELS = {
  COMPANY: { ar: 'مالك الحساب', en: 'Account owner' },
  COMPANY_ADMIN: { ar: 'مدير الشركة', en: 'Company admin' },
  OPERATIONS: { ar: 'العمليات', en: 'Operations' },
  HR: { ar: 'الموارد البشرية', en: 'HR' },
  ACCOUNTANT: { ar: 'المحاسبة', en: 'Accountant' },
  PROJECT_MANAGER: { ar: 'مدير مشروع', en: 'Project manager' },
  VIEWER: { ar: 'اطّلاع فقط', en: 'Viewer' },
  SUPERVISOR: { ar: 'مشرف ميداني', en: 'Field supervisor' },
};

// Mirrors MANAGEABLE_ROLES in app/routers/fleet.py. The owner role is not here
// on purpose: it is granted at account creation and cannot be handed out.
const ASSIGNABLE_ROLES = ['COMPANY_ADMIN', 'OPERATIONS', 'HR', 'ACCOUNTANT', 'PROJECT_MANAGER', 'VIEWER'];

const roleLabel = (role, isAr) =>
  ROLE_LABELS[role] ? (isAr ? ROLE_LABELS[role].ar : ROLE_LABELS[role].en) : role;

export async function loadSettings(container) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';

  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'إعدادات الحساب والوصول' : 'Account & access settings'),
      el('h1', { text: isAr ? 'الإعدادات' : 'Settings' }),
    ]),
    el('div', { class: 'header-actions' }, [
      el('button', { class: 'btn btn-ghost', onclick: () => loadSettings(container) },
        isAr ? '↻ تحديث' : '↻ Refresh'),
    ]),
  ]));

  const tabs = el('div', { class: 'tabs', style: 'margin-bottom:18px' }, [
    ['users', isAr ? '👥 مستخدمو الشركة' : '👥 Company users'],
    ['security', isAr ? '🔐 الأمان' : '🔐 Security'],
    ['subscription', isAr ? '💳 الاشتراك' : '💳 Subscription'],
  ].map(([id, label]) => el('button', {
    class: `tab ${activeTab === id ? 'active' : ''}`,
    'data-tab': id,
    onclick: () => { activeTab = id; loadSettings(container); },
  }, label)));

  const body = el('div', { id: 'settings-body' });
  container.append(tabs, body);

  body.append(loadingState(isAr ? 'جاري التحميل...' : 'Loading...'));
  try {
    const rendered = activeTab === 'users'
      ? await renderUsers(container)
      : activeTab === 'security'
        ? renderSecurity()
        : await renderSubscription();
    body.innerHTML = '';
    body.append(rendered);
  } catch (err) {
    body.innerHTML = '';
    body.append(errorState(
      (isAr ? 'تعذر التحميل: ' : 'Could not load: ') + err.message,
      () => loadSettings(container)
    ));
  }
}

// ── Company users ───────────────────────────────────────────────────────────
async function renderUsers(container) {
  const isAr = getLang() === 'ar';
  const role = appStore.get().role || localStorage.getItem('dou_role_v2');
  const canManage = ['COMPANY', 'COMPANY_ADMIN'].includes(role);
  const canDelete = ['COMPANY', 'COMPANY_ADMIN'].includes(role);

  const users = await api.get('/fleet/users');
  const wrap = el('div', {});

  wrap.append(el('div', { style: 'display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:14px' }, [
    el('p', { style: 'margin:0;color:var(--muted);font-size:12px' },
      isAr
        ? 'حسابات موظفي الشركة وصلاحياتهم. مالك الحساب لا يمكن حذفه أو تغيير دوره.'
        : 'Your company staff accounts and their access. The account owner cannot be removed or re-roled.'),
    canManage ? el('button', { class: 'btn btn-primary btn-blue', id: 'btn-add-user', onclick: () => openAddUser(container) },
      isAr ? '+ إضافة مستخدم' : '+ Add user') : null,
  ].filter(Boolean)));

  if (!users?.length) {
    wrap.append(emptyState(isAr ? 'لا يوجد مستخدمون بعد.' : 'No users yet.'));
    return wrap;
  }

  wrap.append(table([
    { key: 'name', label: isAr ? 'الاسم' : 'Name' },
    { key: 'phone', label: isAr ? 'جوال الدخول' : 'Sign-in mobile' },
    { key: 'role', label: isAr ? 'الدور' : 'Role', render: (v, row) =>
        row.is_owner
          ? badge(isAr ? 'مالك الحساب' : 'Account owner', 'blue')
          : roleLabel(v, isAr) },
    { key: 'is_active', label: isAr ? 'الحالة' : 'Status', render: (v) =>
        badge(v ? (isAr ? 'نشط' : 'Active') : (isAr ? 'موقوف' : 'Suspended'), v ? 'green' : 'red') },
    { key: 'actions', label: isAr ? 'إجراء' : 'Action', render: (_, row) =>
        row.is_owner || !canManage
          ? el('span', { style: 'color:var(--muted)' }, '—')
          : el('div', { class: 'inline-actions' }, [
              el('button', { class: 'btn btn-ghost btn-small', onclick: () => openEditUser(row, container) },
                isAr ? 'تعديل' : 'Edit'),
              el('button', {
                class: `btn btn-small ${row.is_active ? 'btn-ghost' : 'btn-green'}`,
                onclick: () => setUserActive(row, !row.is_active, container),
              }, row.is_active ? (isAr ? 'إيقاف' : 'Suspend') : (isAr ? 'تفعيل' : 'Activate')),
              canDelete ? el('button', { class: 'btn btn-red btn-small', onclick: () => deleteUser(row, container) },
                isAr ? 'حذف' : 'Delete') : null,
            ].filter(Boolean)) },
  ], users));
  return wrap;
}

function openAddUser(container) {
  const isAr = getLang() === 'ar';
  const content = el('form', { onsubmit: async (e) => {
    e.preventDefault();
    const msg = document.getElementById('su-msg');
    try {
      await api.post('/fleet/users', {
        name: document.getElementById('su-name').value.trim(),
        phone: document.getElementById('su-phone').value.trim(),
        password: document.getElementById('su-password').value,
        role: document.getElementById('su-role').value,
      });
      m.remove();
      loadSettings(container);
    } catch (err) {
      msg.style.color = 'var(--red)';
      msg.textContent = '❌ ' + err.message;
    }
  }}, [
    formRow([inputField('su-name', isAr ? 'الاسم' : 'Name', { required: true })]),
    formRow([inputField('su-phone', isAr ? 'جوال الدخول' : 'Sign-in mobile',
      { required: true, placeholder: '9665xxxxxxxx' })]),
    formRow([inputField('su-password', isAr ? 'كلمة المرور (8 أحرف على الأقل)' : 'Password (at least 8 characters)',
      { type: 'password', required: true, minlength: 8 })]),
    formRow([selectField('su-role', isAr ? 'الدور' : 'Role',
      ASSIGNABLE_ROLES.map((r) => ({ value: r, label: roleLabel(r, isAr) })), 'OPERATIONS')]),
    el('p', { id: 'su-msg', style: 'margin:8px 0 0;font-size:12px' }),
    el('button', { class: 'btn btn-primary btn-blue btn-full', type: 'submit', style: 'margin-top:12px' },
      isAr ? 'إضافة المستخدم' : 'Add user'),
  ]);
  const m = modal(isAr ? '➕ إضافة مستخدم للشركة' : '➕ Add a company user', content);
}

function openEditUser(row, container) {
  const isAr = getLang() === 'ar';
  const content = el('form', { onsubmit: async (e) => {
    e.preventDefault();
    const msg = document.getElementById('eu-msg');
    try {
      await api.patch(`/fleet/users/${row.id}`, {
        name: document.getElementById('eu-name').value.trim(),
        role: document.getElementById('eu-role').value,
      });
      m.remove();
      loadSettings(container);
    } catch (err) {
      msg.style.color = 'var(--red)';
      msg.textContent = '❌ ' + err.message;
    }
  }}, [
    formRow([inputField('eu-name', isAr ? 'الاسم' : 'Name', { value: row.name || '', required: true })]),
    formRow([selectField('eu-role', isAr ? 'الدور' : 'Role',
      ASSIGNABLE_ROLES.map((r) => ({ value: r, label: roleLabel(r, isAr) })), row.role)]),
    el('p', { id: 'eu-msg', style: 'margin:8px 0 0;font-size:12px' }),
    el('button', { class: 'btn btn-primary btn-blue btn-full', type: 'submit', style: 'margin-top:12px' },
      isAr ? 'حفظ' : 'Save'),
  ]);
  const m = modal(`✏️ ${isAr ? 'تعديل' : 'Edit'} ${escapeHtml(row.name || '')}`, content);
}

async function setUserActive(row, active, container) {
  const isAr = getLang() === 'ar';
  try {
    await api.patch(`/fleet/users/${row.id}`, { is_active: active });
    loadSettings(container);
  } catch (err) {
    showToast((isAr ? '❌ تعذر تحديث الحالة: ' : '❌ Could not update: ') + err.message, 'error');
  }
}

async function deleteUser(row, container) {
  const isAr = getLang() === 'ar';
  const ok = confirm(isAr
    ? `حذف المستخدم «${row.name}»؟ لن يستطيع الدخول بعدها.`
    : `Delete "${row.name}"? They will no longer be able to sign in.`);
  if (!ok) return;
  try {
    await api.del(`/fleet/users/${row.id}`);
    loadSettings(container);
  } catch (err) {
    showToast((isAr ? '❌ تعذر الحذف: ' : '❌ Could not delete: ') + err.message, 'error');
  }
}

// ── Security ────────────────────────────────────────────────────────────────
function renderSecurity() {
  const isAr = getLang() === 'ar';
  const wrap = el('div', {});
  wrap.append(el('div', { class: 'card', style: 'max-width:460px' }, [
    el('h3', { style: 'margin:0 0 4px', text: isAr ? 'تغيير كلمة المرور' : 'Change password' }),
    el('p', { style: 'margin:0 0 14px;color:var(--muted);font-size:12px' },
      isAr
        ? 'بعد التغيير ستحتاج لتسجيل الدخول من جديد.'
        : 'You will need to sign in again after changing it.'),
    el('form', { onsubmit: async (e) => {
      e.preventDefault();
      const msg = document.getElementById('cp-msg');
      const next = document.getElementById('cp-new').value;
      if (next !== document.getElementById('cp-confirm').value) {
        msg.style.color = 'var(--red)';
        msg.textContent = isAr ? '❌ كلمتا المرور غير متطابقتين.' : '❌ The two passwords do not match.';
        return;
      }
      try {
        await api.post('/auth/change-password', {
          current_password: document.getElementById('cp-current').value,
          new_password: next,
        });
        msg.style.color = 'var(--green)';
        msg.textContent = isAr
          ? '✅ تم تغيير كلمة المرور. جاري تسجيل الخروج...'
          : '✅ Password changed. Signing you out...';
        setTimeout(() => { api.logout(); location.reload(); }, 1400);
      } catch (err) {
        msg.style.color = 'var(--red)';
        msg.textContent = '❌ ' + err.message;
      }
    }}, [
      formRow([inputField('cp-current', isAr ? 'كلمة المرور الحالية' : 'Current password',
        { type: 'password', required: true })]),
      formRow([inputField('cp-new', isAr ? 'كلمة المرور الجديدة (8 أحرف على الأقل)' : 'New password (at least 8 characters)',
        { type: 'password', required: true, minlength: 8 })]),
      formRow([inputField('cp-confirm', isAr ? 'تأكيد كلمة المرور الجديدة' : 'Confirm new password',
        { type: 'password', required: true, minlength: 8 })]),
      el('p', { id: 'cp-msg', style: 'margin:8px 0 0;font-size:12px' }),
      el('button', { class: 'btn btn-primary btn-blue btn-full', type: 'submit', style: 'margin-top:12px' },
        isAr ? 'تغيير كلمة المرور' : 'Change password'),
    ]),
  ]));
  return wrap;
}

// ── Subscription ────────────────────────────────────────────────────────────
async function renderSubscription() {
  const isAr = getLang() === 'ar';
  const wrap = el('div', {});
  const status = await api.get('/billing/status');

  const tone = status.status === 'ACTIVE' ? 'green' : status.status === 'SUSPENDED' ? 'red' : 'amber';
  const statusLabel = isAr
    ? { ACTIVE: 'نشط', SUSPENDED: 'موقوف', TRIAL: 'تجريبي', EXPIRED: 'منتهٍ' }
    : { ACTIVE: 'Active', SUSPENDED: 'Suspended', TRIAL: 'Trial', EXPIRED: 'Expired' };

  wrap.append(el('div', { class: 'card' }, [
    el('div', { style: 'display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px' }, [
      el('h3', { style: 'margin:0', text: isAr ? 'اشتراك الشركة' : 'Company subscription' }),
      badge(statusLabel[status.status] || status.status, tone),
    ]),
    el('div', { class: 'cards' }, [
      metricCard(status.plan || '—', isAr ? 'الباقة' : 'Plan'),
      metricCard(money(status.monthly_fee), isAr ? 'الرسوم الشهرية' : 'Monthly fee'),
      metricCard(status.due_date ? String(status.due_date).slice(0, 10) : '—', isAr ? 'تاريخ الاستحقاق' : 'Due date', 'amber'),
      metricCard(status.days_left ?? '—', isAr ? 'أيام متبقية' : 'Days left',
        Number(status.days_left) <= 7 ? 'red' : 'green'),
    ]),
    el('p', { style: 'margin:14px 0 0;color:var(--muted);font-size:12px' },
      isAr
        ? 'الباقة والرسوم تُدار من إدارة DOU. للتعديل أو الترقية تواصل مع الدعم.'
        : 'Your plan and fee are managed by DOU. Contact support to change or upgrade.'),
  ]));
  return wrap;
}

