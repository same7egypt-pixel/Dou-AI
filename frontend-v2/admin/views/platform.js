// Super Admin — platform views
import { api } from '../../shared/api/client.js';
import { el, loadingState, emptyState, errorState, metricCard, table } from '../../shared/components/ui.js';

export async function loadRevenue(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [el('div', {}, [el('div', { class: 'kicker' }, 'المالية'), el('h1', { text: 'التحصيل والإيرادات' })]), el('button', { class: 'btn btn-ghost', onclick: () => loadRevenue(container) }, '↻ تحديث')]));
  const body = el('div', {}, [loadingState('جاري التحميل...')]);
  container.append(body);
  try {
    const data = await api.get('/admin/finance/summary');
    body.innerHTML = '';
    body.append(el('div', { class: 'cards' }, [
      metricCard(`${data.collected || 0} ر.س`, 'المحصل', 'trend'),
      metricCard(`${data.expected || 0} ر.س`, 'المتوقع'),
      metricCard(data.overdue || 0, 'متأخرات', 'alert'),
    ]));
  } catch (e) { body.replaceWith(errorState('تعذر التحميل: ' + e.message)); }
}

export async function loadPlans(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [el('div', {}, [el('div', { class: 'kicker' }, 'الباقات'), el('h1', { text: 'الباقات والأسعار' })]), el('button', { class: 'btn btn-ghost', onclick: () => loadPlans(container) }, '↻ تحديث')]));
  container.append(el('div', {}, [emptyState('إدارة الباقات من إدارة DOU — تواصل مع الدعم للتعديلات.')]));
}

export async function loadUsage(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [el('div', {}, [el('div', { class: 'kicker' }, 'الاستخدام'), el('h1', { text: 'الاستخدام والحدود' })]), el('button', { class: 'btn btn-ghost', onclick: () => loadUsage(container) }, '↻ تحديث')]));
  const body = el('div', {}, [loadingState('جاري التحميل...')]);
  container.append(body);
  try {
    const data = await api.get('/admin/tenants');
    const rows = data.tenants || data || [];
    body.replaceWith(table([{ key: 'name', label: 'الشركة' }, { key: 'riders_count', label: 'السائقين' }, { key: 'status', label: 'الحالة' }], rows));
  } catch (e) { body.replaceWith(errorState('تعذر التحميل: ' + e.message)); }
}

export async function loadHealth(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [el('div', {}, [el('div', { class: 'kicker' }, 'صحة المنصة'), el('h1', { text: 'صحة المنصة' })]), el('button', { class: 'btn btn-ghost', onclick: () => loadHealth(container) }, '↻ تحديث')]));
  const body = el('div', {}, [loadingState('جاري الفحص...')]);
  container.append(body);
  try {
    const data = await api.get('/admin/system-status');
    body.innerHTML = '';
    body.append(el('div', { class: 'card' }, [el('h3', { text: 'حالة الخدمات' }), el('pre', { style: 'direction:ltr;text-align:left;background:var(--soft);padding:16px;border-radius:10px;font-size:12px;overflow:auto' }, JSON.stringify(data, null, 2))]));
  } catch (e) { body.replaceWith(errorState('تعذر التحميل: ' + e.message)); }
}

export async function loadIntegrations(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [el('div', {}, [el('div', { class: 'kicker' }, 'التكاملات'), el('h1', { text: 'التكاملات والويبهوكات' })]), el('button', { class: 'btn btn-ghost', onclick: () => loadIntegrations(container) }, '↻ تحديث')]));
  container.append(el('div', {}, [emptyState('إدارة التكاملات من إعدادات النظام — تواصل مع الدعم للتعديلات.')]));
}

export async function loadAudit(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [el('div', {}, [el('div', { class: 'kicker' }, 'السجل'), el('h1', { text: 'سجل إدارة DOU' })]), el('button', { class: 'btn btn-ghost', onclick: () => loadAudit(container) }, '↻ تحديث')]));
  const body = el('div', {}, [loadingState('جاري التحميل...')]);
  container.append(body);
  try {
    const data = await api.get('/admin/audit-log?limit=50');
    const rows = data.logs || data || [];
    if (!rows.length) { body.replaceWith(emptyState('لا توجد سجلات بعد.')); return; }
    body.replaceWith(table([{ key: 'action', label: 'العملية' }, { key: 'actor_name', label: 'المسؤول' }, { key: 'created_at', label: 'التاريخ' }], rows));
  } catch (e) { body.replaceWith(errorState('تعذر التحميل: ' + e.message)); }
}

export async function loadSettings(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [el('div', {}, [el('div', { class: 'kicker' }, 'الإعدادات'), el('h1', { text: 'إعدادات النظام' })]), el('button', { class: 'btn btn-ghost', onclick: () => loadSettings(container) }, '↻ تحديث')]));
  container.append(el('div', {}, [emptyState('إعدادات النظام تُدار من قبل فريق DOU — تواصل مع الدعم للتعديلات.')]));
}
