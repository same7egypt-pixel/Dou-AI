// Command Center — Intelligent Operational KPIs, Real-time Status, Master Plan Launchpad & Priority Action Queue
import { api } from '../../shared/api/client.js';
import { appStore, isDeliveryPlatform } from '../../shared/state/store.js';
import { el, loadingState, emptyState, errorState, metricCard, badge, aiPromptBar, priorityActionCard } from '../../shared/components/ui.js';
import { go, openAIDrawer, getContextualPrompts } from '../shell.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

export async function loadCommandCenter(container) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'مركز القيادة التشغيلي الموحد' : 'Unified Operational Command Center'),
      el('h1', { text: isAr ? 'مركز القيادة والعمليات' : 'Command Center & Operations' })
    ]),
    el('div', { class: 'header-actions' }, [
      el('button', { class: 'btn btn-ghost', onclick: () => loadCommandCenter(container) }, `↻ ${t('تحديث البيانات')}`),
      el('button', { class: 'btn btn-ai', onclick: () => openAIDrawer() }, [
        el('span', { text: '✨' }),
        el('span', { text: isAr ? 'استفسار ذكي' : 'Smart Query' })
      ]),
    ]),
  ]));

  const state = el('div', {}, [loadingState(isAr ? 'جاري تحميل بيانات مركز القيادة...' : 'Loading Command Center data...')]);
  container.append(state);

  try {
    const [overview, needsAttention] = await Promise.all([
      api.get('/fleet/overview').catch(() => ({ total_riders: 0, online_riders: 0, active_riders: 0, absent_today: 0, present_today: 0, ready_riders: 0, not_ready_riders: 0, on_leave: 0, pending_leaves: 0, expired_docs: 0, expiring_30: 0, expiring_60: 0 })),
      api.get('/analytics/needs-attention/deterministic').catch(() => ({ items: [] })),
    ]);
    state.replaceWith(renderDashboard(overview, needsAttention));
  } catch (e) {
    state.replaceWith(errorState((isAr ? 'تعذر تحميل البيانات: ' : 'Failed to load data: ') + e.message, () => loadCommandCenter(container)));
  }
}

function renderFirstRunGuide(overview, isAr) {
  // Each step reports its own state from data, so the guide is a live checklist
  // rather than a static banner that keeps congratulating you on nothing.
  const steps = [
    {
      done: Number(overview?.contracts_total ?? 0) > 0,
      title: isAr ? 'العقد التجاري وفرع التشغيل' : 'Commercial contract & branch',
      why: isAr ? 'مين العميل، وأي مدينة بتغطيها' : 'Who the client is, and which city it covers',
      cta: isAr ? 'أنشئ العقد' : 'Create contract',
      go: async (c) => { const m = await import('./capacity.js'); m.openCreateContractModal(c); },
    },
    {
      done: Number(overview?.supervisors_total ?? 0) > 0,
      title: isAr ? 'المشرف الميداني' : 'Field supervisor',
      why: isAr ? 'مين مسؤول عن المناديب في الفرع' : 'Who is responsible for riders at the branch',
      cta: isAr ? 'أضف مشرف' : 'Add supervisor',
      go: async (c) => { const m = await import('./capacity.js'); m.openSupervisorsManagementModal(c); },
    },
    {
      done: Number(overview?.couriers_total ?? 0) > 0,
      title: isAr ? 'أول مندوب' : 'Your first rider',
      why: isAr ? 'ومن هنا كل حاجة تانية بتشتغل' : 'Everything else runs from here',
      cta: isAr ? 'أضف مندوب' : 'Add rider',
      go: () => go('riders'),
    },
  ];
  const doneCount = steps.filter((s) => s.done).length;

  const box = el('div', {
    style: 'background:var(--card);border:1px solid var(--border);border-inline-start:3px solid var(--primary);'
         + 'border-radius:12px;padding:20px 22px;margin:16px 0 20px'
  }, [
    el('div', { style: 'display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap' }, [
      el('h3', { style: 'margin:0 0 4px;font-size:16px;color:var(--text)' },
        isAr ? '👋 ابدأ من هنا' : '👋 Start here'),
      el('span', { style: 'font-size:12px;color:var(--muted)' },
        isAr ? `${doneCount} من ${steps.length} خطوات` : `${doneCount} of ${steps.length} steps`),
    ]),
    el('p', { style: 'margin:0 0 16px;font-size:13px;color:var(--muted);line-height:1.9' },
      isAr
        ? 'ثلاث خطوات، مرة واحدة، وبعدها المنظومة كلها شغالة: الورديات والحضور والرواتب ومطابقة شيتات المنصات.'
        : 'Three steps, once. After them everything works: shifts, attendance, payroll and platform sheet matching.'),
    el('div', { style: 'display:grid;gap:8px' }, steps.map((step, i) => el('div', {
      style: 'display:flex;align-items:center;gap:12px;padding:11px 13px;border-radius:9px;'
           + `border:1px solid var(--border);background:${step.done ? 'transparent' : 'var(--bg)'};`
           + (step.done ? 'opacity:.6' : '')
    }, [
      el('span', { style: `font-family:monospace;font-size:13px;color:${step.done ? 'var(--green)' : 'var(--primary)'};min-width:18px` },
        step.done ? '✓' : String(i + 1)),
      el('div', { style: 'flex:1;min-width:0' }, [
        el('div', { style: 'font-size:14px;font-weight:600;color:var(--text)' }, step.title),
        el('div', { style: 'font-size:12px;color:var(--muted)' }, step.why),
      ]),
      step.done ? null : el('button', {
        class: 'btn btn-primary btn-small',
        onclick: () => step.go(document.getElementById('content-area')),
      }, step.cta),
    ].filter(Boolean)))),
  ]);
  return box;
}

function renderDashboard(overview, needsAttention) {
  const wrap = el('div', {});
  const isAr = getLang() === 'ar';
  const attentionItems = needsAttention?.items || [];
  const highSeverityCount = attentionItems.filter(i => i.severity === 'high').length;
  
  // 1. Live Operational Status Bar
  const now = new Date();
  const timeStr = now.toLocaleTimeString(isAr ? 'ar-SA' : 'en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const dateStr = now.toISOString().slice(0, 10);
  
  let statusClass = 'healthy';
  let statusText = isAr ? 'الأسطول يعمل بحالة مستقرة وطبيعية' : 'Fleet is operating in normal healthy condition';
  // An account with no riders has no fleet to be stable. Saying it anyway was
  // the first sentence this product spoke to a paying customer, and it taught
  // them that its status messages are not measured — which costs the next
  // "healthy" and every one after it.
  const fleetSize = Number(overview?.couriers_total ?? 0);
  if (fleetSize === 0) {
    statusClass = 'warning';
    statusText = isAr
      ? 'لا يوجد مناديب بعد — ابدأ بإعداد الهيكل التشغيلي'
      : 'No riders yet — start by setting up your operating structure';
  }
  if (highSeverityCount > 0) {
    statusClass = 'danger';
    statusText = isAr 
      ? `تنبيه: يوجد ${highSeverityCount} استثناءات تشغيلية حرجة بحاجة لتدخل فوري`
      : `Alert: There are ${highSeverityCount} critical operational exceptions requiring immediate attention`;
  } else if (attentionItems.length > 0) {
    statusClass = 'warning';
    statusText = isAr
      ? `يوجد ${attentionItems.length} حالات تشغيلية تتطلب المتابعة`
      : `There are ${attentionItems.length} operational cases requiring follow-up`;
  }

  wrap.append(el('div', { class: 'ops-status-bar' }, [
    el('div', { class: 'ops-status-pill' }, [
      el('span', { class: `ops-status-dot ${statusClass}` }),
      el('span', { text: statusText }),
    ]),
    el('div', { class: 'ops-status-meta' }, [
      el('span', { text: `${isAr ? '📅 الفترة: ' : '📅 Period: '}${dateStr}` }),
      el('span', { text: `${isAr ? '⏱️ آخر تحديث: ' : '⏱️ Last update: '}${timeStr}` }),
    ]),
  ]));

  // The product knew the order all along — contract, branch, supervisor, rider,
  // sheet, payroll — and never said it. A new company met nine screens of zeros
  // and an invitation to "ask a smart question" about a fleet that did not
  // exist. This is the ten minutes that decide whether a trial becomes a
  // customer, so it says what to do, in order, with the door for each step.
  if (fleetSize === 0) {
    wrap.append(renderFirstRunGuide(overview, isAr));
  }

// 2. Contextual Quick Intelligent Prompt Chips
  const promptBar = aiPromptBar(getContextualPrompts('commandCenter'), (prompt) => {
    openAIDrawer(prompt);
  });
  if (promptBar) wrap.append(promptBar);

  // 3. MASTER PLAN & HR QUICK LAUNCHPAD
  wrap.append(el('div', { class: 'card', style: 'background: linear-gradient(135deg, rgba(37,99,235,0.06) 0%, rgba(124,58,237,0.08) 100%); border: 1px solid rgba(124,58,237,0.25); margin-bottom: 22px; padding: 18px 22px;' }, [
    el('div', { style: 'display:flex; justify-content:space-between; align-items:center; margin-bottom: 14px; flex-wrap:wrap; gap:8px;' }, [
      el('div', { style: 'display:flex; align-items:center; gap:10px;' }, [
        el('span', { style: 'font-size:22px;' }, '🚀'),
        el('h3', { style: 'margin:0; font-size:16px; font-weight:800; color:var(--text);' }, isAr ? 'مركز إطلاق ميزات DOU التشغيلية والمالية' : 'DOU Operational & Financial Launchpad'),
        el('span', { class: 'badge badge-green', style: 'font-size:11px;' }, isAr ? 'جاهزة ومكتملة 100%' : '100% Ready & Live'),
      ]),
      el('span', { style: 'font-size:12px; color:var(--muted); font-weight:600;' }, isAr ? 'الوصول المباشر بنقرة واحدة لجميع مسارات العمليات' : 'One-click direct access to all operational workflows'),
    ]),
    el('div', { style: 'display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px;' }, [
      // Card 1: Bulk Ingestion
      el('div', { class: 'card', style: 'margin:0; padding:14px; cursor:pointer; border:1px solid var(--border); transition:transform 0.15s, border-color 0.15s; background:var(--card)', onclick: () => { go('riders'); setTimeout(() => { const btn = document.getElementById('btn-bulk-import'); if (btn) btn.click(); }, 300); } }, [
        el('div', { style: 'display:flex; align-items:center; gap:8px; margin-bottom:6px;' }, [
          el('span', { style: 'font-size:20px;' }, '📥'),
          el('b', { style: 'font-size:13px; color:var(--text);' }, isAr ? 'الاستيراد الجماعي وقوالب CSV' : 'Bulk Ingestion & CSV Templates'),
        ]),
        el('p', { style: 'font-size:12px; color:var(--muted); margin:0 0 8px 0; line-height:1.4;' }, isAr ? 'تنزيل قوالب السائقين والأداء، ومعاينة الملفات وفحص البصمة SHA-256.' : 'Download driver and performance templates, preview files, and verify SHA-256 checksums.'),
        el('div', { style: 'font-size:11px; font-weight:700; color:var(--primary);' }, isAr ? 'فتح نافذة الاستيراد ➔' : 'Open Import Window ➔'),
      ]),
      // Card 2: Payroll Ledger
      el('div', { class: 'card', style: 'margin:0; padding:14px; cursor:pointer; border:1px solid var(--border); transition:transform 0.15s, border-color 0.15s; background:var(--card)', onclick: () => go('payroll') }, [
        el('div', { style: 'display:flex; align-items:center; gap:8px; margin-bottom:6px;' }, [
          el('span', { style: 'font-size:20px;' }, '💰'),
          el('b', { style: 'font-size:13px; color:var(--text);' }, isAr ? 'كشف الرواتب والسلف والمخالفات' : 'Payroll, Advances & Deductions Ledger'),
        ]),
        el('p', { style: 'font-size:12px; color:var(--muted); margin:0 0 8px 0; line-height:1.4;' }, isAr ? 'احتساب الرواتب التلقائي، السلف، خطط البونص، وإقفال الشهر المعتمد.' : 'Automated payroll calculation, advances, bonus plans, and approved month closing.'),
        el('div', { style: 'font-size:11px; font-weight:700; color:var(--primary);' }, isAr ? 'فتح كشف الرواتب ➔' : 'Open Payroll Ledger ➔'),
      ]),
      // Card 3: Platform Delivery Facts (19 KPIs)
      el('div', { class: 'card', style: 'margin:0; padding:14px; cursor:pointer; border:1px solid var(--border); transition:transform 0.15s, border-color 0.15s; background:var(--card)', onclick: () => go('reports') }, [
        el('div', { style: 'display:flex; align-items:center; gap:8px; margin-bottom:6px;' }, [
          el('span', { style: 'font-size:20px;' }, '🛵'),
          el('b', { style: 'font-size:13px; color:var(--text);' }, isAr ? 'تحليل تقارير المنصات (19 مؤشر)' : 'Platform Reports Analysis (19 KPIs)'),
        ]),
        el('p', { style: 'font-size:12px; color:var(--muted); margin:0 0 8px 0; line-height:1.4;' }, isAr ? 'قمع التوصيل، استغلال الساعات، الأوردرات المجمعة، وسجلات شهر كامل.' : 'Delivery funnel, hour utilization, batched orders, and full-month logs.'),
        el('div', { style: 'font-size:11px; font-weight:700; color:var(--primary);' }, isAr ? 'استعراض تحليل الأداء ➔' : 'View Performance Analysis ➔'),
      ]),
      // Card 4: Readiness & Driver 360
      el('div', { class: 'card', style: 'margin:0; padding:14px; cursor:pointer; border:1px solid var(--border); transition:transform 0.15s, border-color 0.15s; background:var(--card)', onclick: () => go('riders') }, [
        el('div', { style: 'display:flex; align-items:center; gap:8px; margin-bottom:6px;' }, [
          el('span', { style: 'font-size:20px;' }, '🚦'),
          el('b', { style: 'font-size:13px; color:var(--text);' }, isAr ? 'محرك الجاهزية وإسناد المركبات' : 'Readiness Engine & Vehicle Assignment'),
        ]),
        el('p', { style: 'font-size:12px; color:var(--muted); margin:0 0 8px 0; line-height:1.4;' }, isAr ? 'تقييم الأبعاد الـ 8، تفعيل السائق، وإسناد المركبات والورديات.' : '8-dimension assessment, driver activation, and vehicle/shift assignment.'),
        el('div', { style: 'font-size:11px; font-weight:700; color:var(--primary);' }, isAr ? 'فتح ملف السائق 360 ➔' : 'Open Driver 360 Profile ➔'),
      ]),
      // Card 5: DOU AI & Advanced Reports
      el('div', { class: 'card', style: 'margin:0; padding:14px; cursor:pointer; border:1px solid var(--border); transition:transform 0.15s, border-color 0.15s; background:var(--card)', onclick: () => go('reports') }, [
        el('div', { style: 'display:flex; align-items:center; gap:8px; margin-bottom:6px;' }, [
          el('span', { style: 'font-size:20px;' }, '📊'),
          el('b', { style: 'font-size:13px; color:var(--text);' }, isAr ? 'لوحات DOU AI الذكية وكتالوج 31 تقرير' : 'DOU AI Dashboards & 31-Report Catalog'),
        ]),
        el('p', { style: 'font-size:12px; color:var(--muted); margin:0 0 8px 0; line-height:1.4;' }, isAr ? 'تضمين لوحات DOU AI المشفرة بـ JWT، وتصدير CSV لكافة المجالات.' : 'Embedded JWT-signed DOU AI dashboards and CSV export across all domains.'),
        el('div', { style: 'font-size:11px; font-weight:700; color:var(--primary);' }, isAr ? 'استعراض التقارير ➔' : 'Explore Reports ➔'),
      ]),
      // Card 6: Needs Attention Queue
      el('div', { class: 'card', style: 'margin:0; padding:14px; cursor:pointer; border:1px solid var(--border); transition:transform 0.15s, border-color 0.15s; background:var(--card)', onclick: () => go('needsAttention') }, [
        el('div', { style: 'display:flex; align-items:center; gap:8px; margin-bottom:6px;' }, [
          el('span', { style: 'font-size:20px;' }, '⚡'),
          el('b', { style: 'font-size:13px; color:var(--text);' }, isAr ? 'طابور استثناءات يحتاج انتباه' : 'Needs Attention Exceptions Queue'),
        ]),
        el('p', { style: 'font-size:12px; color:var(--muted); margin:0 0 8px 0; line-height:1.4;' }, isAr ? 'رصد حتمي مباشر للغياب، الوثائق المنتهية، عجز السعة، وروابط الحل السريع.' : 'Deterministic monitoring of absences, expired docs, capacity deficits, and quick-fix links.'),
        el('div', { style: 'font-size:11px; font-weight:700; color:var(--primary);' }, isAr ? 'معالجة الاستثناءات ➔' : 'Resolve Exceptions ➔'),
      ]),
    ]),
  ]));

  // 4. Clickable KPI Metrics Groups
  // Group 1: Workforce & Active Attendance
  wrap.append(el('div', { style: 'margin-bottom:8px;font-size:12px;font-weight:700;color:var(--muted)' }, isAr ? 'القوى العاملة والحضور اللحظي' : 'Workforce & Real-time Attendance'));
  wrap.append(el('div', { class: 'cards' }, [
    metricCard(overview.couriers_total, isAr ? 'إجمالي السائقين' : 'Total Drivers', 'blue', () => go('riders'), isAr ? 'استعراض الفريق' : 'View Team'),
    metricCard(overview.couriers_online, isAr ? 'متصلون الآن' : 'Online Now', 'trend', () => go('riders'), isAr ? 'جاهزية الاتصال' : 'Online Readiness'),
    metricCard(overview.shifts_running, isAr ? 'نشطون بالورديات' : 'Active in Shifts', 'trend', () => go('shifts'), isAr ? 'مسندون لورديات' : 'Assigned to Shifts'),
    metricCard(overview.absent_today, isAr ? 'غائبون اليوم' : 'Absent Today', 'alert', () => go('shifts'), isAr ? 'مراجعة الحضور' : 'Review Attendance'),
    metricCard(overview.present_today, isAr ? 'حاضرون اليوم' : 'Present Today', 'trend', () => go('shifts'), isAr ? 'حضور مؤكد' : 'Confirmed Present'),
  ]));

  // Group 2: Operational Readiness & Leaves
  wrap.append(el('div', { style: 'margin-bottom:8px;font-size:12px;font-weight:700;color:var(--muted)' }, isAr ? 'الجاهزية التشغيلية والإجازات' : 'Operational Readiness & Leaves'));
  wrap.append(el('div', { class: 'cards' }, [
    metricCard(Math.max((overview.couriers_total || 0) - (overview.not_ready || 0), 0), isAr ? 'جاهز للعمل' : 'Operationally Ready', 'trend', () => go('riders'), isAr ? 'مكتمل الوثائق والمركبة' : 'Valid Docs & Vehicle'),
    metricCard(overview.not_ready, isAr ? 'غير جاهز' : 'Not Ready', 'alert', () => go('riders'), isAr ? 'يوجد موانع تشغيلية' : 'Operational Blockers'),
    metricCard(overview.on_leave, isAr ? 'في إجازة معتمدة' : 'On Approved Leave', 'blue', () => go('shifts'), isAr ? 'إجازة سارية' : 'Active Leave'),
    metricCard(overview.pending_leaves, isAr ? 'إجازات معلّقة' : 'Pending Leaves', overview.pending_leaves > 0 ? 'alert' : 'blue', () => go('shifts'), isAr ? 'طابور الاعتمادات' : 'Approvals Queue'),
  ]));

  // Group 3: Document Compliance
  wrap.append(el('div', { style: 'margin-bottom:8px;font-size:12px;font-weight:700;color:var(--muted)' }, isAr ? 'امتثال الوثائق والمستندات' : 'Document Compliance'));
  wrap.append(el('div', { class: 'cards' }, [
    metricCard(overview.documents_expired, isAr ? '🔴 مستندات منتهية' : '🔴 Expired Documents', 'alert', () => go('needsAttention'), isAr ? 'تحتاج تجديد فوري' : 'Needs Immediate Renewal'),
    metricCard(overview.documents_30, isAr ? '🟠 تنتهي خلال 30 يوم' : '🟠 Expiring in 30 Days', 'warning', () => go('needsAttention'), isAr ? 'تنبيه استباقي' : 'Proactive Alert'),
    metricCard(overview.documents_60, isAr ? '🟡 تنتهي خلال 60 يوم' : '🟡 Expiring in 60 Days', 'blue', () => go('needsAttention'), isAr ? 'متابعة دورية' : 'Regular Follow-up'),
  ]));

  // 5. Prioritized Action Queue
  wrap.append(el('div', { style: 'margin:24px 0 12px 0;display:flex;justify-content:space-between;align-items:center' }, [
    el('h3', { style: 'margin:0;font-size:16px' }, isAr ? '⚡ أهم الإجراءات المطلوبة الآن' : '⚡ Top Priority Actions Now'),
    badge(isAr ? `${attentionItems.length} إجراء` : `${attentionItems.length} Actions`, attentionItems.length > 0 ? 'amber' : 'green'),
  ]));

  if (!attentionItems.length) {
    wrap.append(emptyState(isAr ? 'لا توجد إجراءات تشغيلية معلقة حالياً — الأسطول في حالة ممتازة.' : 'No pending operational actions — fleet is running optimally.'));
  } else {
    attentionItems.slice(0, 5).forEach((item) => {
      wrap.append(priorityActionCard({
        title: isAr ? (item.title_ar || item.title || item.signal) : (item.title_en || item.title || item.title_ar || item.signal),
        description: isAr ? (item.description_ar || item.description || '') : (item.description_en || item.description || ''),
        severity: item.severity,
        count: item.count,
        actionLabel: isAr ? 'معالجة ➔' : 'Resolve ➔',
        onAction: () => {
          if (item.signal.includes('DOC') || item.signal.includes('EXPIRED')) {
            go('needsAttention');
          } else if (item.signal.includes('ABSENCE') || item.signal.includes('SHIFT') || item.signal.includes('LEAVE')) {
            go('shifts');
          } else {
            go('riders');
          }
        }
      }));
    });
  }

  return wrap;
}
