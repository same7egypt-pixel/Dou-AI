// DOU AI screen — Deterministic Conversational BI & File Export
import { api } from '../../shared/api/client.js';
import { el, loadingState, emptyState, errorState, escapeHtml, badge, showToast } from '../../shared/components/ui.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

let conversationId = null;
window._douaiExports = window._douaiExports || {};

export async function loadDouAI(container) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'ذكاء العمليات والأساطيل' : 'Operations & Fleet Intelligence'),
      el('h1', { text: isAr ? '✨ مساعد DOU AI واستخراج الملفات' : '✨ DOU AI Assistant & File Export' })
    ]),
    el('div', { class: 'header-actions' }, [
      el('button', { class: 'btn btn-ghost', onclick: () => { conversationId = null; loadDouAI(container); } }, isAr ? '+ محادثة جديدة' : '+ New Conversation'),
    ]),
  ]));

  const layout = el('div', { class: 'ai-shell' }, [
    el('div', { class: 'ai-panel' }, [
      el('div', { class: 'ai-head' }, [
        el('div', {}, [
          el('h2', { text: isAr ? 'مساعد العمليات والتقارير القابلة للتنزيل' : 'Field Operations & Downloadable Reports' }),
          el('p', { text: isAr ? 'اسأل عن أي مؤشر أو تقرير، وسيقوم DOU AI بفهم طلبك واستخراج الملف مباشرة لحفظه كـ Excel/CSV.' : 'Ask for any operational report or table. DOU AI will generate and export it as Excel/CSV instantly.' })
        ]),
        badge(isAr ? 'بيانات حية 100%' : '100% Verified Live Data', 'green'),
      ]),
      el('div', { class: 'ai-messages', id: 'ai-messages' }, [
        el('div', { class: 'ai-empty' }, [
          el('div', { style: 'font-size:36px;margin-bottom:10px' }, '✨'),
          el('b', { text: isAr ? 'كيف يمكنني مساعدتك في استخراج بيانات أسطولك اليوم؟' : 'How can I assist you with your fleet reports today?' }),
          el('span', { text: isAr ? 'اكتب استفسارك وسأعرض النتائج فوراً مع زر تنزيل الملف لحفظه على جهازك.' : 'Type your query and I will provide the live data with an instant download button.' })
        ])
      ]),
      el('div', { class: 'ai-compose' }, [
        el('textarea', {
          id: 'ai-input',
          placeholder: isAr ? 'اكتب سؤالك (مثال: هات لي ملف السائقين الغائبين اليوم، أو نزل لي شيت الرواتب)...' : 'Type your query (e.g. Export absent drivers today, or Download payroll sheet)...',
          onkeydown: (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAI(); } }
        }),
        el('button', { class: 'btn btn-blue', id: 'ai-send', onclick: () => sendAI() }, isAr ? 'إرسال' : 'Send'),
      ]),
    ]),
    el('aside', { class: 'ai-side' }, [
      el('div', { class: 'card' }, [
        el('h3', { text: isAr ? '⚡ ملفات واستفسارات سريعة' : '⚡ Quick Reports & Files' }),
        el('div', { class: 'ai-prompts' }, [
          el('span', { style: 'font-size:11px;font-weight:700;color:var(--muted);margin-top:6px;display:block' }, isAr ? 'ملفات الحضور والغياب:' : 'Attendance & Absence:'),
          el('button', { class: 'ai-prompt', onclick: () => askPrompt(isAr ? 'هات لي ملف السائقين الغائبين اليوم' : 'Export absent drivers today') }, isAr ? '📥 ملف السائقين الغائبين اليوم' : '📥 Absent drivers today (File)'),
          el('button', { class: 'ai-prompt', onclick: () => askPrompt(isAr ? 'كشف حضور السائقين هذا الأسبوع' : 'Drivers attendance report this week') }, isAr ? '⏱️ كشف الحضور هذا الأسبوع' : '⏱️ Attendance sheet this week'),

          el('span', { style: 'font-size:11px;font-weight:700;color:var(--muted);margin-top:10px;display:block' }, isAr ? 'الرواتب والأداء:' : 'Payroll & Performance:'),
          el('button', { class: 'ai-prompt', onclick: () => askPrompt(isAr ? 'نزل لي شيت الرواتب والخصومات' : 'Download payroll and deductions sheet') }, isAr ? '💰 شيت الرواتب والخصومات' : '💰 Payroll & Deductions sheet'),
          el('button', { class: 'ai-prompt', onclick: () => askPrompt(isAr ? 'ملف السائقين تحت المستهدف' : 'Drivers below target report') }, isAr ? '🎯 ملف السائقين تحت التارجت' : '🎯 Drivers below target (File)'),

          el('span', { style: 'font-size:11px;font-weight:700;color:var(--muted);margin-top:10px;display:block' }, isAr ? 'الجاهزية والوثائق:' : 'Readiness & Docs:'),
          el('button', { class: 'ai-prompt', onclick: () => askPrompt(isAr ? 'ما الذي يحتاج انتباهي اليوم؟' : 'What needs my attention today?') }, isAr ? '⚠️ ما الذي يحتاج انتباهي اليوم؟' : '⚠️ What needs attention today?'),
          el('button', { class: 'ai-prompt', onclick: () => askPrompt(isAr ? 'ملف الوثائق المنتهية وقرب الانتهاء' : 'Expiring documents report') }, isAr ? '📑 كشف الوثائق المنتهية' : '📑 Expiring documents list'),
        ])
      ]),
      el('div', { class: 'card' }, [
        el('h3', { text: isAr ? 'حالة محرك الاستعلام والتصدير' : 'Engine & Export Status' }),
        el('p', { id: 'ai-status', style: 'font-size:11.5px;color:var(--muted)' }, isAr ? 'جاهز للاستعلام وتصدير الملفات' : 'Ready for queries & file exports')
      ]),
    ]),
  ]);

  container.append(layout);
  checkAIStatus();
}

async function checkAIStatus() {
  const isAr = getLang() === 'ar';
  try {
    const s = await api.get('/ai/status');
    const statusEl = document.getElementById('ai-status');
    if (statusEl) {
      if (s.available) {
        statusEl.textContent = isAr ? '● محرك التحليلات وتصدير الملفات متصل' : '● Live analytics & file export engine ready';
      } else {
        statusEl.textContent = isAr ? '● تحليلات وتصدير DOU المصرح به جاهز' : '● Authorized DOU deterministic export ready';
      }
    }
  } catch (e) {
    const statusEl = document.getElementById('ai-status');
    if (statusEl) statusEl.textContent = isAr ? 'حالة الخدمة غير متاحة' : 'Service status unavailable';
  }
}

function askPrompt(text) {
  document.getElementById('ai-input').value = text;
  sendAI();
}

async function sendAI() {
  const isAr = getLang() === 'ar';
  const input = document.getElementById('ai-input');
  const btn = document.getElementById('ai-send');
  const question = input.value.trim();
  if (!question || btn.disabled) return;
  input.value = '';
  btn.disabled = true;
  btn.textContent = '...';

  const box = document.getElementById('ai-messages');
  box.querySelector('.ai-empty')?.remove();
  box.insertAdjacentHTML('beforeend', `<div class="ai-msg user">${escapeHtml(question)}</div>`);
  const loading = el('div', { class: 'ai-msg assistant' }, isAr ? 'DOU AI يسترجع البيانات ويجهز الملف المطلوب...' : 'DOU AI is retrieving data and preparing your file...');
  box.append(loading);
  box.scrollTop = box.scrollHeight;

  try {
    const data = await api.post('/ai/chat', { question, conversation_id: conversationId, context: { current_view: 'douai' } });
    conversationId = data.conversation_id;
    loading.remove();
    renderAIResponse(data, question);
  } catch (e) {
    loading.innerHTML = (isAr ? 'تعذر إكمال الطلب: ' : 'Failed to process request: ') + escapeHtml(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = isAr ? 'إرسال' : 'Send';
  }
}

function renderAIResponse(data, originalQuestion = '') {
  const isAr = getLang() === 'ar';
  const box = document.getElementById('ai-messages');
  let html = `<div class="ai-msg assistant"><div>${escapeHtml(data.answer)}</div>`;
  
  if (data.kpis?.length) {
    html += `<div class="ai-kpis">${data.kpis.map((k) => `<div class="ai-kpi"><b>${escapeHtml(k.value)}</b><span>${escapeHtml(k.label)}</span></div>`).join('')}</div>`;
  }

  const exportId = 'exp_' + Math.random().toString(36).substring(2, 9);

  if (data.table?.rows?.length) {
    const cols = data.table.columns || [];
    const rows = data.table.rows;
    window._douaiExports[exportId] = {
      title: data.answer.split('\n')[0] || 'DOU_Report',
      columns: cols,
      rows: rows
    };

    const fileName = `DOU_${(data.table.name || 'Report').replace(/[^a-zA-Z0-9_]/g, '_')}_${new Date().toISOString().slice(0, 10)}.csv`;

    // File download card
    html += `
      <div class="ai-export-card">
        <div class="ai-export-info">
          <div class="ai-export-icon">📊</div>
          <div class="ai-export-details">
            <b>${isAr ? 'ملف البيانات المولد جاهز للحفظ' : 'Generated Report File Ready'}</b>
            <span>${fileName} · ${rows.length} ${isAr ? 'سجل / صف' : 'rows'}</span>
          </div>
        </div>
        <div class="ai-export-actions">
          <button class="ai-export-btn ai-export-btn-primary" onclick="window.downloadDouaiCSV('${exportId}', '${fileName}')">
            📥 ${isAr ? 'تنزيل وحفظ ملف Excel (CSV)' : 'Save as Excel / CSV'}
          </button>
          <button class="ai-export-btn ai-export-btn-secondary" onclick="window.printDouaiPDF('${exportId}')">
            🖨️ ${isAr ? 'طباعة / PDF' : 'Print / PDF'}
          </button>
        </div>
      </div>
    `;

    // Interactive Preview Table
    html += `<div class="table-wrap" style="margin-top:10px"><table><thead><tr>${cols.map((c) => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead><tbody>${rows.slice(0, 25).map((r) => `<tr>${cols.map((c) => `<td>${escapeHtml(r[c] !== undefined && r[c] !== null ? r[c] : '-')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    if (rows.length > 25) {
      html += `<div style="font-size:11px;color:var(--muted);margin-top:4px;text-align:center">${isAr ? `(يتم عرض 25 صفاً من أصل ${rows.length} صف، قم بتنزيل الملف لعرض كافة البيانات)` : `(Showing 25 of ${rows.length} rows. Download full file to view all)`}</div>`;
    }
  } else if (data.kpis?.length && !data.table?.rows?.length) {
    // Generate KPI export
    const kpiRows = data.kpis.map(k => ({ [isAr ? 'المؤشر' : 'Metric']: k.label, [isAr ? 'القيمة' : 'Value']: k.value }));
    const kpiCols = [isAr ? 'المؤشر' : 'Metric', isAr ? 'القيمة' : 'Value'];
    window._douaiExports[exportId] = {
      title: 'DOU_KPI_Summary',
      columns: kpiCols,
      rows: kpiRows
    };
    const fileName = `DOU_Summary_${new Date().toISOString().slice(0, 10)}.csv`;
    html += `
      <div class="ai-export-card">
        <div class="ai-export-info">
          <div class="ai-export-icon">📑</div>
          <div class="ai-export-details">
            <b>${isAr ? 'ملف ملخص المؤشرات جاهز للحفظ' : 'KPI Summary Ready'}</b>
            <span>${fileName}</span>
          </div>
        </div>
        <div class="ai-export-actions">
          <button class="ai-export-btn ai-export-btn-primary" onclick="window.downloadDouaiCSV('${exportId}', '${fileName}')">
            📥 ${isAr ? 'تنزيل ملخص (Excel)' : 'Download Summary'}
          </button>
        </div>
      </div>
    `;
  }

  const sourceLabel = isAr ? 'المصدر: ' : 'Source: ';
  const freshnessLabel = isAr ? ' · الحداثة: ' : ' · Freshness: ';
  const latencyLabel = isAr ? ' · زمن الاستجابة: ' : ' · Latency: ';
  html += `<div class="ai-meta">${sourceLabel}${escapeHtml(data.source)}${freshnessLabel}${escapeHtml(data.freshness)}${latencyLabel}${escapeHtml(data.latency_ms)}ms</div></div>`;
  box.insertAdjacentHTML('beforeend', html);
  box.scrollTop = box.scrollHeight;
}

// Global functions for instant client-side file export with UTF-8 BOM for flawless Excel Arabic support
window.downloadDouaiCSV = function(exportId, fileName) {
  const item = window._douaiExports[exportId];
  if (!item || !item.rows?.length) return showToast('No export data found', 'info');

  const cols = item.columns || Object.keys(item.rows[0] || {});
  
  // Format CSV rows
  const csvRows = [];
  // Header row
  csvRows.push(cols.map(c => `"${String(c).replace(/"/g, '""')}"`).join(','));
  
  // Data rows
  item.rows.forEach(r => {
    csvRows.push(cols.map(c => {
      const val = r[c] !== undefined && r[c] !== null ? String(r[c]) : '';
      return `"${val.replace(/"/g, '""')}"`;
    }).join(','));
  });

  // UTF-8 BOM prefix \uFEFF ensures Excel renders Arabic properly without garbled characters
  const csvContent = '\uFEFF' + csvRows.join('\r\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName || 'DOU_Export.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

window.printDouaiPDF = function(exportId) {
  const item = window._douaiExports[exportId];
  if (!item || !item.rows?.length) return showToast('No export data found', 'info');

  const isAr = getLang() === 'ar';
  const cols = item.columns || Object.keys(item.rows[0] || {});
  
  const printWindow = window.open('', '_blank');
  printWindow.document.write(`
    <!DOCTYPE html>
    <html dir="${isAr ? 'rtl' : 'ltr'}" lang="${isAr ? 'ar' : 'en'}">
    <head>
      <title>${escapeHtml(item.title || 'DOU Report')}</title>
      <style>
        body { font-family: Tahoma, Arial, sans-serif; padding: 24px; color: #1e293b; direction: ${isAr ? 'rtl' : 'ltr'}; }
        .header { border-bottom: 2px solid #ff5500; padding-bottom: 12px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }
        h1 { font-size: 20px; margin: 0; color: #0f172a; }
        .meta { font-size: 11px; color: #64748b; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 12px; }
        th, td { border: 1px solid #cbd5e1; padding: 8px 12px; text-align: ${isAr ? 'right' : 'left'}; }
        th { background: #f8fafc; font-weight: bold; }
        tr:nth-child(even) { background: #f8fafc; }
      </style>
    </head>
    <body>
      <div class="header">
        <div>
          <h1>${escapeHtml(item.title || 'DOU Report')}</h1>
          <div class="meta">${isAr ? 'تم استخراج التقرير عبر DOU AI' : 'Generated by DOU AI'} · ${new Date().toLocaleDateString()}</div>
        </div>
        <div style="font-weight:900;font-size:20px;color:#ff5500">DOU Fleet OS</div>
      </div>
      <table>
        <thead>
          <tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr>
        </thead>
        <tbody>
          ${item.rows.map(r => `<tr>${cols.map(c => `<td>${escapeHtml(r[c] !== undefined && r[c] !== null ? r[c] : '-')}</td>`).join('')}</tr>`).join('')}
        </tbody>
      </table>
    </body>
    </html>
  `);
  printWindow.document.close();
  printWindow.focus();
  setTimeout(() => {
    printWindow.print();
  }, 500);
};

