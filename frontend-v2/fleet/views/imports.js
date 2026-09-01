// Imports module — rider/performance import workflows and history
import { api } from '../../shared/api/client.js';
import { el, loadingState, emptyState, errorState, table, modal, formRow, escapeHtml } from '../../shared/components/ui.js';

let riderImportBatch = null;
let performanceImportBatch = null;

export function renderBulkImportWorkflow({ onRidersImported = null, onPerformanceImported = null } = {}) {
  const tabs = el('div', { class: 'filters', style: 'margin-bottom:16px' }, [
    el('button', { class: 'btn-blue import-tab', type: 'button', 'data-import-tab': 'riders' }, 'استيراد السائقين'),
    el('button', { class: 'btn-ghost import-tab', type: 'button', 'data-import-tab': 'performance' }, 'استيراد الأداء'),
  ]);

  const ridersTab = renderImportTab({
    tab: 'riders',
    title: 'استيراد السائقين',
    description: 'ارفع ملف CSV أو Excel يحتوي على بيانات السائقين. حمّل القالب لمعرفة الأعمدة المطلوبة.',
    fileId: 'riderImportFile',
    resultId: 'riderImportResult',
    confirmId: 'riderImportConfirm',
    templateName: 'rider-import-template.csv',
    templatePath: '/fleet/imports/riders/template',
    previewPath: '/fleet/imports/riders/preview',
    confirmPath: (batchId) => `/fleet/imports/riders/${batchId}/confirm`,
    setBatch: (id) => { riderImportBatch = id; },
    getBatch: () => riderImportBatch,
    successMessage: (r) => `✅ تم استيراد ${r.result?.imported || 0} سائق بنجاح`,
    onConfirmed: onRidersImported,
  });

  const performanceTab = renderImportTab({
    tab: 'performance',
    title: 'استيراد الأداء التشغيلي',
    description: 'ارفع ملف CSV أو Excel يحتوي على أداء السائقين والطلبات المكتملة لكل يوم.',
    fileId: 'performanceImportFile',
    resultId: 'performanceImportResult',
    confirmId: 'performanceImportConfirm',
    templateName: 'performance-import-template.csv',
    templatePath: '/fleet/imports/performance/template',
    previewPath: '/fleet/imports/performance/preview',
    confirmPath: (batchId) => `/fleet/imports/performance/${batchId}/confirm`,
    setBatch: (id) => { performanceImportBatch = id; },
    getBatch: () => performanceImportBatch,
    successMessage: (r) => `✅ تم: جديد ${r.result?.imported || 0} · محدث ${r.result?.updated || 0}`,
    onConfirmed: onPerformanceImported,
  });
  performanceTab.style.display = 'none';

  tabs.querySelectorAll('.import-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      const active = btn.dataset.importTab;
      tabs.querySelectorAll('.import-tab').forEach((b) => {
        b.className = `${b.dataset.importTab === active ? 'btn-blue' : 'btn-ghost'} import-tab`;
      });
      ridersTab.style.display = active === 'riders' ? '' : 'none';
      performanceTab.style.display = active === 'performance' ? '' : 'none';
    });
  });

  return el('div', {}, [tabs, ridersTab, performanceTab]);
}

export function openBulkImportModal(options = {}) {
  return modal('الاستيراد الجماعي', renderBulkImportWorkflow(options));
}

function renderImportTab(config) {
  const result = el('div', { id: config.resultId, style: 'margin-top:14px' });
  const confirm = el('button', { id: config.confirmId, type: 'button', class: 'btn-blue', style: 'display:none' }, 'تأكيد الاستيراد');

  const card = el('div', { class: 'card import-tab-content', 'data-import-content': config.tab }, [
    el('h3', { text: config.title }),
    el('p', { style: 'color:var(--muted);margin-top:-4px' }, config.description),
    formRow([
      el('button', { type: 'button', class: 'btn-ghost', onclick: () => downloadTemplate(config.templatePath, config.templateName) }, 'تنزيل القالب'),
      el('input', { id: config.fileId, type: 'file', accept: '.csv,text/csv,.xlsx,.xls' }),
    ]),
    formRow([
      el('button', { type: 'button', class: 'btn-ghost', onclick: () => previewImport(config) }, 'معاينة'),
      confirm,
    ]),
    result,
  ]);

  confirm.addEventListener('click', () => confirmImport(config));
  return card;
}

async function downloadTemplate(path, filename) {
  try {
    const res = await fetch(path, { headers: { Authorization: `Bearer ${api.getToken()}` } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 200);
  } catch (e) {
    window.alert('تعذر تحميل القالب: ' + e.message);
  }
}

async function readImportFile(id) {
  const file = document.getElementById(id)?.files?.[0];
  if (!file) throw new Error('اختر ملفاً أولاً');
  return { name: file.name, text: await file.text() };
}

async function previewImport(config) {
  const result = document.getElementById(config.resultId);
  result.replaceChildren(loadingState('جاري فحص الملف...'));
  document.getElementById(config.confirmId).style.display = 'none';
  try {
    const file = await readImportFile(config.fileId);
    const preview = await api.post(config.previewPath, { csv_text: file.text, file_name: file.name });
    config.setBatch(preview.id);
    result.replaceChildren(renderImportSummary(preview));
    const canConfirm = ['COMPANY', 'COMPANY_ADMIN'].includes(api.getRole());
    document.getElementById(config.confirmId).style.display = canConfirm && preview.valid_rows > 0 && preview.invalid_rows === 0 ? '' : 'none';
  } catch (e) {
    result.replaceChildren(errorState('تعذرت المعاينة: ' + e.message));
  }
}

async function confirmImport(config) {
  const batchId = config.getBatch();
  if (!batchId) return;
  const result = document.getElementById(config.resultId);
  result.replaceChildren(loadingState('جاري تأكيد الاستيراد...'));
  try {
    const confirmed = await api.post(config.confirmPath(batchId));
    document.getElementById(config.confirmId).style.display = 'none';
    result.replaceChildren(el('p', { style: 'color:var(--green);font-weight:700' }, config.successMessage(confirmed)), renderImportSummary(confirmed));
    if (typeof config.onConfirmed === 'function') config.onConfirmed(confirmed);
  } catch (e) {
    result.replaceChildren(errorState('تعذر تأكيد الاستيراد: ' + e.message));
  }
}

function renderImportSummary(result) {
  const errors = result.errors || [];
  const warnings = result.warnings || [];
  const cards = el('div', { class: 'cards', style: 'grid-template-columns:repeat(auto-fit,minmax(120px,1fr))' }, [
    metric(result.total_rows || 0, 'إجمالي الصفوف'),
    metric(result.valid_rows || 0, 'صالح', 'trend'),
    metric(result.invalid_rows || 0, 'غير صالح', 'alert'),
    metric(result.warning_rows || warnings.length || 0, 'تحذيرات'),
  ]);
  const children = [cards];
  if (errors.length) children.push(renderIssueList('أخطاء المعاينة', errors, 'var(--red)'));
  if (warnings.length) children.push(renderIssueList('تحذيرات', warnings, 'var(--amber)'));
  return el('div', {}, children);
}

function metric(value, label, cls = '') {
  return el('div', { class: `metric ${cls}`.trim() }, [el('b', { text: value }), el('span', { text: label })]);
}

function renderIssueList(title, items, color) {
  return el('div', { class: 'card', style: `border:1px solid ${color};box-shadow:none` }, [
    el('h3', { text: `${title} (${items.length})` }),
    el('ul', {}, items.slice(0, 20).map((issue) => el('li', { html: `صف ${escapeHtml(issue.row || '—')}: ${escapeHtml(issue.field || '')}${issue.value !== undefined ? ` = ${escapeHtml(issue.value || '—')}` : ''} — ${escapeHtml(issue.reason || '')}` }))),
    items.length > 20 ? el('p', { style: 'color:var(--muted)' }, `و${items.length - 20} عناصر أخرى...`) : null,
  ]);
}

export async function loadImportHistory(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [el('div', { class: 'kicker' }, 'السائقون'), el('h1', { text: 'سجل الاستيراد' })]),
  ]));
  const body = el('div', {}, [loadingState('جاري تحميل سجل الاستيراد...')]);
  container.append(body);
  await renderImportHistory(body);
}

export function openImportHistoryModal() {
  const body = el('div', {}, [loadingState('جاري تحميل سجل الاستيراد...')]);
  modal('سجل عمليات الاستيراد', body);
  renderImportHistory(body);
}

async function renderImportHistory(target, page = 1) {
  try {
    const pageSize = 50;
    const offset = (page - 1) * pageSize;
    const data = await api.get(`/imports/history?limit=${pageSize}&offset=${offset}`);
    const rows = data.rows || data.items || [];
    if (!rows.length) {
      target.replaceChildren(emptyState('لا توجد عمليات استيراد سابقة.'));
      return;
    }
    target.replaceChildren(table([
      { key: 'import_type', label: 'النوع', render: (v) => ({ RIDERS: 'سائقون', PERFORMANCE: 'أداء' }[v] || v || '—') },
      { key: 'file_name', label: 'الملف' },
      { key: 'total_rows', label: 'الصفوف' },
      { key: 'valid_rows', label: 'صالح' },
      { key: 'invalid_rows', label: 'غير صالح' },
      { key: 'status', label: 'الحالة' },
      { key: 'created_at', label: 'التاريخ', render: (v) => v ? new Date(v).toLocaleDateString() : '—' },
    ], rows));
  } catch (e) {
    target.replaceChildren(errorState('تعذر التحميل: ' + e.message));
  }
}
