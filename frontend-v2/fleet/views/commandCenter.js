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
      api.get('/fleet/overview'),
      api.get('/analytics/needs-attention/deterministic'),
    ]);
    state.replaceWith(renderDashboard(overview, needsAttention));
  } catch (e) {
    state.replaceWith(errorState(
      (isAr ? 'تعذر تحميل بيانات مركز القيادة والعمليات — تحقق من الاتصال بالخادم وأعد المحاولة: ' : 'Failed to load Command Center data — check server connection and retry: ') + (e.message || ''),
      () => loadCommandCenter(container)
    ));
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
  const timeStr = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
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

  // 3. Prioritized Action Queue — Operational Actions First
  wrap.append(el('div', { style: 'margin:20px 0 12px 0;display:flex;justify-content:space-between;align-items:center' }, [
    el('h3', { style: 'margin:0;font-size:16px;font-weight:800;color:var(--text)' }, isAr ? '⚡ أهم الإجراءات المطلوبة الآن' : '⚡ Top Priority Actions Now'),
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
          if (item.signal === 'pending_attendance_corrections') {
            window.__shiftsInitialTab = 'corrections';
            go('shifts');
          } else if (item.signal === 'overtime') {
            window.__shiftsInitialTab = 'overtime';
            go('shifts');
          } else if (item.signal === 'absent_riders') {
            window.__shiftsInitialTab = 'attendance';
            go('shifts');
          } else if (item.signal === 'capacity_shortage') {
            go('capacity');
          } else if (item.signal === 'below_target') {
            go('reports');
          } else if (item.signal === 'incomplete_onboarding') {
            go('riders');
          } else if (item.signal.includes('DOC') || item.signal.includes('EXPIRED') || item.signal === 'expiring_documents') {
            go('needsAttention');
          } else {
            go('needsAttention');
          }
        }
      }));
    });
  }

  // 4. Clickable KPI Metrics Groups
  // Group 1: Workforce & Active Attendance
  wrap.append(el('div', { style: 'margin:24px 0 8px 0;font-size:12px;font-weight:700;color:var(--muted)' }, isAr ? 'القوى العاملة والحضور اللحظي' : 'Workforce & Real-time Attendance'));
  wrap.append(el('div', { class: 'cards' }, [
    metricCard(overview.couriers_total, isAr ? 'إجمالي السائقين' : 'Total Drivers', 'blue', () => go('riders'), isAr ? 'استعراض الفريق' : 'View Team'),
    metricCard(overview.couriers_online, isAr ? 'متصلون الآن' : 'Online Now', 'trend', () => go('riders'), isAr ? 'جاهزية الاتصال' : 'Online Readiness'),
    metricCard(overview.shifts_running, isAr ? 'نشطون بالورديات' : 'Active in Shifts', 'trend', () => go('shifts'), isAr ? 'مسندون لورديات' : 'Assigned to Shifts'),
    metricCard(overview.absent_today, isAr ? 'غائبون اليوم' : 'Absent Today', 'alert', () => { window.__shiftsInitialTab = 'attendance'; go('shifts'); }, isAr ? 'مراجعة الحضور' : 'Review Attendance'),
    metricCard(overview.present_today, isAr ? 'حاضرون اليوم' : 'Present Today', 'trend', () => { window.__shiftsInitialTab = 'attendance'; go('shifts'); }, isAr ? 'حضور مؤكد' : 'Confirmed Present'),
  ]));

  // Group 2: Operational Readiness & Leaves
  wrap.append(el('div', { style: 'margin-bottom:8px;font-size:12px;font-weight:700;color:var(--muted)' }, isAr ? 'الجاهزية التشغيلية والإجازات' : 'Operational Readiness & Leaves'));
  wrap.append(el('div', { class: 'cards' }, [
    metricCard(Math.max((overview.couriers_total || 0) - (overview.not_ready || 0), 0), isAr ? 'جاهز للعمل' : 'Operationally Ready', 'trend', () => go('riders'), isAr ? 'مكتمل الوثائق والمركبة' : 'Valid Docs & Vehicle'),
    metricCard(overview.not_ready, isAr ? 'غير جاهز' : 'Not Ready', 'alert', () => go('riders'), isAr ? 'يوجد موانع تشغيلية' : 'Operational Blockers'),
    metricCard(overview.on_leave, isAr ? 'في إجازة معتمدة' : 'On Approved Leave', 'blue', () => { window.__shiftsInitialTab = 'leaves'; go('shifts'); }, isAr ? 'إجازة سارية' : 'Active Leave'),
    metricCard(overview.pending_leaves, isAr ? 'إجازات معلّقة' : 'Pending Leaves', overview.pending_leaves > 0 ? 'alert' : 'blue', () => { window.__shiftsInitialTab = 'leaves'; go('shifts'); }, isAr ? 'طابور الاعتمادات' : 'Approvals Queue'),
  ]));

  // Group 3: Document Compliance
  wrap.append(el('div', { style: 'margin-bottom:8px;font-size:12px;font-weight:700;color:var(--muted)' }, isAr ? 'امتثال الوثائق والمستندات' : 'Document Compliance'));
  wrap.append(el('div', { class: 'cards' }, [
    metricCard(overview.documents_expired, isAr ? '🔴 مستندات منتهية' : '🔴 Expired Documents', 'alert', () => go('needsAttention'), isAr ? 'تحتاج تجديد فوري' : 'Needs Immediate Renewal'),
    metricCard(overview.documents_30, isAr ? '🟠 تنتهي خلال 30 يوم' : '🟠 Expiring in 30 Days', 'warning', () => go('needsAttention'), isAr ? 'تنبيه استباقي' : 'Proactive Alert'),
    metricCard(overview.documents_60, isAr ? '🟡 تنتهي خلال 60 يوم' : '🟡 Expiring in 60 Days', 'blue', () => go('needsAttention'), isAr ? 'متابعة دورية' : 'Regular Follow-up'),
  ]));

  return wrap;
}
