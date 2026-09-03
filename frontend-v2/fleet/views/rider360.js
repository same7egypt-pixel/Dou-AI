// Rider 360 — unified 8-tab profile workspace
import { api } from '../../shared/api/client.js';
import { appStore } from '../../shared/state/store.js';
import { el, loadingState, emptyState, errorState, metricCard, badge, table, button, escapeHtml, modal, formRow, inputField, selectField, searchableSelect } from '../../shared/components/ui.js';
import { go } from '../shell.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

let currentRiderId = null;

function getCurrentRole() {
  return appStore.get().role || appStore.get().user?.role || localStorage.getItem('dou_role_v2');
}

export async function loadRider360(container, riderId = null) {
  const isAr = getLang() === 'ar';
  const initialId = riderId || window.__rider360InitialId || currentRiderId;
  window.__rider360InitialId = null;
  if (initialId) currentRiderId = initialId;

  const initialTab = window.__rider360InitialTab || 'profile';
  window.__rider360InitialTab = null;

  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'الملف التشغيلي الموحد' : 'Unified Operational Workspace'),
      el('h1', { text: isAr ? '◎ ملف السائق 360' : '◎ Driver 360 Profile' })
    ]),
    el('button', { class: 'btn btn-ghost', onclick: () => go('riders') }, isAr ? 'العودة للسائقين' : '← Back to Drivers'),
  ]));

  const riderSelectorCard = el('div', { class: 'card', style: 'padding:14px 18px;margin-bottom:16px;background:var(--card);border:1px solid var(--border);border-radius:12px' });
  const riderSelect = searchableSelect({
    id: 'r360-select',
    placeholder: isAr ? '🔍 ابحث بالاسم، رقم الجوال، أو رقم السائق...' : '🔍 Search by name, mobile, or ID...',
    options: [],
    value: currentRiderId ? String(currentRiderId) : '',
    onChange: (val) => {
      if (val && Number(val) !== currentRiderId) {
        loadRider360(container, Number(val));
      }
    }
  });

  riderSelectorCard.append(
    el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:6px' }, [
      el('label', { style: 'font-weight:700;font-size:12px;color:var(--muted)' }, isAr ? '👤 اختر السائق لاستعراض ملفه الشامل:' : '👤 Select driver to view comprehensive profile:'),
      el('span', { style: 'font-size:11px;color:var(--muted)' }, isAr ? '⚡ اكتب للبحث الفوري عن أي سائق' : '⚡ Type for instant search')
    ]),
    riderSelect
  );
  container.append(riderSelectorCard);

  const content = el('div', {}, [loadingState(isAr ? 'جاري تحميل السائقين...' : 'Loading drivers...')]);
  container.append(content);

  try {
    const data = await api.get('/fleet/couriers/page?page=1&page_size=100');
    const riders = data.rows || [];
    const options = riders.map((r) => ({
      value: String(r.id),
      label: `${r.name || 'سائق بدون اسم'} (#${r.id})`,
      sublabel: `📱 ${r.phone || '—'} | ${r.contract_name || r.primary_project_name || 'عقد عام'} | المشرف: ${r.supervisor_name || '—'}`,
      badge: r.employment_status === 'ACTIVE' || r.is_active ? 'نشط' : 'غير نشط',
      badgeColor: r.employment_status === 'ACTIVE' || r.is_active ? 'green' : 'gray'
    }));
    riderSelect.setOptions(options);

    if (currentRiderId) {
      riderSelect.setValue(String(currentRiderId));
      renderTabs(container, content, initialTab);
    } else if (riders.length) {
      currentRiderId = riders[0].id;
      riderSelect.setValue(String(currentRiderId));
      renderTabs(container, content, initialTab);
    } else {
      content.replaceWith(emptyState('لا يوجد سائقون ضمن نطاقك.'));
    }
  } catch (e) {
    content.replaceWith(errorState('تعذر تحميل السائقين: ' + e.message));
  }
}

// Module scope on purpose. This list used to be declared inside the render
// function while renderTabs read it from here, so every visit to Driver 360
// threw "TABS is not defined". The throw happened inside a try block, so the
// screen reported "تعذر تحميل السائقين" and the real cause never surfaced.
function riderTabs() {
  const isAr = getLang() === 'ar';
  return [
    { id: 'profile', label: isAr ? 'الملف الشخصي' : 'Profile' },
    { id: 'documents', label: isAr ? 'المستندات' : 'Documents' },
    { id: 'shifts', label: isAr ? 'الورديات' : 'Shifts' },
    { id: 'attendance', label: isAr ? 'الحضور' : 'Attendance' },
    { id: 'performance', label: isAr ? 'الأداء' : 'Performance' },
    { id: 'targets', label: isAr ? 'الأهداف' : 'Targets' },
    { id: 'payroll', label: isAr ? 'الراتب' : 'Payroll' },
    { id: 'leave', label: isAr ? 'الإجازات' : 'Leaves' },
  ];
}

function renderTabs(container, content, startTab = 'profile') {
  const tabs = el('div', { class: 'tabs' }, riderTabs().map((t) => el('button', { class: `tab ${t.id === startTab ? 'active' : ''}`, 'data-tab': t.id, onclick: () => switchTab(t.id) }, t.label)));
  const pane = el('div', { class: 'tab-pane' }, [loadingState('جاري تحميل البيانات...')]);
  content.replaceWith(el('div', {}, [tabs, pane]));
  switchTab(startTab);
}

function switchTab(tabId) {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === tabId));
  const pane = document.querySelector('.tab-pane');
  if (!pane) return;
  pane.innerHTML = '';
  pane.append(loadingState('جاري التحميل...'));
  loadTabContent(tabId, pane);
}

async function loadTabContent(tabId, pane) {
  if (!currentRiderId) return;
  try {
    let content;
    switch (tabId) {
      case 'profile': content = await renderProfile(); break;
      case 'documents': content = await renderDocuments(); break;
      case 'shifts': content = await renderShifts(); break;
      case 'attendance': content = await renderAttendance(); break;
      case 'performance': content = await renderPerformance(); break;
      case 'targets': content = await renderTargets(); break;
      case 'payroll': content = await renderPayroll(); break;
      case 'leave': content = await renderLeave(); break;
    }
    if (content) {
      pane.innerHTML = '';
      pane.append(content);
    }
  } catch (e) {
    pane.innerHTML = '';
    pane.append(errorState('تعذر التحميل: ' + e.message));
  }
}

async function renderProfile() {
  const id = currentRiderId;
  const [profile, readiness, vehicle] = await Promise.all([
    api.get(`/analytics/riders/${id}/profile`),
    api.get(`/readiness/${id}`),
    api.get(`/vehicles/riders/${id}/readiness?as_of=${new Date().toISOString().slice(0,10)}`).catch(() => null),
  ]);
  const wrap = el('div', {});
  wrap.append(el('div', { class: 'cards' }, [
    metricCard(profile.month_attendance_days || 0, 'أيام الحضور الشهر'),
    metricCard(profile.month_orders || 0, 'الأداء المسجل'),
    metricCard(profile.target_achievement != null ? `${profile.target_achievement}%` : '—', 'تحقيق الهدف'),
    metricCard(`${profile.documents_valid || 0}/${profile.documents_total || 0}`, 'المستندات'),
  ]));
  const dimensions = readiness?.dimensions || {};
  const blockers = readiness?.blockers || [];
  const canManage = ['COMPANY', 'COMPANY_ADMIN', 'OPERATIONS', 'HR'].includes(getCurrentRole());
  wrap.append(el('div', { class: 'card' }, [
    el('h3', { text: 'بيانات السائق' }),
    el('div', { class: 'profile-grid' }, [
      fieldPair('الاسم', profile.name),
      fieldPair('الجوال', profile.phone),
      fieldPair('الحالة', profile.employment_status),
      fieldPair('مرحلة الانضمام', readiness?.onboarding_status || 'NEW'),
      fieldPair('الجاهزية', readiness?.overall_status || '—'),
      fieldPair('المركبة', vehicle?.details?.assignment ? `${vehicle.details.assignment.vehicle_type} — ${vehicle.details.assignment.plate_number}` : 'غير مسندة'),
      fieldPair('المشروع', profile.project_id || '—'),
      fieldPair('الفرع', profile.branch_id || '—'),
      fieldPair('المشرف', profile.supervisor_id || '—'),
    ]),
    canManage ? el('div', { style: 'margin-top:14px;display:flex;gap:8px;flex-wrap:wrap' }, [
      el('button', { class: 'btn btn-blue btn-small', onclick: () => assignVehicle() }, 'إسناد / تغيير مركبة'),
      ['NEW', 'INCOMPLETE'].includes(readiness?.onboarding_status) ? el('button', { class: 'btn btn-ghost btn-small', onclick: () => transitionReadiness('SUBMIT_FOR_REVIEW') }, 'إرسال للمراجعة') : null,
      readiness?.onboarding_status === 'READY_FOR_REVIEW' ? el('button', { class: 'btn btn-green btn-small', onclick: () => transitionReadiness('ACTIVATE') }, 'تفعيل للعمل') : null,
      readiness?.onboarding_status === 'READY_FOR_REVIEW' ? el('button', { class: 'btn btn-red btn-small', onclick: () => transitionReadiness('REJECT') }, 'إعادة للاستكمال') : null,
    ]) : null,
  ]));
  wrap.append(el('div', { class: 'card' }, [
    el('h3', { text: 'أبعاد الجاهزية' }),
    ...Object.entries(dimensions).map(([k, v]) => fieldPair(k, v || '—')),
    blockers.length ? el('p', { style: 'color:var(--red);margin-top:12px' }, `المعوقات: ${blockers.join('، ')}`) : el('p', { style: 'color:var(--green);margin-top:12px' }, '✅ لا توجد معوقات'),
  ]));
  return wrap;
}

function fieldPair(label, value) {
  return el('div', { class: 'field-pair' }, [el('span', { text: label }), el('b', { text: String(value ?? '—') })]);
}

const DOCUMENT_TYPE_LABELS = {
  IQAMA: { ar: 'الإقامة / الهوية الوطنية', en: 'Iqama / national ID' },
  DRIVING_LICENSE: { ar: 'رخصة القيادة', en: 'Driving licence' },
  VEHICLE_LICENSE: { ar: 'استمارة المركبة', en: 'Vehicle registration' },
  INSURANCE: { ar: 'وثيقة التأمين', en: 'Insurance document' },
  WORK_PERMIT: { ar: 'تصريح العمل', en: 'Work permit' },
  PASSPORT: { ar: 'جواز السفر', en: 'Passport' },
};

// This tab used to read /documents/RIDER/{id} — a metadata-only store that
// holds no files and that nothing writes to. Riders upload from the phone app
// into CourierDocumentSubmission, so their documents were invisible here and
// nobody could review them: the rider stayed blocked on documents:MISSING
// forever. This reads the store that actually holds the file, and lets the
// company file a document on the rider's behalf.
async function renderDocuments() {
  const id = currentRiderId;
  const isAr = getLang() === 'ar';
  const canManage = ['COMPANY', 'COMPANY_ADMIN', 'OPERATIONS', 'HR'].includes(getCurrentRole());
  const wrap = el('div', {});

  let docs = [];
  try {
    docs = await api.get(`/hr/couriers/${id}/documents`);
  } catch (err) {
    return errorState(
      (isAr ? 'تعذر تحميل مستندات السائق: ' : 'Could not load the rider documents: ') + err.message,
      () => switchTab('documents')
    );
  }

  if (canManage) {
    wrap.append(el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px' }, [
      el('select', { id: 'doc-upload-type', style: 'padding:8px 12px;border:1px solid var(--border);border-radius:8px' },
        Object.entries(DOCUMENT_TYPE_LABELS).map(([value, label]) =>
          el('option', { value }, isAr ? label.ar : label.en))),
      el('button', { class: 'btn btn-blue', id: 'btn-upload-doc', onclick: () => uploadRiderDocument(id) },
        isAr ? '📎 رفع مستند للسائق' : '📎 Upload a document'),
      el('span', { style: 'font-size:11px;color:var(--muted)' },
        isAr ? 'صورة أو PDF حتى 1 ميجابايت' : 'Image or PDF, up to 1 MB'),
    ]));
  }

  if (!docs?.length) {
    wrap.append(emptyState(isAr
      ? 'لا توجد مستندات لهذا السائق — ارفعها هنا أو اطلب من السائق رفعها من التطبيق.'
      : 'No documents for this rider — upload one here, or ask the rider to upload from the app.'));
    return wrap;
  }

  const statusTone = { APPROVED: 'green', PENDING: 'amber', REJECTED: 'red' };
  const statusLabel = isAr
    ? { APPROVED: 'معتمد', PENDING: 'قيد المراجعة', REJECTED: 'مرفوض' }
    : { APPROVED: 'Approved', PENDING: 'Pending', REJECTED: 'Rejected' };

  wrap.append(table([
    {
      key: 'document_type',
      label: isAr ? 'نوع المستند' : 'Document type',
      render: (v) => (DOCUMENT_TYPE_LABELS[v] ? (isAr ? DOCUMENT_TYPE_LABELS[v].ar : DOCUMENT_TYPE_LABELS[v].en) : v),
    },
    { key: 'filename', label: isAr ? 'الملف' : 'File' },
    {
      key: 'status',
      label: isAr ? 'الحالة' : 'Status',
      render: (v) => badge(statusLabel[v] || v, statusTone[v] || 'gray'),
    },
    {
      key: 'created_at',
      label: isAr ? 'تاريخ الرفع' : 'Uploaded',
      render: (v) => (v ? String(v).slice(0, 10) : '—'),
    },
    {
      key: 'actions',
      label: isAr ? 'إجراء' : 'Action',
      render: (_, row) => el('div', { class: 'inline-actions' }, [
        el('button', { class: 'btn btn-ghost btn-small', onclick: () => viewRiderDocument(row.id) },
          isAr ? 'عرض' : 'View'),
        row.status === 'PENDING' && canManage
          ? el('button', { class: 'btn btn-green btn-small', onclick: () => decideRiderDocument(row.id, 'approve') },
              isAr ? 'اعتماد' : 'Approve')
          : null,
        row.status === 'PENDING' && canManage
          ? el('button', { class: 'btn btn-red btn-small', onclick: () => decideRiderDocument(row.id, 'reject') },
              isAr ? 'رفض' : 'Reject')
          : null,
      ].filter(Boolean)),
    },
  ], docs));
  return wrap;
}

async function viewRiderDocument(documentId) {
  const isAr = getLang() === 'ar';
  try {
    const doc = await api.get(`/hr/documents/${documentId}/content`);
    const win = window.open('', '_blank');
    if (!win) { alert(isAr ? 'اسمح بالنوافذ المنبثقة لعرض المستند' : 'Allow pop-ups to view the document'); return; }
    if (doc.mime_type === 'application/pdf') {
      win.location.href = doc.file_data;
    } else {
      win.document.write(
        `<title>${escapeHtml(doc.filename || '')}</title>` +
        `<img src="${doc.file_data}" style="max-width:100%;height:auto;display:block;margin:auto">`
      );
    }
  } catch (err) {
    alert((isAr ? '❌ تعذر عرض المستند: ' : '❌ Could not open the document: ') + err.message);
  }
}

async function decideRiderDocument(documentId, action) {
  const isAr = getLang() === 'ar';
  const note = prompt(isAr ? 'ملاحظة المراجعة (اختياري):' : 'Review note (optional):', '') || '';
  try {
    await api.post(`/hr/documents/${documentId}/decide`, { action, note });
    switchTab('documents');
  } catch (err) {
    alert((isAr ? '❌ تعذر حفظ القرار: ' : '❌ Could not save the decision: ') + err.message);
  }
}

function uploadRiderDocument(riderId) {
  const isAr = getLang() === 'ar';
  const documentType = document.getElementById('doc-upload-type')?.value || 'IQAMA';
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/jpeg,image/png,application/pdf';
  input.onchange = async () => {
    const file = input.files?.[0];
    if (!file) return;
    // The endpoint caps the encoded payload at 1 MB; check before encoding so
    // the operator gets told the size, not a rejection after a slow upload.
    if (file.size > 1_000_000) {
      alert(isAr ? '❌ الملف أكبر من 1 ميجابايت. اضغطه ثم أعد المحاولة.'
                 : '❌ The file is larger than 1 MB. Compress it and try again.');
      return;
    }
    const button = document.getElementById('btn-upload-doc');
    if (button) { button.disabled = true; button.textContent = isAr ? '⏳ جاري الرفع…' : '⏳ Uploading…'; }
    try {
      const fileData = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error(isAr ? 'تعذر قراءة الملف' : 'Could not read the file'));
        reader.readAsDataURL(file);
      });
      await api.post(`/hr/couriers/${riderId}/documents`, {
        document_type: documentType,
        filename: file.name,
        mime_type: file.type || 'application/octet-stream',
        file_data: fileData,
      });
      switchTab('documents');
    } catch (err) {
      alert((isAr ? '❌ تعذر رفع المستند: ' : '❌ Could not upload the document: ') + err.message);
      if (button) { button.disabled = false; button.textContent = isAr ? '📎 رفع مستند للسائق' : '📎 Upload a document'; }
    }
  };
  input.click();
}

async function renderShifts() {
  const id = currentRiderId;
  const shifts = await api.get(`/shifts/riders/${id}/shifts`);
  const wrap = el('div', {});
  const canManage = ['COMPANY', 'COMPANY_ADMIN', 'OPERATIONS', 'HR'].includes(getCurrentRole());
  if (canManage) wrap.append(el('button', { class: 'btn btn-blue', style: 'margin-bottom:12px', onclick: () => assignShift() }, 'إسناد وردية'));
  if (!shifts?.length) { wrap.append(emptyState('لا ورديات مسندة.')); return wrap; }
  wrap.append(table([
    { key: 'name', label: 'الوردية' },
    { key: 'start_time', label: 'من' },
    { key: 'end_time', label: 'إلى' },
    { key: 'status', label: 'الحالة', render: (v) => badge(v, v === 'ACTIVE' ? 'green' : 'gray') },
    { key: 'actions', label: 'إجراء', render: (_, row) => canManage ? el('button', { class: 'btn btn-red btn-small', onclick: () => window.removeShift(row.id) }, 'إزالة') : '—' },
  ], shifts));
  return wrap;
}

async function renderAttendance() {
  const id = currentRiderId;
  const rows = await api.get(`/fleet/attendance?courier_id=${id}`);
  const wrap = el('div', {});
  if (!rows?.length) { wrap.append(emptyState('لا سجلات حضور اليوم.')); return wrap; }
  wrap.append(table([
    { key: 'date', label: 'التاريخ', render: (v, r) => r.check_in ? String(r.check_in).slice(0, 10) : '—' },
    { key: 'shift', label: 'الوردية' },
    { key: 'check_in', label: 'الدخول', render: (v) => v ? new Date(v).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }) : '—' },
    { key: 'check_out', label: 'الخروج', render: (v) => v ? new Date(v).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }) : '—' },
    { key: 'status', label: 'الحالة', render: (v) => badge(v, v === 'PRESENT' ? 'green' : v === 'LATE' ? 'amber' : 'red') },
    { key: 'actions', label: 'تصحيح', render: (_, r) => el('button', { class: 'btn btn-ghost btn-small', onclick: () => window.correctAtt(r.id) }, 'تصحيح') },
  ], rows));
  return wrap;
}

async function renderPerformance() {
  const id = currentRiderId;
  const data = await api.get(`/analytics/performance/scorecard/RIDER/${id}`);
  const wrap = el('div', {});
  wrap.append(el('div', { class: 'card' }, [
    el('h3', { text: `الأداء — ${data.period || 'الفترة الحالية'}` }),
    el('p', { style: 'color:var(--muted)' }, `KPIs: ${data.kpis?.length || 0} · أهداف: ${data.targets?.length || 0}`),
    data.kpis?.length ? table([
      { key: 'name', label: 'المؤشر' },
      { key: 'value', label: 'القيمة' },
      { key: 'target', label: 'المستهدف' },
    ], data.kpis) : null,
  ]));
  return wrap;
}

async function renderTargets() {
  const id = currentRiderId;
  const targets = await api.get(`/analytics/targets?scope_type=RIDER&scope_id=${id}`);
  const wrap = el('div', {});
  const canManage = ['COMPANY', 'COMPANY_ADMIN', 'OPERATIONS', 'HR'].includes(getCurrentRole());
  if (canManage) wrap.append(el('button', { class: 'btn btn-blue', style: 'margin-bottom:12px', onclick: () => setTarget() }, 'تحديد / تعديل هدف'));
  if (!targets?.length) { wrap.append(emptyState('لا أهداف محددة.')); return wrap; }
  wrap.append(table([
    { key: 'target_type', label: 'الهدف' },
    { key: 'period', label: 'الفترة' },
    { key: 'target_value', label: 'القيمة' },
    { key: 'actual_value', label: 'الفعلي' },
    { key: 'achievement_percentage', label: 'الإنجاز', render: (v) => badge(`${v || 0}%`, v >= 100 ? 'green' : v >= 80 ? 'blue' : 'red') },
  ], targets));
  return wrap;
}

// This tab used to read /analytics/payroll/breakdown, a parallel ledger built on
// PayrollInputRecord that the payroll engine never writes. The result was a
// rider showing 0 SAR here while the payroll sheet showed 216 for the same
// rider and month. Payroll has exactly one calculation path (see CLAUDE.md);
// the rider statement is that path, scoped to one rider.
async function renderPayroll() {
  const id = currentRiderId;
  const month = new Date().toISOString().slice(0, 7);
  const isAr = getLang() === 'ar';
  const money = (v) => `${Number(v || 0).toFixed(2)} ${isAr ? 'ر.س' : 'SAR'}`;

  let data;
  try {
    data = await api.get(`/hr/payroll/rider/${id}/statement?month=${month}`);
  } catch (err) {
    return errorState(
      (isAr ? 'تعذر تحميل كشف حساب المندوب: ' : 'Could not load the rider statement: ') + err.message,
      () => switchTab('payroll')
    );
  }

  const s = data.statement || {};
  const period = data.period || {};
  const wrap = el('div', {});

  wrap.append(el('div', { class: 'cards' }, [
    metricCard(money(s.base_salary), isAr ? 'الأساسي والبدلات' : 'Base & allowances'),
    metricCard(money(s.delivery_pay), isAr ? 'أجر التوصيل' : 'Delivery pay', 'trend'),
    metricCard(money(s.target_bonus), isAr ? 'حافز التارجت' : 'Target bonus', 'trend'),
    metricCard(money(s.total_deductions), isAr ? 'الاستقطاعات' : 'Deductions', 'alert'),
    metricCard(money(s.net_pay), isAr ? 'صافي المستحق' : 'Net pay'),
  ]));

  // Every line the sheet computes, so this screen and the sheet can be compared
  // row by row rather than trusted separately.
  const lines = [
    { label: isAr ? 'الراتب الأساسي والبدلات' : 'Base salary & allowances', value: s.base_salary },
    { label: isAr ? `الطلبات المعتمدة (${s.approved_orders ?? 0} × ${s.per_delivery_rate ?? 0})` : `Approved orders (${s.approved_orders ?? 0} × ${s.per_delivery_rate ?? 0})`, value: s.delivery_pay },
    { label: isAr ? 'حافز التارجت' : 'Target bonus', value: s.target_bonus },
    { label: isAr ? 'ساعات إضافية' : 'Overtime', value: s.overtime_pay },
    { label: isAr ? 'إضافات أخرى' : 'Other additions', value: s.other_additions },
    { label: isAr ? 'إجمالي المستحق' : 'Gross pay', value: s.gross_pay, strong: true },
    { label: isAr ? 'خصم غياب' : 'Absence deduction', value: -Math.abs(s.absence_deduction || 0) },
    { label: isAr ? 'خصم تأخير' : 'Lateness deduction', value: -Math.abs(s.late_deduction || 0) },
    { label: isAr ? 'سلف مستردة' : 'Advances recovered', value: -Math.abs(s.advance_deduction || 0) },
    { label: isAr ? 'خصومات أخرى' : 'Other deductions', value: -Math.abs(s.other_deduction || 0) },
    { label: isAr ? 'مديونية مرحّلة مسددة' : 'Carried debt applied', value: -Math.abs(s.carried_debt_applied || 0) },
    { label: isAr ? 'صافي المستحق للصرف' : 'Net pay', value: s.net_pay, strong: true },
  ].filter((l) => l.strong || Number(l.value || 0) !== 0);

  const statusBadge = period.finalized
    ? badge(isAr ? '🔒 مقفل بلقطة مالية' : '🔒 Finalized snapshot', 'green')
    : badge(isAr ? '✏️ مسودة تشغيلية' : '✏️ Live draft', 'amber');

  wrap.append(el('div', { class: 'card' }, [
    el('div', { style: 'display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:10px' }, [
      el('h3', { style: 'margin:0', text: `${isAr ? 'تفصيل الراتب —' : 'Salary breakdown —'} ${period.month || month}` }),
      statusBadge,
    ]),
    table(
      [
        { key: 'label', label: isAr ? 'البند' : 'Line' },
        { key: 'amount', label: isAr ? 'المبلغ' : 'Amount' },
      ],
      lines.map((l) => ({
        label: l.strong ? `● ${l.label}` : l.label,
        amount: money(l.value),
      }))
    ),
  ]));

  if (Number(s.debt_generated || 0) > 0) {
    wrap.append(el('div', { class: 'card', style: 'border-color:var(--amber)' }, [
      el('p', { style: 'margin:0;color:var(--amber);font-weight:600' },
        isAr
          ? `مدين — مرحّل ${money(s.debt_generated)} للشهر التالي. صافي هذا الشهر صفر.`
          : `In debt — ${money(s.debt_generated)} carried to next month. This month's net is zero.`),
    ]));
  }

  return wrap;
}

async function renderLeave() {
  const id = currentRiderId;
  const wrap = el('div', { id: 'rider360-leave-wrap' });
  const role = appStore.get().role || appStore.get().user?.role || localStorage.getItem('dou_role_v2');
  const canManage = ['COMPANY', 'COMPANY_ADMIN', 'OPERATIONS', 'HR'].includes(role);

  const topBar = el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:16px' }, [
    el('h3', { text: '🌴 سجل وإدارة الإجازات' }),
    canManage ? el('button', { class: 'btn btn-blue', id: 'btn-request-leave', onclick: () => window.openRequestLeaveModal(id) }, '+ طلب إجازة') : null,
  ]);
  wrap.append(topBar);

  try {
    const [entitlements, leaves] = await Promise.all([
      api.get(`/leave/entitlements/${id}`).catch(() => []),
      api.get(`/leave/requests?courier_id=${id}`).catch(() => []),
    ]);

    const ent = entitlements?.[0] || { entitled_days: 21, used_days: 0, pending_days: 0, available_days: 21 };
    
    const metrics = el('div', { class: 'cards', id: 'rider-leave-metrics', style: 'margin-bottom:16px' }, [
      metricCard(ent.available_days ?? ent.entitled_days, 'الرصيد المتاح (أيام)', 'good'),
      metricCard(ent.entitled_days, 'إجمالي الاستحقاق'),
      metricCard(ent.used_days, 'المستخدم', 'normal'),
      metricCard(ent.pending_days, 'طلبات معلقة', ent.pending_days ? 'alert' : 'normal'),
    ]);
    wrap.append(metrics);

    if (!leaves?.length) {
      wrap.append(emptyState('لا توجد طلبات إجازة مسجلة لهذا السائق.'));
      return wrap;
    }

    wrap.append(table([
      { key: 'leave_type_name', label: 'النوع', render: (v) => v || 'إجازة سنوية' },
      { key: 'from_date', label: 'من' },
      { key: 'to_date', label: 'إلى' },
      { key: 'days', label: 'الأيام', render: (v) => `${v || 1} يوم` },
      { key: 'reason', label: 'السبب', render: (v) => v || '—' },
      { key: 'status', label: 'الحالة', render: (v) => badge(v === 'APPROVED' ? 'معتمد' : v === 'PENDING' ? 'قيد المراجعة' : v === 'SUPERVISOR_APPROVED' ? 'معتمد مبدئياً' : 'مرفوض', v === 'APPROVED' ? 'green' : v.includes('PENDING') || v.includes('SUPERVISOR') ? 'amber' : 'red') },
      { key: 'actions', label: 'إجراء', render: (_, r) => (r.status === 'PENDING' || r.status === 'SUPERVISOR_APPROVED') && canManage ? el('div', { class: 'inline-actions' }, [
        el('button', { class: 'btn btn-green btn-small', onclick: () => window.openLeaveDecisionModal(r.id, 'APPROVED') }, 'موافقة'),
        el('button', { class: 'btn btn-red btn-small', onclick: () => window.openLeaveDecisionModal(r.id, 'REJECTED') }, 'رفض'),
      ]) : '—' },
    ], leaves));
  } catch (e) {
    wrap.append(errorState('تعذر تحميل بيانات الإجازات: ' + e.message));
  }

  return wrap;
}

window.openRequestLeaveModal = async (courierId) => {
  try {
    const types = await api.get('/leave/types');
    const typeOptions = (types || []).map(t => ({ value: t.id, label: `${t.name_ar} (حد أقصى ${t.max_days_per_year || 21} يوم)` }));
    if (!typeOptions.length) {
      typeOptions.push({ value: 1, label: 'إجازة سنوية' });
    }

    const todayStr = new Date().toISOString().split('T')[0];
    const form = el('form', { id: 'request-leave-form' }, [
      selectField('leave-type-id', 'نوع الإجازة', typeOptions),
      formRow([
        inputField('leave-from-date', 'من تاريخ', { type: 'date', value: todayStr, required: true }),
        inputField('leave-to-date', 'إلى تاريخ', { type: 'date', value: todayStr, required: true }),
      ]),
      inputField('leave-reason', 'سبب الإجازة', { type: 'text', placeholder: 'مثال: ظروف عائلية أو سفر', required: true }),
      el('button', { type: 'submit', class: 'btn btn-blue', style: 'margin-top:12px' }, 'إرسال طلب الإجازة'),
      el('span', { id: 'leave-req-msg', class: 'msg' })
    ]);

    const m = modal('تقديم طلب إجازة للسائق', form);

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const msg = document.getElementById('leave-req-msg');
      const leaveTypeId = Number(document.getElementById('leave-type-id').value);
      const fromDate = document.getElementById('leave-from-date').value;
      const toDate = document.getElementById('leave-to-date').value;
      const reason = document.getElementById('leave-reason').value;

      try {
        await api.post('/leave/requests', {
          courier_id: courierId,
          leave_type_id: leaveTypeId,
          from_date: fromDate,
          to_date: toDate,
          reason: reason
        });
        msg.style.color = 'var(--green)';
        msg.textContent = '✅ تم إرسال طلب الإجازة بنجاح.';
        setTimeout(() => { m.remove(); switchTab('leave'); }, 800);
      } catch (err) {
        msg.style.color = 'var(--red)';
        msg.textContent = '❌ ' + err.message;
      }
    });
  } catch (e) {
    modal('خطأ', el('p', { text: 'تعذر فتح النموذج: ' + e.message }));
  }
};

window.openLeaveDecisionModal = (requestId, decision) => {
  const isApprove = decision === 'APPROVED';
  const form = el('form', { id: 'leave-decision-form' }, [
    el('p', { style: 'margin-bottom:12px', text: isApprove ? 'هل أنت متأكد من اعتماد طلب الإجازة؟' : 'هل أنت متأكد من رفض طلب الإجازة؟' }),
    inputField('leave-decision-comment', isApprove ? 'ملاحظات الاعتماد (اختياري)' : 'سبب الرفض (مطلوب)', {
      type: 'text',
      placeholder: isApprove ? 'ملاحظات إدارية...' : 'سبب الرفض...',
      required: !isApprove
    }),
    el('button', {
      type: 'submit',
      class: isApprove ? 'btn-green' : 'btn-red',
      style: 'margin-top:12px'
    }, isApprove ? '✅ تأكيد الاعتماد' : '❌ تأكيد الرفض'),
    el('span', { id: 'leave-dec-msg', class: 'msg' })
  ]);

  const m = modal(isApprove ? 'اعتماد طلب الإجازة' : 'رفض طلب الإجازة', form);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const msg = document.getElementById('leave-dec-msg');
    const comment = document.getElementById('leave-decision-comment').value;
    try {
      await api.post(`/leave/requests/${requestId}/admin-decide`, {
        decision,
        comment: comment || null
      });
      msg.style.color = 'var(--green)';
      msg.textContent = isApprove ? '✅ تم اعتماد الإجازة.' : '✅ تم رفض الإجازة.';
      setTimeout(() => { m.remove(); switchTab('leave'); }, 800);
    } catch (err) {
      msg.style.color = 'var(--red)';
      msg.textContent = '❌ ' + err.message;
    }
  });
};

async function assignVehicle() {
  try {
    const vehicles = await api.get('/vehicles/');
    if (!vehicles.length) {
      modal('إسناد مركبة', el('div', {}, [
        el('p', { style: 'color:var(--red)' }, '⚠️ لا توجد مركبات نشطة في الأسطول.'),
        el('button', { class: 'btn btn-ghost', onclick: () => document.querySelector('.modal-overlay')?.remove() }, 'إغلاق')
      ]));
      return;
    }
    const vehicleSelect = selectField('av-vehicle', 'اختر المركبة', vehicles.map(v => ({
      value: v.id,
      label: `${v.plate_number} — ${v.make || ''} ${v.model || ''} (${v.vehicle_type})`
    })));
    const content = el('form', {}, [
      formRow([vehicleSelect]),
      formRow([inputField('av-date', 'تاريخ بداية الإسناد', { type: 'date', value: new Date().toISOString().slice(0, 10), required: true })]),
      el('button', { type: 'submit', class: 'btn btn-blue' }, 'حفظ الإسناد'),
      el('span', { id: 'av-msg', class: 'msg' })
    ]);
    const m = modal('إسناد مركبة للسائق', content);
    content.addEventListener('submit', async (e) => {
      e.preventDefault();
      const msg = document.getElementById('av-msg');
      const vId = Number(document.getElementById('av-vehicle')?.value);
      const dt = document.getElementById('av-date')?.value || new Date().toISOString().slice(0, 10);
      try {
        await api.post(`/vehicles/assignments?vehicle_id=${vId}`, {
          courier_id: currentRiderId,
          effective_from: dt,
          effective_to: null,
          is_primary: true
        });
        msg.style.color = 'var(--green)';
        msg.textContent = '✅ تم إسناد المركبة بنجاح.';
        setTimeout(() => { m.remove(); switchTab('profile'); }, 800);
      } catch (err) {
        msg.style.color = 'var(--red)';
        msg.textContent = '❌ ' + err.message;
      }
    });
  } catch (e) {
    modal('خطأ', el('div', {}, [el('p', { style: 'color:var(--red)' }, 'تعذر تحميل المركبات: ' + e.message)]));
  }
}

async function transitionReadiness(action) {
  try {
    await api.post(`/readiness/${currentRiderId}/transition`, { action, note: null });
    switchTab('profile');
  } catch (e) {
    modal('خطأ في انتقال الجاهزية', el('div', {}, [
      el('p', { style: 'color:var(--red)' }, 'تعذر تنفيذ الإجراء: ' + e.message),
      el('button', { class: 'btn btn-ghost', onclick: () => document.querySelector('.modal-overlay')?.remove() }, 'إغلاق')
    ]));
  }
}

async function assignShift() {
  try {
    const shifts = await api.get('/fleet/shifts');
    if (!shifts.length) {
      modal('إسناد وردية', el('div', {}, [
        el('p', { style: 'color:var(--red)' }, '⚠️ لا توجد ورديات متاحة. أنشئ وردية أولاً من جدول الورديات.'),
        el('button', { class: 'btn btn-ghost', onclick: () => document.querySelector('.modal-overlay')?.remove() }, 'إغلاق')
      ]));
      return;
    }
    const shiftSelect = selectField('as-shift', 'اختر الوردية', shifts.map(s => ({
      value: s.id,
      label: `${s.name || 'وردية #' + s.id} (${s.start_time} – ${s.end_time})`
    })));
    const content = el('form', {}, [
      formRow([shiftSelect]),
      el('button', { type: 'submit', class: 'btn btn-blue' }, 'إسناد الوردية'),
      el('span', { id: 'as-msg', class: 'msg' })
    ]);
    const m = modal('إسناد وردية للسائق', content);
    content.addEventListener('submit', async (e) => {
      e.preventDefault();
      const msg = document.getElementById('as-msg');
      const shiftId = Number(document.getElementById('as-shift')?.value);
      try {
        await api.post(`/shifts/${shiftId}/assign`, { courier_id: currentRiderId });
        msg.style.color = 'var(--green)';
        msg.textContent = '✅ تم إسناد الوردية بنجاح.';
        setTimeout(() => { m.remove(); switchTab('shifts'); }, 800);
      } catch (err) {
        msg.style.color = 'var(--red)';
        msg.textContent = '❌ ' + err.message;
      }
    });
  } catch (e) {
    modal('خطأ', el('div', {}, [el('p', { style: 'color:var(--red)' }, 'تعذر تحميل الورديات: ' + e.message)]));
  }
}

async function setTarget() {
  const content = el('form', {}, [
    formRow([
      selectField('st-type', 'نوع الهدف', [
        { value: 'PERFORMANCE', label: 'أداء (طلبات)' },
        { value: 'ATTENDANCE', label: 'حضور (أيام)' },
        { value: 'FINANCIAL', label: 'مالي' },
      ]),
      inputField('st-period', 'فترة الهدف (YYYY-MM)', { value: new Date().toISOString().slice(0, 7), required: true }),
    ]),
    formRow([
      inputField('st-val', 'قيمة الهدف المطلوب', { type: 'number', min: 1, value: 100, required: true }),
    ]),
    el('button', { type: 'submit', class: 'btn btn-blue' }, 'حفظ الهدف'),
    el('span', { id: 'st-msg', class: 'msg' })
  ]);
  const m = modal('تحديد هدف للسائق', content);
  content.addEventListener('submit', async (e) => {
    e.preventDefault();
    const msg = document.getElementById('st-msg');
    const targetType = document.getElementById('st-type')?.value;
    const period = document.getElementById('st-period')?.value;
    const targetVal = Number(document.getElementById('st-val')?.value);
    try {
      await api.post('/analytics/targets', {
        scope_type: 'RIDER',
        scope_id: currentRiderId,
        target_type: targetType,
        period,
        target_value: targetVal,
      });
      msg.style.color = 'var(--green)';
      msg.textContent = '✅ تم حفظ الهدف بنجاح.';
      setTimeout(() => { m.remove(); switchTab('targets'); }, 800);
    } catch (err) {
      msg.style.color = 'var(--red)';
      msg.textContent = '❌ ' + err.message;
    }
  });
}

window.decideDoc = async (docId, decision) => {
  try {
    await api.post(`/documents/${docId}/review`, {
      decision,
      review_note: decision === 'VALID' ? 'تم الاعتماد الإداري للمستند' : 'المستند غير واضح أو منتهي الصلاحية',
    });
    const pane = document.querySelector('.tab-pane');
    if (pane) loadTabContent('documents', pane);
  } catch (err) {
    alert('تعذر تحديث حالة المستند: ' + err.message);
  }
};

