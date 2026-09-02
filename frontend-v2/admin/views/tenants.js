// Super Admin — Tenants
import { api } from '../../shared/api/client.js';
import { el, loadingState, emptyState, errorState, table, button, escapeHtml, modal, badge } from '../../shared/components/ui.js';

export async function loadTenants(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, 'إدارة الشركات'),
      el('h1', { text: 'الشركات المشتركة' })
    ]),
    el('button', { class: 'btn btn-ghost', onclick: () => loadTenants(container) }, '↻ تحديث')
  ]));
  const body = el('div', {}, [loadingState('جاري تحميل الشركات...')]);
  container.append(body);
  try {
    const data = await api.get('/admin/tenants');
    const rows = data.tenants || data || [];
    if (!rows.length) { body.replaceWith(emptyState('لا توجد شركات بعد.')); return; }

    function showTenantDetails(tenant) {
      const content = el('div', { style: 'display:grid;gap:12px;direction:rtl' }, [
        el('div', { style: 'display:flex;justify-content:space-between;align-items:center' }, [
          el('h3', { text: tenant.name || 'تفاصيل الشركة' }),
          badge(tenant.subscription_status || tenant.status || 'ACTIVE', (tenant.subscription_status === 'ACTIVE' || tenant.status === 'ACTIVE') ? 'green' : 'amber'),
        ]),
        el('div', { class: 'card', style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:12px;font-size:13px' }, [
          el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'البلد: '), el('b', { text: tenant.country || '—' })]),
          el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'العملة: '), el('b', { text: tenant.currency || 'SAR' })]),
          el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'الباقة: '), el('b', { text: tenant.plan || 'TRIAL' })]),
          el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'الرسوم الشهرية: '), el('b', { text: `${tenant.monthly_fee || 0} ${tenant.currency || 'SAR'}` })]),
          el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'عدد المناديب: '), el('b', { text: String(tenant.couriers_count || 0) })]),
          el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'تاريخ الاستحقاق: '), el('b', { text: tenant.due_date ? new Date(tenant.due_date).toLocaleDateString('ar-SA') : '—' })]),
        ]),
      ]);
      modal(`تفاصيل شركة ${tenant.name}`, content);
    }

    body.replaceWith(table([
      { key: 'name', label: 'الشركة' },
      { key: 'country', label: 'البلد' },
      { key: 'currency', label: 'العملة' },
      { key: 'status', label: 'الحالة', render: (v, row) => badge(row.subscription_status || v || 'ACTIVE', (row.subscription_status === 'ACTIVE' || v === 'ACTIVE') ? 'green' : 'amber') },
      { key: 'actions', label: 'إجراء', render: (_, row) => el('button', { class: 'btn btn-ghost btn-small', onclick: () => showTenantDetails(row) }, 'تفاصيل') },
    ], rows));
  } catch (e) { body.replaceWith(errorState('تعذر التحميل: ' + e.message)); }
}
