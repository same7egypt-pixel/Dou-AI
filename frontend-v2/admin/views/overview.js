// Super Admin — Overview
import { api } from '../../shared/api/client.js';
import { el, loadingState, errorState, metricCard } from '../../shared/components/ui.js';

export async function loadOverview(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [el('div', {}, [el('div', { class: 'kicker' }, 'لوحة قيادة المنصة'), el('h1', { text: 'لوحة القيادة' })]), el('button', { class: 'btn-ghost', onclick: () => loadOverview(container) }, '↻ تحديث')]));
  const body = el('div', {}, [loadingState('جاري التحميل...')]);
  container.append(body);
  try {
    const data = await api.get('/admin/dashboard');
    body.innerHTML = '';
    body.append(el('div', { class: 'cards' }, [
      metricCard(data.total_tenants || 0, 'إجمالي الشركات'),
      metricCard(data.active_tenants || 0, 'شركات نشطة', 'trend'),
      metricCard(data.total_riders || 0, 'إجمالي السائقين'),
      metricCard(`${data.monthly_revenue || 0} ر.س`, 'الإيرادات الشهرية'),
    ]));
  } catch (e) { body.replaceWith(errorState('تعذر التحميل: ' + e.message)); }
}
