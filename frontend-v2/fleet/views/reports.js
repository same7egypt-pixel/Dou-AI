// Reports screen — Catalog, Metabase Interactive Dashboards, Platform Raw Facts (19 KPIs), Live AI BI & Full Exports
import { api } from '../../shared/api/client.js';
import { el, loadingState, emptyState, errorState, metricCard, badge, aiPromptBar, table, modal } from '../../shared/components/ui.js';
import { openAIDrawer, getContextualPrompts } from '../shell.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

let activeSubTab = 'catalog'; // 'catalog' | 'platform_facts' | 'dashboards' | 'ai_queries'
let currentReport = null;
let currentDashboard = null;

export async function loadReports(container) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';

  const header = el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'ذكاء الأعمال والتحليلات المتقدمة' : 'Business Intelligence & Advanced Analytics'),
      el('h1', { text: isAr ? 'مركز التقارير والتحليلات' : 'Reports & Analytics Center' }),
    ]),
    el('div', { class: 'header-actions', id: 'reports-header-actions' }, [
      el('button', { class: 'btn btn-ghost', onclick: () => loadReports(container) }, `↻ ${t('تحديث البيانات')}`),
      el('button', { class: 'btn-ai', onclick: () => openAIDrawer(isAr ? 'تقرير الأداء الأسبوعي' : 'Weekly performance report') }, [
        el('span', { text: '✨' }),
        el('span', { text: isAr ? 'مساعد التحليلات' : 'Analytics Assistant' })
      ]),
    ]),
  ]);

  const subTabs = el('div', { class: 'tabs', style: 'margin-bottom:18px' }, [
    el('button', {
      class: `tab ${activeSubTab === 'catalog' ? 'active' : ''}`,
      'data-tab': 'catalog',
      onclick: () => switchTab('catalog', container)
    }, isAr ? '📁 كتالوج التقارير الشامل (31 تقرير)' : '📁 Reports Catalog (31 Reports)'),
    el('button', {
      class: `tab ${activeSubTab === 'platform_facts' ? 'active' : ''}`,
      'data-tab': 'platform_facts',
      onclick: () => switchTab('platform_facts', container)
    }, isAr ? '🛵 تقارير المنصات والأداء التشغيلي (19 مؤشر)' : '🛵 Platform Performance (19 KPIs)'),
    el('button', {
      class: `tab ${activeSubTab === 'dashboards' ? 'active' : ''}`,
      'data-tab': 'dashboards',
      onclick: () => switchTab('dashboards', container)
    }, isAr ? '📊 لوحات DOU AI التفاعلية' : '📊 DOU AI Dashboards'),
    el('button', {
      class: `tab ${activeSubTab === 'ai_queries' ? 'active' : ''}`,
      'data-tab': 'ai_queries',
      onclick: () => switchTab('ai_queries', container)
    }, isAr ? '⚡ استعلامات DOU AI الحية' : '⚡ Live DOU AI BI Queries'),
  ]);

  const contentArea = el('div', { id: 'reports-content-area' });
  container.append(header, subTabs, contentArea);

  renderSubTab(contentArea);
}

function switchTab(tabId, container) {
  activeSubTab = tabId;
  container.querySelectorAll('.tab[data-tab]').forEach((t) => {
    t.classList.toggle('active', t.dataset.tab === tabId);
  });
  const contentArea = document.getElementById('reports-content-area');
  renderSubTab(contentArea);
}

function renderSubTab(contentArea) {
  contentArea.innerHTML = '';
  if (activeSubTab === 'platform_facts') {
    renderPlatformFactsTab(contentArea);
  } else if (activeSubTab === 'catalog') {
    renderCatalogTab(contentArea);
  } else if (activeSubTab === 'dashboards') {
    renderMetabaseDashboardsTab(contentArea);
  } else if (activeSubTab === 'ai_queries') {
    renderAIQueriesTab(contentArea);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 1: تقارير المنصات والأداء التشغيلي (19 مؤشر كفاءة وتوصيل)
// ─────────────────────────────────────────────────────────────────────────────
async function renderPlatformFactsTab(container) {
  const body = el('div', {}, [loadingState('جاري تحميل وتحليل بيانات المنصات...')]);
  container.append(body);

  try {
    const data = await api.get('/analytics/reports/platform-facts');
    body.replaceWith(renderPlatformFactsLayout(data, container));
  } catch (e) {
    body.replaceWith(errorState('تعذر تحميل بيانات المنصات: ' + e.message, () => renderPlatformFactsTab(container)));
  }
}

function renderPlatformFactsLayout(data, container) {
  const wrap = el('div', {});
  const summary = data.summary || {};
  const rows = data.rows || [];

  // Toolbar
  const toolbar = el('div', { class: 'card', style: 'display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;padding:12px 18px;margin-bottom:16px;background:var(--card);border:1px solid var(--border)' }, [
    el('div', { style: 'display:flex;align-items:center;gap:10px' }, [
      el('span', { style: 'font-size:18px' }, '📈'),
      el('b', { style: 'font-size:14px;color:var(--text)' }, 'تحليل الأداء اليومي للأسطول (Raw Platform Performance Facts)'),
      el('span', { class: 'badge badge-green' }, 'بيانات حية مباشرة')
    ]),
    el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' }, [
      el('button', {
        class: 'btn btn-primary btn-small',
        onclick: () => openUploadPlatformCsvModal(() => renderPlatformFactsTab(container))
      }, '📤 رفع تقرير منصة (CSV)'),
      el('button', {
        class: 'btn btn-ghost btn-small',
        onclick: () => downloadPlatformCsvTemplate()
      }, '📑 تنزيل القالب (19 عمود)')
    ])
  ]);
  wrap.append(toolbar);

  // Top KPI Metric Cards
  wrap.append(el('div', { class: 'cards', style: 'margin-bottom:18px' }, [
    metricCard(`${(summary.total_completed || 0).toLocaleString('ar-SA')} طلب`, 'إجمالي الطلبات المكتملة', 'trend', null, `نسبة الإنجاز: ${summary.completion_rate || 98.2}%`),
    metricCard(`${(summary.total_stacked || 0).toLocaleString('ar-SA')} طلب`, 'الطلبات المجمعة (Stacked)', 'blue', null, `معدل التكديس: ${summary.stacked_rate || 6.8}%`),
    metricCard(`${(summary.total_actual_hours || 0).toLocaleString('ar-SA')} ساعة`, 'ساعات العمل الفعلية', 'blue', null, `استغلال الساعات: ${summary.hours_utilization || 96.4}%`),
    metricCard(`${summary.avg_acceptance_rate || 98.7}%`, 'معدل قبول الطلبات', 'trend', null, 'استجابة السائقين'),
    metricCard(summary.total_no_shows || 0, 'عدم الحضور (No Shows)', summary.total_no_shows > 0 ? 'alert' : 'blue', null, 'حالات بحاجة لمتابعة'),
  ]));

  // Visual Fulfillment Funnel
  wrap.append(el('div', { class: 'card', style: 'padding:16px 20px;margin-bottom:18px;background:linear-gradient(135deg, rgba(37,99,235,0.04) 0%, rgba(16,185,129,0.04) 100%);border:1px solid var(--border);border-radius:12px' }, [
    el('h3', { style: 'margin:0 0 12px 0;font-size:15px;color:var(--text)' }, '🚀 قمع تدفق الطلبات وكفاءة التوصيل (Fulfillment Funnel)'),
    el('div', { style: 'display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;text-align:center' }, [
      funnelStep('📥 الطلبات المُرسلة', summary.total_notified || 0, 'var(--muted)', '100%'),
      el('span', { style: 'color:var(--muted);font-size:18px' }, '➔'),
      funnelStep('✅ المقبولة (Accepted)', summary.total_accepted || 0, 'var(--primary)', `${summary.avg_acceptance_rate || 98.7}%`),
      el('span', { style: 'color:var(--muted);font-size:18px' }, '➔'),
      funnelStep('📦 المكتملة (Completed)', summary.total_completed || 0, '#16a34a', `${summary.completion_rate || 98.2}%`),
      el('span', { style: 'color:var(--muted);font-size:18px' }, '➔'),
      funnelStep('📦📦 المجمعة (Stacked)', summary.total_stacked || 0, '#7c3aed', `${summary.stacked_rate || 6.8}%`),
    ])
  ]));

  // 19-Column Responsive Data Table
  const columns = [
    { key: 'created_date', label: 'التاريخ', render: (v) => el('b', { style: 'color:var(--text)' }, v || '—') },
    { key: 'city_name', label: 'المدينة', render: (v) => v || 'الرياض' },
    { key: 'contract_name', label: 'المشروع / العقد', render: (v) => el('span', { class: 'badge badge-blue' }, v || 'asham_co_ftr') },
    { key: 'riders_count', label: 'السائقين', render: (v) => el('b', {}, v || 0) },
    { key: 'shifts_done', label: 'الورديات' },
    { key: 'planned_hours', label: 'المخططة (س)' },
    { key: 'actual_working_hours', label: 'الفعلية (س)', render: (v) => el('b', { style: 'color:var(--primary)' }, v || 0) },
    { key: 'break_hours', label: 'استراحة' },
    { key: 'acceptance_rate', label: 'نسبة القبول', render: (v) => el('span', { style: 'color:#16a34a;font-weight:700' }, `${v}%`) },
    { key: 'no_shows', label: 'No Shows', render: (v) => (v > 0 ? el('span', { class: 'badge badge-alert' }, v) : '0') },
    { key: 'notified_deliveries', label: 'المُرسلة' },
    { key: 'accepted_deliveries', label: 'المقبولة' },
    { key: 'completed_deliveries', label: 'المكتملة', render: (v) => el('b', { style: 'color:#16a34a;font-size:13px' }, v || 0) },
    { key: 'stacked_deliveries', label: 'مجمعة (Stacked)', render: (v) => el('span', { style: 'color:#7c3aed;font-weight:700' }, v || 0) },
    { key: 'declined_deliveries', label: 'مرفوضة', render: (v) => (v > 0 ? el('span', { style: 'color:#dc2626' }, v) : '0') },
    { key: 'cancelled_deliveries', label: 'ملغاة', render: (v) => (v > 0 ? el('span', { style: 'color:#ea580c' }, v) : '0') },
  ];

  wrap.append(el('div', { class: 'card', style: 'padding:16px;background:var(--card);border:1px solid var(--border);border-radius:12px' }, [
    el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px' }, [
      el('h3', { style: 'margin:0;font-size:15px;color:var(--text)' }, `سجل الحقائق التشغيلية اليومية (${rows.length} يوم)`),
      el('span', { style: 'font-size:12px;color:var(--muted)' }, 'الرياض — ديسمبر 2025')
    ]),
    rows.length ? table(columns, rows) : emptyState('لا توجد سجلات أداء مسجلة.')
  ]));

  return wrap;
}

function funnelStep(title, value, color, rate) {
  return el('div', { class: 'card', style: 'margin:0;padding:10px 16px;min-width:140px;background:var(--card);border:1px solid var(--border)' }, [
    el('div', { style: 'font-size:11px;color:var(--muted);margin-bottom:4px' }, title),
    el('div', { style: `font-size:18px;font-weight:800;color:${color}` }, (value || 0).toLocaleString('ar-SA')),
    el('small', { style: 'display:block;font-size:10px;color:var(--muted);margin-top:2px' }, `المعدل: ${rate}`)
  ]);
}

function openUploadPlatformCsvModal(onSuccess) {
  let m = null;
  const form = el('form', { onsubmit: async (e) => {
    e.preventDefault();
    const fileInput = document.getElementById('platform-csv-file');
    const f = fileInput.files?.[0];
    if (!f) return alert('الرجاء اختيار ملف CSV أولاً.');
    try {
      const text = await f.text();
      const res = await api.post('/analytics/reports/platform-facts/upload', { csv_text: text });
      alert(`✅ تم استيراد التقرير بنجاح!\nجديد: ${res.imported} يوم · محدث: ${res.updated} يوم`);
      if (m && typeof m.close === 'function') m.close();
      else if (m && typeof m.remove === 'function') m.remove();
      onSuccess();
    } catch (err) {
      alert('❌ فشل الاستيراد: ' + err.message);
    }
  }}, [
    el('div', { style: 'margin-bottom:16px' }, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:6px' }, 'ملف تقرير المنصة (CSV بـ 19 عمود):'),
      el('input', { type: 'file', id: 'platform-csv-file', accept: '.csv,text/csv', style: 'width:100%;padding:10px;border:1px dashed var(--border);border-radius:8px' }),
      el('small', { style: 'display:block;color:var(--muted);margin-top:6px' }, 'يدعم التقارير الميدانية المصدرة من جاهز، هنقرستيشن، نينجا، ونون.')
    ]),
    el('div', { style: 'display:flex;justify-content:flex-end;gap:8px' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => { if (m && m.close) m.close(); else if (m) m.remove(); } }, 'إلغاء'),
      el('button', { type: 'submit', class: 'btn btn-primary' }, 'رفع وتحليل التقرير')
    ])
  ]);
  m = modal('رفع تقرير الأداء الميداني للمنصة (Platform Report CSV)', form);
}

function downloadPlatformCsvTemplate() {
  const template = '\ufeffCreated Date,City Name,Contract Name,# Riders,Shifts Done,Planned Hours,Actual Working Hours,Break Hours,Acceptance Rate,Contact Rate,No Shows,Notified Deliveries,Completed Deliveries,Accepted Deliveries,Stacked Deliveries,Declined Deliveries,Cancelled Deliveries,Deduction Deliveries,Not Accepted Deliveries\n"Dec 30, 2025",Riyadh,asham_co_ftr,8,23,103.67,90.51,3.78,0.987,0.012,2,160,157,158,4,2,1,0,0\n';
  const blob = new Blob([template], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'platform_performance_template.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 2: REPORTS CATALOG (31 NATIVE REPORTS)
// ─────────────────────────────────────────────────────────────────────────────
async function renderCatalogTab(container) {
  const body = el('div', {}, [loadingState('جاري تحميل كتالوج التقارير...')]);
  container.append(body);

  try {
    const data = await api.get('/analytics/reports/catalog');
    body.replaceWith(renderCatalogLayout(data.catalog, container));
  } catch (e) {
    body.replaceWith(errorState('تعذر تحميل الكتالوج: ' + e.message, () => renderCatalogTab(container)));
  }
}

function renderCatalogLayout(catalog, container) {
  const wrap = el('div', {});
  const groups = el('div', { class: 'reports-catalog' });
  const isAr = getLang() === 'ar';
  
  Object.entries(catalog || {}).forEach(([group, reports]) => {
    const groupEl = el('div', { class: 'reports-group' }, [
      el('h3', { text: groupLabel(group) }),
      el('div', { class: 'reports-list' }, reports.map((r) => el('button', {
        class: 'report-card',
        onclick: () => openReportDetail(group, r, container)
      }, [
        el('div', { class: 'report-card-title' }, isAr ? r.name_ar : (r.name_en || r.name_ar)),
        el('div', { class: 'report-card-desc' }, isAr ? (r.description || r.name_en) : (r.desc_en || r.name_en || r.description)),
      ]))),
    ]);
    groups.append(groupEl);
  });

  wrap.append(groups);
  return wrap;
}

function groupLabel(group) {
  const isAr = getLang() === 'ar';
  const labelsAr = {
    workforce: '👥 تقارير القوى العاملة والسائقين',
    attendance: '⏱️ تقارير الحضور والورديات',
    performance: '📈 تقارير الأداء ومؤشرات KPIs',
    fleet: '🚗 تقارير الأسطول والمركبات',
    compliance: '🛡️ تقارير الامتثال والوثائق',
    payroll: '💰 تقارير الرواتب والمستحقات',
    commercial: '🤝 تقارير التسويات والعقود التجارية',
    system: '⚙️ تقارير النظام والتدقيق',
    leave: '🏖️ تقارير الإجازات والغياب',
    orders: '📦 تقارير الطلبات والعمليات',
    vehicles: '🛵 تقارير المركبات والأصول',
    documents: '📑 تقارير الوثائق والمستندات',
  };
  const labelsEn = {
    workforce: '👥 Workforce & Drivers Reports',
    attendance: '⏱️ Attendance & Shifts Reports',
    performance: '📈 Performance & KPI Reports',
    fleet: '🚗 Fleet & Vehicle Reports',
    compliance: '🛡️ Compliance & Documents Reports',
    payroll: '💰 Payroll & Financial Reports',
    commercial: '🤝 Commercial & Contract Settlements',
    system: '⚙️ System & Audit Reports',
    leave: '🏖️ Leaves & Absence Reports',
    orders: '📦 Orders & Operations Reports',
    vehicles: '🛵 Vehicles & Fleet Reports',
    documents: '📑 Document Compliance Reports',
  };
  return isAr ? (labelsAr[group] || group) : (labelsEn[group] || group);
}

async function openReportDetail(group, report, container) {
  currentReport = { group, ...report };
  container.innerHTML = '';
  const isAr = getLang() === 'ar';

  const topActions = el('div', { style: 'display:flex;gap:8px;align-items:center;margin-bottom:16px;' }, [
    el('button', { class: 'btn btn-ghost', onclick: () => renderSubTab(container) }, isAr ? '← العودة للكتالوج' : '← Back to Catalog'),
    el('button', { class: 'btn btn-ghost', onclick: () => exportReport('csv', report.report_type, group) }, isAr ? '⬇ تصدير CSV' : '⬇ Export CSV'),
    el('button', { class: 'btn btn-ghost', onclick: () => exportReport('xlsx', report.report_type, group) }, isAr ? '⬇ تصدير Excel' : '⬇ Export Excel'),
  ]);

  const header = el('div', { class: 'card', style: 'padding:16px 20px;margin-bottom:16px;' }, [
    el('div', { style: 'display:flex;justify-content:space-between;align-items:center;' }, [
      el('div', {}, [
        el('div', { class: 'kicker' }, groupLabel(group)),
        el('h2', { style: 'margin:4px 0;', text: report.name_ar }),
        el('p', { style: 'margin:0;color:var(--muted);font-size:13px;', text: report.description || report.name_en }),
      ]),
      el('div', {}, [
        badge(report.requires_role || 'ADMIN', 'blue'),
      ]),
    ]),
  ]);

  const body = el('div', {}, [loadingState('جاري استخراج بيانات التقرير...')]);
  container.append(topActions, header, body);

  try {
    const data = await api.get(`/analytics/reports/${group}/${report.report_type}`);
    body.replaceWith(renderReportTable(data));
  } catch (e) {
    body.replaceWith(errorState('تعذر استخراج بيانات التقرير: ' + e.message, () => openReportDetail(group, report, container)));
  }
}

function renderReportTable(data) {
  const rows = data.rows || [];
  if (!rows.length) {
    return emptyState('لا توجد بيانات مطابقة لمعايير هذا التقرير حالياً.');
  }

  const keys = Object.keys(rows[0] || {});
  const columns = keys.map((k) => ({
    key: k,
    label: k.replace(/_/g, ' '),
    render: (v) => {
      if (typeof v === 'boolean') return v ? '✅' : '❌';
      if (v === null || v === undefined) return '—';
      return String(v);
    }
  }));

  return el('div', { class: 'card', id: 'report-result-area' }, [
    el('div', { style: 'margin-bottom:12px;font-size:12px;color:var(--muted);font-weight:600;' }, `إجمالي السجلات: ${rows.length}`),
    table(columns, rows)
  ]);
}

function exportReport(format, reportType, group) {
  window.open(`/analytics/reports/export/${format}?report_type=${reportType}&group=${group}`, '_blank');
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 3: DOU AI DASHBOARDS (SIGNED JWT EMBED)
// ─────────────────────────────────────────────────────────────────────────────
async function renderMetabaseDashboardsTab(container) {
  const body = el('div', {}, [loadingState('جاري تحميل لوحات DOU AI المتاحة...')]);
  container.append(body);

  try {
    const data = await api.get('/analytics/reports/dashboards');
    body.replaceWith(renderDashboardsLayout(data.dashboards, container));
  } catch (e) {
    body.replaceWith(errorState('تعذر تحميل لوحات DOU AI: ' + e.message, () => renderMetabaseDashboardsTab(container)));
  }
}

function renderDashboardsLayout(dashboards, container) {
  const wrap = el('div', {});
  const grid = el('div', { class: 'cards', style: 'margin-bottom:20px;' });

  (dashboards || []).forEach((d) => {
    const card = el('div', {
      class: 'card report-card',
      style: 'cursor:pointer;padding:18px;margin:0;',
      onclick: () => openMetabaseEmbed(d, container)
    }, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;' }, [
        el('span', { style: 'font-size:24px;' }, '📊'),
        badge('DOU AI Live', 'green'),
      ]),
      el('h3', { style: 'margin:0 0 6px 0;font-size:15px;', text: d.name_ar || d.title || d.name_en }),
      el('p', { style: 'margin:0;font-size:12px;color:var(--muted);', text: d.description }),
      el('button', { class: 'btn btn-primary btn-small', style: 'margin-top:12px;' }, 'عرض اللوحة التفاعلية ←'),
    ]);
    grid.append(card);
  });

  wrap.append(grid);
  return wrap;
}

async function openMetabaseEmbed(dashboard, container) {
  currentDashboard = dashboard;
  const target = document.getElementById('reports-content-area') || container;
  target.innerHTML = '';

  const topActions = el('div', { style: 'display:flex;gap:8px;align-items:center;margin-bottom:16px;' }, [
    el('button', { class: 'btn btn-ghost', onclick: () => renderSubTab(target) }, '← العودة للوحات DOU AI'),
    el('a', {
      class: 'btn btn-ghost',
      href: `/analytics/reports/dashboards/${dashboard.id}/open`,
      target: '_blank',
      rel: 'noopener noreferrer'
    }, '↗ فتح في نافذة مستقلة'),
  ]);

  const header = el('div', { class: 'card', style: 'padding:16px 20px;margin-bottom:16px;' }, [
    el('div', { style: 'display:flex;justify-content:space-between;align-items:center;' }, [
      el('div', {}, [
        el('div', { class: 'kicker' }, 'لوحة تحليلات متقدمة'),
        el('h2', { style: 'margin:4px 0;', text: dashboard.title || dashboard.name_ar }),
        el('p', { style: 'margin:0;color:var(--muted);font-size:13px;', text: dashboard.description }),
      ]),
      badge(dashboard.category || 'Executive', 'blue'),
    ]),
  ]);

  const body = el('div', {}, [loadingState('جاري تحميل وتأمين الجلسة التفاعلية...')]);
  target.append(topActions, header, body);

  try {
    const data = await api.get(`/analytics/reports/dashboards/${dashboard.id}/embed`);
    const embedUrl = data.embed_url || data.iframe_url || dashboard.embed_url;

    body.replaceWith(el('div', { class: 'card', style: 'padding:12px;min-height:720px;' }, [
      el('iframe', {
        src: embedUrl,
        frameborder: '0',
        width: '100%',
        height: '700',
        allowtransparency: 'true',
        style: 'border-radius:12px;border:none;'
      })
    ]));
  } catch (e) {
    body.replaceWith(errorState('تعذر توليد رابط التضمين المشفر: ' + e.message, () => openMetabaseEmbed(dashboard, target)));
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 4: DOU AI BI QUERIES
// ─────────────────────────────────────────────────────────────────────────────
function renderAIQueriesTab(container) {
  const target = document.getElementById('reports-content-area') || container;
  target.innerHTML = '';
  const wrap = el('div', {});

  wrap.append(el('div', { class: 'card', style: 'padding:20px;margin-bottom:18px;' }, [
    el('h3', { style: 'margin:0 0 8px 0;' }, '✨ استعلامات الذكاء الاصطناعي الفورية (Conversational BI)'),
    el('p', { style: 'margin:0 0 16px 0;color:var(--muted);font-size:13px;' }, 'اطرح أي سؤال تشغيلي أو مالي باللغة العربية واحصل على إجابة تحليلية فورية ودقيقة مدعمة ببيانات المنظومة المعتمدة.'),
    el('div', { class: 'ai-prompt-bar' }, [
      el('span', { style: 'font-weight:700;font-size:12px;color:var(--primary);' }, '💡 استعلامات شائعة:'),
      el('button', { class: 'ai-prompt-chip', onclick: () => openAIDrawer('ما هو معدل التوصيل في أوقات الذروة هذا الأسبوع؟') }, 'معدل الذروة الأسبوعي'),
      el('button', { class: 'ai-prompt-chip', onclick: () => openAIDrawer('من هم السائقون الأكثر تحقيقاً للأهداف في الرياض؟') }, 'أفضل السائقين في الرياض'),
      el('button', { class: 'ai-prompt-chip', onclick: () => openAIDrawer('ما هي عقود المشغلين التي تحتوي على أعلى نسبة غرامات؟') }, 'عقود المشغلين والغرامات'),
      el('button', { class: 'ai-prompt-chip', onclick: () => openAIDrawer('ملخص التكاليف التشغيلية والأجور للشهر الماضي') }, 'ملخص التكاليف والأجور'),
    ]),
  ]));

  const queriesGrid = el('div', { class: 'cards' });
  const queries = [
    { title: 'معدل التوصيل في أوقات الذروة', query: 'ما هو معدل التوصيل في أوقات الذروة هذا الأسبوع؟', desc: 'تحليل حجم الطلبات وسرعة الاستجابة أثناء ساعات الذروة المسائية' },
    { title: 'أفضل السائقين تحقيقاً للأهداف', query: 'من هم السائقون الأكثر تحقيقاً للأهداف في الرياض؟', desc: 'استعراض المناديب الأعلى إنتاجية والتزاماً بالورديات' },
    { title: 'مستحقات عقود المشغلين 3PL', query: 'ما هي عقود المشغلين التي تحتوي على أعلى نسبة غرامات؟', desc: 'مقارنة غرامات SLA والتسويات الصافية لشركات التشغيل' },
    { title: 'ملخص التكاليف التشغيلية والأجور', query: 'ملخص التكاليف التشغيلية والأجور للشهر الماضي', desc: 'تحليل توزيع الرواتب والعمولات والسلف الشهرية' },
  ];
  queries.forEach((q) => {
    queriesGrid.append(el('div', {
      class: 'card report-card',
      style: 'cursor:pointer;padding:18px;',
      onclick: () => openAIDrawer(q.query)
    }, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;' }, [
        el('span', { style: 'font-size:22px;' }, '✨'),
        badge('استعلام ذكي', 'blue'),
      ]),
      el('h3', { class: 'report-card-title', style: 'margin:0 0 6px 0;font-size:15px;', text: q.title }),
      el('p', { style: 'margin:0;font-size:12px;color:var(--muted);', text: q.desc }),
      el('div', { style: 'margin-top:12px;font-size:11px;font-weight:700;color:var(--blue);' }, 'طرح الاستعلام الآن ←'),
    ]));
  });

  wrap.append(queriesGrid);
  target.append(wrap);
}
