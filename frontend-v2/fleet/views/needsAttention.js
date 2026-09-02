// Needs Attention screen — intelligent action queue with contextual guidance and deep links
import { api } from '../../shared/api/client.js';
import { el, loadingState, emptyState, errorState, metricCard, badge, aiPromptBar, priorityActionCard } from '../../shared/components/ui.js';
import { go, openAIDrawer, getContextualPrompts } from '../shell.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

const ROUTES_AR = {
  capacity_shortage: { view: 'capacity', label: 'تخطيط السعة ➔' },
  absent_riders: { view: 'shifts', subtab: 'attendance', label: 'سجل الحضور ➔' },
  below_target: { view: 'reports', label: 'تقرير الأداء ➔' },
  incomplete_onboarding: { view: 'riders', label: 'ملف السائقين ➔' },
  expiring_documents: { view: 'riders', label: 'مراجعة الوثائق ➔' },
  pending_attendance_corrections: { view: 'shifts', subtab: 'corrections', label: 'طابور التصحيحات ➔' },
  unassigned_platform_riders: { view: 'riders', label: 'توزيع المناديب ➔' },
  pending_b2b_settlements: { view: 'capacity', label: 'تسويات المشغلين ➔' },
};

const ROUTES_EN = {
  capacity_shortage: { view: 'capacity', label: 'Capacity Planning ➔' },
  absent_riders: { view: 'shifts', subtab: 'attendance', label: 'Attendance Log ➔' },
  below_target: { view: 'reports', label: 'Performance Report ➔' },
  incomplete_onboarding: { view: 'riders', label: 'Driver Profiles ➔' },
  expiring_documents: { view: 'riders', label: 'Review Documents ➔' },
  pending_attendance_corrections: { view: 'shifts', subtab: 'corrections', label: 'Corrections Queue ➔' },
  unassigned_platform_riders: { view: 'riders', label: 'Driver Distribution ➔' },
  pending_b2b_settlements: { view: 'capacity', label: 'Operator Settlements ➔' },
};

const ACTION_EXPLANATIONS_AR = {
  capacity_shortage: 'يوجد عجز في السعة مقارنة بطلب المنصات. افتح تخطيط السعة لإعادة جدولة وتوزيع الورديات.',
  absent_riders: 'تم تسجيل غياب لسائقين مسندين لورديات نشطة اليوم. افتح شاشة الحضور للتواصل مع المشرف وتعيين بدلاء.',
  below_target: 'أداء السائق أقل من المستهدف المعتمد. افتح تقرير الأداء لمراجعة معدل القبول والإكمال.',
  incomplete_onboarding: 'سائقون بانتظار استكمال الوثائق أو المركبة لبدء العمل التشغيلي.',
  expiring_documents: 'وثائق قاربت على الانتهاء تتطلب التواصل مع السائق للتحديث قبل التعطيل الآلي.',
  pending_attendance_corrections: 'طلبات تصحيح أوقات الدخول والخروج بانتظار الاعتماد قبل إقفال مسير الرواتب.',
  unassigned_platform_riders: 'سائقون نشطون على المنصة دون إسناد لشركة تشغيل (3PL). عيّن المشغل المسؤول لتفعيل النطاق.',
  pending_b2b_settlements: 'تسويات مالية شهرية لشركات التشغيل محسوبة وبانتظار المراجعة والاعتماد النهائي.',
};

const ACTION_EXPLANATIONS_EN = {
  capacity_shortage: 'Capacity shortage detected compared to platform demand. Open Capacity Planning to reschedule and balance shift capacity.',
  absent_riders: 'Absence recorded for drivers assigned to active shifts today. Open Attendance to contact supervisor and assign replacements.',
  below_target: 'Driver performance is below target. Open Performance Report to review acceptance and completion rates.',
  incomplete_onboarding: 'Drivers awaiting document completion or vehicle assignment to begin operational shifts.',
  expiring_documents: 'Critical documents expiring soon requiring follow-up before automated suspension.',
  pending_attendance_corrections: 'Check-in/out correction requests pending approval before payroll cutoff.',
  unassigned_platform_riders: 'Active drivers without 3PL operator assignment. Assign responsible operator to activate scope.',
  pending_b2b_settlements: 'Monthly 3PL operator financial settlements calculated and pending final review and approval.',
};

const TITLES_EN = {
  capacity_shortage: 'Shift Capacity Deficit',
  absent_riders: 'Absent Drivers on Active Shifts',
  below_target: 'Drivers Below Target',
  incomplete_onboarding: 'Incomplete Onboarding Drivers',
  expiring_documents: 'Expiring Documents',
  pending_attendance_corrections: 'Pending Attendance Corrections',
  unassigned_platform_riders: 'Unassigned Platform Drivers',
  pending_b2b_settlements: 'Pending 3PL Settlements',
};

function handleActionNavigation(signal) {
  const isAr = getLang() === 'ar';
  const routes = isAr ? ROUTES_AR : ROUTES_EN;
  const route = routes[signal];
  if (!route) { go('commandCenter'); return; }
  if (route.subtab && route.view === 'shifts') {
    window.__shiftsInitialTab = route.subtab;
  }
  go(route.view);
}

export async function loadNeedsAttention(container) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'الاستثناءات التشغيلية الميدانية' : 'Field Operational Exceptions'),
      el('h1', { text: isAr ? '⚠️ يحتاج انتباه' : '⚠️ Needs Attention Queue' })
    ]),
    el('div', { class: 'header-actions' }, [
      el('button', { class: 'btn btn-ghost', onclick: () => loadNeedsAttention(container) }, isAr ? '↻ تحديث' : '↻ Refresh'),
      el('button', { class: 'btn btn-ai', onclick: () => openAIDrawer(isAr ? 'ما الذي يحتاج انتباهي اليوم؟' : 'What needs my attention today?') }, [
        el('span', { text: '✨' }),
        el('span', { text: isAr ? 'تحليل الاستثناءات' : 'Analyze Exceptions' })
      ]),
    ]),
  ]));

  // AI Prompt Chips
  const promptBar = aiPromptBar(getContextualPrompts('needsAttention'), (p) => openAIDrawer(p));
  if (promptBar) container.append(promptBar);

  const list = el('div', {}, [loadingState(isAr ? 'جاري تحليل وتجميع الإشارات التشغيلية...' : 'Analyzing and aggregating operational signals...')]);
  container.append(list);

  try {
    const data = await api.get('/analytics/needs-attention/deterministic');
    const items = data.items || [];
    list.innerHTML = '';

    const highCount = items.filter(i => i.severity === 'high').length;
    const mediumCount = items.filter(i => i.severity === 'medium').length;
    const lowCount = items.filter(i => i.severity === 'low' || !i.severity).length;

    list.append(el('div', { class: 'cards' }, [
      metricCard(data.total || 0, isAr ? 'إجمالي الإشارات المفتوحة' : 'Total Open Signals', 'alert', null, isAr ? 'استثناءات نشطة' : 'Active Exceptions'),
      metricCard(highCount, isAr ? 'حالات حرجة وعاجلة' : 'Critical & Urgent', 'alert', null, isAr ? 'تتطلب إجراءً فورياً' : 'Requires Immediate Action'),
      metricCard(mediumCount, isAr ? 'حالات متابعة متوسطة' : 'Medium Follow-ups', 'warning', null, isAr ? 'قبل تفاقم الأثر' : 'Prevent Impact Escalation'),
      metricCard(lowCount, isAr ? 'تنبيهات استباقية' : 'Proactive Alerts', 'blue', null, isAr ? 'متابعة دورية' : 'Regular Follow-up'),
    ]));

    if (!items.length) {
      list.append(emptyState(isAr ? '✅ لا توجد استثناءات تشغيلية مفتوحة — جميع العمليات ضمن النطاق المستهدف.' : '✅ No open operational exceptions — all operations are within target thresholds.'));
      return;
    }

    // Sort: High severity first
    const sorted = [...items].sort((a, b) => {
      const weights = { high: 3, medium: 2, low: 1 };
      return (weights[b.severity] || 0) - (weights[a.severity] || 0);
    });

    const routes = isAr ? ROUTES_AR : ROUTES_EN;
    const explanations = isAr ? ACTION_EXPLANATIONS_AR : ACTION_EXPLANATIONS_EN;

    list.append(el('div', { class: 'card' }, [
      el('h3', {}, [
        el('span', { text: isAr ? 'قائمة الاستثناءات المفتوحة ومسارات المعالجة' : 'Open Exceptions Queue & Remediation Pathways' }),
        el('span', { class: 'badge badge-red', style: isAr ? 'margin-right:8px' : 'margin-left:8px' }, isAr ? `${sorted.length} استثناء` : `${sorted.length} Exceptions`)
      ]),
      ...sorted.map((item) => {
        const route = routes[item.signal] || { label: isAr ? 'فتح التفاصيل ➔' : 'View Details ➔' };
        const desc = explanations[item.signal] || item.signal;
        const title = isAr ? (item.title_ar || item.title || item.signal) : (TITLES_EN[item.signal] || item.title_en || item.title || item.title_ar);
        return priorityActionCard({
          title,
          description: desc,
          severity: item.severity,
          count: item.count,
          actionLabel: route.label,
          onAction: () => handleActionNavigation(item.signal)
        });
      })
    ]));
  } catch (e) {
    list.replaceWith(errorState((isAr ? 'تعذر التحميل: ' : 'Failed to load: ') + e.message, () => loadNeedsAttention(container)));
  }
}
