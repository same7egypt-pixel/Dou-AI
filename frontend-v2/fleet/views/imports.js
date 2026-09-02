// Imports module — rider/performance import workflows and history
import { api } from '../../shared/api/client.js';
import { el, loadingState, emptyState, errorState, table, modal, formRow, escapeHtml } from '../../shared/components/ui.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

let riderImportBatch = null;
let performanceImportBatch = null;

export function renderBulkImportWorkflow({ onRidersImported = null, onPerformanceImported = null } = {}) {
  const isAr = getLang() === 'ar';
  const tabs = el('div', { class: 'filters', style: 'margin-bottom:16px' }, [
    el('button', { class: 'btn btn-blue import-tab', type: 'button', 'data-import-tab': 'riders' }, isAr ? 'استيراد السائقين' : 'Import Drivers'),
    el('button', { class: 'btn btn-ghost import-tab', type: 'button', 'data-import-tab': 'performance' }, isAr ? 'استيراد الأداء' : 'Import Performance'),
  ]);

  const ridersTab = renderImportTab({
    tab: 'riders',
    title: isAr ? 'استيراد السائقين' : 'Import Drivers & Workforce',
    description: isAr ? 'ارفع ملف CSV أو Excel يحتوي على بيانات السائقين. حمّل القالب لمعرفة الأعمدة المطلوبة.' : 'Upload CSV or Excel file containing drivers. Download template for required columns.',
    fileId: 'riderImportFile',
    resultId: 'riderImportResult',
    confirmId: 'riderImportConfirm',
    templateName: 'rider-import-template.csv',
    templatePath: '/fleet/imports/riders/template',
    previewPath: '/fleet/imports/riders/preview',
    confirmPath: (batchId) => `/fleet/imports/riders/${batchId}/confirm`,
    setBatch: (id) => { riderImportBatch = id; },
    getBatch: () => riderImportBatch,
    successMessage: (r) => isAr ? `✅ تم استيراد ${r.result?.imported || 0} سائق بنجاح` : `✅ Successfully imported ${r.result?.imported || 0} drivers`,
    onConfirmed: onRidersImported,
  });

  const performanceTab = renderImportTab({
    tab: 'performance',
    title: isAr ? 'استيراد الأداء التشغيلي' : 'Import Operations & Orders Performance',
    description: isAr ? 'ارفع ملف CSV أو Excel يحتوي على أداء السائقين والطلبات المكتملة لكل يوم.' : 'Upload CSV or Excel containing daily driver orders and performance.',
    fileId: 'performanceImportFile',
    resultId: 'performanceImportResult',
    confirmId: 'performanceImportConfirm',
    templateName: 'performance-import-template.csv',
    templatePath: '/fleet/imports/performance/template',
    previewPath: '/fleet/imports/performance/preview',
    confirmPath: (batchId) => `/fleet/imports/performance/${batchId}/confirm`,
    setBatch: (id) => { performanceImportBatch = id; },
    getBatch: () => performanceImportBatch,
    successMessage: (r) => isAr ? `✅ تم: جديد ${r.result?.imported || 0} · محدث ${r.result?.updated || 0}` : `✅ Done: New ${r.result?.imported || 0} · Updated ${r.result?.updated || 0}`,
    onConfirmed: onPerformanceImported,
  });
  performanceTab.style.display = 'none';

  tabs.querySelectorAll('.import-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      const active = btn.dataset.importTab;
      tabs.querySelectorAll('.import-tab').forEach((b) => {
        // Keep the base `btn` class: the colour modifiers carry no padding or
        // radius of their own, so dropping it renders an unstyled control.
        b.className = `btn ${b.dataset.importTab === active ? 'btn-blue' : 'btn-ghost'} import-tab`;
      });
      ridersTab.style.display = active === 'riders' ? '' : 'none';
      performanceTab.style.display = active === 'performance' ? '' : 'none';
    });
  });

  return el('div', {}, [tabs, ridersTab, performanceTab]);
}

export function openBulkImportModal(options = {}) {
  const isAr = getLang() === 'ar';
  return modal(isAr ? 'الاستيراد الجماعي' : 'Bulk Data Import', renderBulkImportWorkflow(options));
}

function renderImportTab(config) {
  const isAr = getLang() === 'ar';
  const result = el('div', { id: config.resultId, style: 'margin-top:14px' });
  const confirm = el('button', { id: config.confirmId, type: 'button', class: 'btn btn-blue', style: 'display:none' }, isAr ? 'تأكيد الاستيراد' : 'Confirm Import');

  const card = el('div', { class: 'card import-tab-content', 'data-import-content': config.tab }, [
    el('h3', { text: config.title }),
    el('p', { style: 'color:var(--muted);margin-top:-4px' }, config.description),
    formRow([
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => downloadTemplate(config.templatePath, config.templateName) }, isAr ? 'تنزيل القالب' : 'Download Template'),
      el('input', { id: config.fileId, type: 'file', accept: '.csv,text/csv,.xlsx,.xls' }),
    ]),
    formRow([
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => previewImport(config) }, isAr ? 'معاينة' : 'Preview'),
      confirm,
    ]),
    result,
  ]);

  confirm.addEventListener('click', () => confirmImport(config));
  return card;
}

async function downloadTemplate(path, filename) {
  const isAr = getLang() === 'ar';
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
    window.alert((isAr ? 'تعذر تحميل القالب: ' : 'Failed to download template: ') + e.message);
  }
}

async function readImportFile(id) {
  const isAr = getLang() === 'ar';
  const file = document.getElementById(id)?.files?.[0];
  if (!file) throw new Error(isAr ? 'اختر ملفاً أولاً' : 'Please select a file first');
  return { name: file.name, text: await file.text() };
}

async function previewImport(config) {
  const isAr = getLang() === 'ar';
  const result = document.getElementById(config.resultId);
  result.replaceChildren(loadingState(isAr ? 'جاري فحص الملف...' : 'Analyzing file...'));
  document.getElementById(config.confirmId).style.display = 'none';
  try {
    const file = await readImportFile(config.fileId);
    const preview = await api.post(config.previewPath, { csv_text: file.text, file_name: file.name });
    config.setBatch(preview.id);
    result.replaceChildren(renderImportSummary(preview));
    const canConfirm = ['COMPANY', 'COMPANY_ADMIN'].includes(api.getRole());
    document.getElementById(config.confirmId).style.display = canConfirm && preview.valid_rows > 0 && preview.invalid_rows === 0 ? '' : 'none';
  } catch (e) {
    result.replaceChildren(errorState((isAr ? 'تعذرت المعاينة: ' : 'Preview failed: ') + e.message));
  }
}

async function confirmImport(config) {
  const isAr = getLang() === 'ar';
  const batchId = config.getBatch();
  if (!batchId) return;
  const result = document.getElementById(config.resultId);
  result.replaceChildren(loadingState(isAr ? 'جاري تأكيد الاستيراد...' : 'Confirming import...'));
  try {
    const confirmed = await api.post(config.confirmPath(batchId));
    document.getElementById(config.confirmId).style.display = 'none';
    result.replaceChildren(el('p', { style: 'color:var(--green);font-weight:700' }, config.successMessage(confirmed)), renderImportSummary(confirmed));
    if (typeof config.onConfirmed === 'function') config.onConfirmed(confirmed);
  } catch (e) {
    result.replaceChildren(errorState((isAr ? 'تعذر تأكيد الاستيراد: ' : 'Failed to confirm import: ') + e.message));
  }
}

function renderImportSummary(result) {
  const isAr = getLang() === 'ar';
  const errors = result.errors || [];
  const warnings = result.warnings || [];
  const cards = el('div', { class: 'cards', style: 'grid-template-columns:repeat(auto-fit,minmax(120px,1fr))' }, [
    metric(result.total_rows || 0, isAr ? 'إجمالي الصفوف' : 'Total Rows'),
    metric(result.valid_rows || 0, isAr ? 'صالح' : 'Valid', 'trend'),
    metric(result.invalid_rows || 0, isAr ? 'غير صالح' : 'Invalid', 'alert'),
    metric(result.warning_rows || warnings.length || 0, isAr ? 'تحذيرات' : 'Warnings'),
  ]);
  const children = [cards];
  if (errors.length) children.push(renderIssueList(isAr ? 'أخطاء المعاينة' : 'Preview Errors', errors, 'var(--red)'));
  if (warnings.length) children.push(renderIssueList(isAr ? 'تحذيرات' : 'Warnings', warnings, 'var(--amber)'));
  return el('div', {}, children);
}

function metric(value, label, cls = '') {
  return el('div', { class: `metric ${cls}`.trim() }, [el('b', { text: value }), el('span', { text: label })]);
}

function renderIssueList(title, items, color) {
  const isAr = getLang() === 'ar';
  return el('div', { class: 'card', style: `border:1px solid ${color};box-shadow:none` }, [
    el('h3', { text: `${title} (${items.length})` }),
    el('ul', {}, items.slice(0, 20).map((issue) => el('li', { html: `${isAr ? 'صف' : 'Row'} ${escapeHtml(issue.row || '—')}: ${escapeHtml(issue.field || '')}${issue.value !== undefined ? ` = ${escapeHtml(issue.value || '—')}` : ''} — ${escapeHtml(issue.reason || '')}` }))),
    items.length > 20 ? el('p', { style: 'color:var(--muted)' }, isAr ? `و${items.length - 20} عناصر أخرى...` : `and ${items.length - 20} more...`) : null,
  ]);
}

export async function loadImportHistory(container) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [el('div', { class: 'kicker' }, isAr ? 'السائقون' : 'Drivers'), el('h1', { text: isAr ? 'سجل الاستيراد' : 'Import History' })]),
  ]));
  const body = el('div', {}, [loadingState(isAr ? 'جاري تحميل سجل الاستيراد...' : 'Loading import history...')]);
  container.append(body);
  await renderImportHistory(body);
}

export function openImportHistoryModal() {
  const isAr = getLang() === 'ar';
  const body = el('div', {}, [loadingState(isAr ? 'جاري تحميل سجل الاستيراد...' : 'Loading import history...')]);
  modal(isAr ? 'سجل عمليات الاستيراد' : 'Data Import History', body);
  renderImportHistory(body);
}

async function renderImportHistory(target, page = 1) {
  const isAr = getLang() === 'ar';
  try {
    const pageSize = 50;
    const offset = (page - 1) * pageSize;
    const data = await api.get(`/imports/history?limit=${pageSize}&offset=${offset}`);
    const rows = data.rows || data.items || [];
    if (!rows.length) {
      target.replaceChildren(emptyState(isAr ? 'لا توجد عمليات استيراد سابقة.' : 'No previous import history found.'));
      return;
    }
    target.replaceChildren(table([
      { key: 'import_type', label: isAr ? 'النوع' : 'Type', render: (v) => ({ RIDERS: isAr ? 'سائقون' : 'Drivers', PERFORMANCE: isAr ? 'أداء' : 'Performance' }[v] || v || '—') },
      { key: 'file_name', label: isAr ? 'الملف' : 'File Name' },
      { key: 'total_rows', label: isAr ? 'الصفوف' : 'Rows' },
      { key: 'valid_rows', label: isAr ? 'صالح' : 'Valid' },
      { key: 'invalid_rows', label: isAr ? 'غير صالح' : 'Invalid' },
      { key: 'status', label: isAr ? 'الحالة' : 'Status' },
      { key: 'created_at', label: isAr ? 'التاريخ' : 'Date', render: (v) => v ? new Date(v).toLocaleDateString(isAr ? 'ar-SA' : 'en-US') : '—' },
    ], rows));
  } catch (e) {
    target.replaceChildren(errorState((isAr ? 'تعذر التحميل: ' : 'Failed to load: ') + e.message));
  }
}

