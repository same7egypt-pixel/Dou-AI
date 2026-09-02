// Vendors — the delivery-platform screen.
//
// A platform works through logistics vendors who sponsor the riders. Its two
// expensive questions are which vendor supplies riders who actually show up,
// and which vendor is about to put a rider with lapsed papers on the road.
// Two tabs, one for each.
//
// The API refuses both endpoints to an account without MANAGE_OPERATORS, so
// this screen never has to guess at permission.
import { api } from '../../shared/api/client.js';
import { el, loadingState, emptyState, errorState, metricCard, badge, table } from '../../shared/components/ui.js';
import { getLang } from '../../shared/i18n/i18n.js';
import { go } from '../shell.js';

let activeTab = 'scorecard';
let horizonDays = 30;

export async function renderVendors(container) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';

  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'شبكة المورّدين' : 'Vendor Network'),
      el('h1', { text: isAr ? 'المورّدون والالتزام' : 'Vendors & Compliance' })
    ]),
    el('div', { class: 'header-actions' }, [
      el('button', { class: 'btn btn-ghost', onclick: () => renderVendors(container) },
        isAr ? '↻ تحديث' : '↻ Refresh')
    ])
  ]));

  const tabs = el('div', { class: 'tabs', style: 'margin-bottom:18px' }, [
    el('button', {
      class: `tab ${activeTab === 'scorecard' ? 'active' : ''}`,
      'data-tab': 'scorecard',
      onclick: () => { activeTab = 'scorecard'; renderVendors(container); }
    }, isAr ? '🏆 بطاقات أداء المورّدين' : '🏆 Vendor Scorecards'),
    el('button', {
      class: `tab ${activeTab === 'compliance' ? 'active' : ''}`,
      'data-tab': 'compliance',
      onclick: () => { activeTab = 'compliance'; renderVendors(container); }
    }, isAr ? '🛡️ جدار الالتزام' : '🛡️ Compliance Wall'),
  ]);
  container.append(tabs);

  const pane = el('div', { id: 'vendors-pane' }, [loadingState(isAr ? 'جاري التحميل...' : 'Loading...')]);
  container.append(pane);

  try {
    if (activeTab === 'scorecard') await renderScorecard(pane, isAr);
    else await renderCompliance(pane, isAr);
  } catch (e) {
    pane.innerHTML = '';
    pane.append(errorState((isAr ? 'تعذر تحميل بيانات المورّدين: ' : 'Could not load vendors: ') + e.message));
  }
}

function rateBadge(value, { good = 90, warn = 70 } = {}) {
  if (value === null || value === undefined) return el('span', { class: 'badge badge-gray' }, '—');
  const tone = value >= good ? 'green' : (value >= warn ? 'amber' : 'alert');
  return el('span', { class: `badge badge-${tone}` }, `${value}%`);
}

async function renderScorecard(pane, isAr) {
  const data = await api.get('/analytics/reports/vendors/scorecard');
  const rows = data.rows || [];
  pane.innerHTML = '';

  const t = data.totals || {};
  pane.append(el('div', { class: 'cards' }, [
    metricCard(data.vendors || 0, isAr ? 'المورّدون' : 'Vendors', 'blue', null,
      isAr ? 'المرتبطون بالمنصة' : 'Linked to this platform'),
    metricCard(t.riders || 0, isAr ? 'إجمالي المناديب' : 'Total Riders', 'blue', null,
      isAr ? 'عبر كل المورّدين' : 'Across all vendors'),
    metricCard(t.present_today || 0, isAr ? 'حاضرون اليوم' : 'Present Today', 'trend', null,
      isAr ? 'سجّلوا حضورًا' : 'Checked in'),
    metricCard(t.riders_expired || 0, isAr ? 'مناديب بوثائق منتهية' : 'Riders with Expired Docs',
      (t.riders_expired || 0) > 0 ? 'alert' : 'trend', null,
      isAr ? 'ممنوعون من العمل نظاميًا' : 'Legally blocked from working'),
  ]));

  if (!rows.length) {
    pane.append(emptyState(isAr
      ? 'لا يوجد مورّدون مرتبطون بعد. أضفهم من شاشة المشغّلين لتظهر بطاقات أدائهم.'
      : 'No vendors linked yet.'));
    return;
  }

  pane.append(table([
    { key: 'rank', label: '#', render: (v) => el('b', { style: 'color:var(--muted)' }, String(v)) },
    { key: 'operator_name', label: isAr ? 'المورّد' : 'Vendor', render: (v, r) => el('div', {}, [
      el('b', { style: 'display:block;color:var(--text)' }, v || '—'),
      el('small', { style: 'color:var(--muted);font-size:11px' },
        r.is_linked ? (isAr ? 'مرتبط' : 'Linked') : (isAr ? '⚠️ غير مُسند لمورّد' : '⚠️ Unassigned'))
    ]) },
    { key: 'riders', label: isAr ? 'المناديب' : 'Riders', render: (v, r) => el('div', {}, [
      el('b', {}, String(v)),
      el('small', { style: 'display:block;color:var(--muted);font-size:11px' },
        `${r.active_riders} ${isAr ? 'نشط' : 'active'}`)
    ]) },
    { key: 'attendance_rate', label: isAr ? 'الحضور' : 'Attendance', render: (v) => rateBadge(v, { good: 85, warn: 60 }) },
    { key: 'compliance_rate', label: isAr ? 'الالتزام' : 'Compliance', render: (v) => rateBadge(v, { good: 100, warn: 80 }) },
    { key: 'orders_month', label: isAr ? 'طلبات الشهر' : 'Orders', render: (v) => el('b', {}, String(v || 0)) },
    { key: 'target_achievement', label: isAr ? 'إنجاز التارجت' : 'Target', render: (v) => rateBadge(v, { good: 100, warn: 75 }) },
    { key: 'riders_expired', label: isAr ? 'وثائق منتهية' : 'Expired', render: (v, r) => {
      if (!v && !r.riders_expiring) return el('span', { class: 'badge badge-green' }, isAr ? 'سليم' : 'Clear');
      return el('div', { style: 'display:flex;gap:4px;flex-wrap:wrap' }, [
        v ? el('span', { class: 'badge badge-alert' }, `${v} ${isAr ? 'منتهٍ' : 'expired'}`) : null,
        r.riders_expiring ? el('span', { class: 'badge badge-amber' }, `${r.riders_expiring} ${isAr ? 'يوشك' : 'soon'}`) : null,
      ].filter(Boolean));
    } },
  ], rows));
}

async function renderCompliance(pane, isAr) {
  const data = await api.get(`/analytics/reports/vendors/compliance?horizon_days=${horizonDays}`);
  const rows = data.rows || [];
  pane.innerHTML = '';

  const t = data.totals || {};
  pane.append(el('div', { class: 'cards' }, [
    metricCard(t.expired || 0, isAr ? 'وثائق منتهية' : 'Expired', (t.expired || 0) > 0 ? 'alert' : 'trend', null,
      isAr ? 'المندوب ممنوع من العمل' : 'Rider cannot legally work'),
    metricCard(t.expiring || 0, isAr ? `تنتهي خلال ${horizonDays} يومًا` : `Expiring in ${horizonDays}d`, 'amber', null,
      isAr ? 'تحتاج تجديدًا الآن' : 'Renew now'),
    metricCard(t.riders_affected || 0, isAr ? 'مناديب متأثرون' : 'Riders Affected', 'blue', null, ''),
    metricCard(t.vendors_affected || 0, isAr ? 'مورّدون مطالَبون' : 'Vendors to Chase', 'blue', null,
      isAr ? 'المسؤولية عليهم' : 'They hold the paperwork'),
  ]));

  const picker = el('div', { class: 'filters', style: 'margin:14px 0' }, [
    el('span', { style: 'font-size:12.5px;color:var(--muted);font-weight:600' },
      isAr ? 'مدى الإنذار:' : 'Alert horizon:'),
    ...[7, 30, 60, 90].map((d) => el('button', {
      class: `btn btn-small ${horizonDays === d ? 'btn-primary' : 'btn-ghost'}`,
      onclick: () => { horizonDays = d; renderVendors(document.getElementById('content-area')); }
    }, isAr ? `${d} يومًا` : `${d} days`))
  ]);
  pane.append(picker);

  if (!rows.length) {
    pane.append(emptyState(isAr
      ? `لا توجد وثائق منتهية أو توشك خلال ${horizonDays} يومًا. الشبكة ملتزمة.`
      : `Nothing expired or expiring within ${horizonDays} days.`));
    return;
  }

  pane.append(table([
    { key: 'severity', label: isAr ? 'الحالة' : 'Status', render: (v, r) => v === 'EXPIRED'
      ? el('span', { class: 'badge badge-alert' }, isAr ? `منتهٍ منذ ${Math.abs(r.days_remaining)} يومًا` : `Expired ${Math.abs(r.days_remaining)}d ago`)
      : el('span', { class: 'badge badge-amber' }, isAr ? `خلال ${r.days_remaining} يومًا` : `In ${r.days_remaining}d`) },
    { key: 'document', label: isAr ? 'الوثيقة' : 'Document', render: (v) => el('b', {}, v) },
    { key: 'rider_name', label: isAr ? 'المندوب' : 'Rider', render: (v, r) => el('div', {}, [
      el('b', { style: 'display:block;color:var(--text)' }, v || '—'),
      el('small', { style: 'color:var(--muted);font-size:11px' }, r.rider_phone || '')
    ]) },
    { key: 'operator_name', label: isAr ? 'المورّد المسؤول' : 'Responsible Vendor', render: (v) => badge(v || '—', 'blue') },
    { key: 'expiry_date', label: isAr ? 'تاريخ الانتهاء' : 'Expiry', render: (v) => el('span', { style: 'font-variant-numeric:tabular-nums' }, v || '—') },
    { key: 'rider_id', label: isAr ? 'إجراء' : 'Action', render: (v) => el('button', {
      class: 'btn btn-ghost btn-small',
      onclick: () => { window.__rider360InitialId = v; window.__rider360InitialTab = 'documents'; go('rider360'); }
    }, isAr ? 'فتح الملف ➔' : 'Open profile ➔') },
  ], rows));
}
