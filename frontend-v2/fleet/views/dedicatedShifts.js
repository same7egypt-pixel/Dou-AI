// Dedicated Restaurant Shifts (DOU Flex) & Logistics Company Settlements
import { api } from '../../shared/api/client.js';
import {
  el, loadingState, emptyState, errorState, table, button, escapeHtml,
  modal, metricCard, badge, showToast } from '../../shared/components/ui.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

let currentSubTab = 'contracts'; // 'contracts' | 'settlement'

export async function loadDedicatedShifts(container, tabOverride = null) {
  const isAr = getLang() === 'ar';
  if (tabOverride) currentSubTab = tabOverride;

  container.innerHTML = '';

  const headerActions = el('div', { style: 'display:flex;gap:8px;align-items:center' }, [
    el('button', {
      class: 'btn btn-ghost btn-small',
      onclick: () => loadDedicatedShifts(container, currentSubTab)
    }, isAr ? 'تحديث ↻' : 'Refresh ↻')
  ]);

  const header = el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'عقود المطاعم ونظام الورديات المخصصة' : 'Restaurant Contracts & Dedicated Shifts'),
      el('h1', { text: isAr ? 'عقود المطاعم (DOU Flex)' : 'Restaurant Shifts (DOU Flex)' }),
    ]),
    headerActions,
  ]);

  const tabsNav = el('div', { class: 'tabs', style: 'margin-bottom:16px' }, [
    el('button', {
      class: `tab ${currentSubTab === 'contracts' ? 'active' : ''}`,
      onclick: () => { currentSubTab = 'contracts'; renderContent(contentArea, container); }
    }, isAr ? '🏬 عقود الفروع والمناديب' : '🏬 Branch Contracts & Riders'),
    el('button', {
      class: `tab ${currentSubTab === 'settlement' ? 'active' : ''}`,
      onclick: () => { currentSubTab = 'settlement'; renderContent(contentArea, container); }
    }, isAr ? '💰 المقاصة والمستحقات الشهرية' : '💰 Monthly Settlements'),
  ]);

  const contentArea = el('div', { id: 'dedicated-shifts-content' });
  container.append(header, tabsNav, contentArea);

  renderContent(contentArea, container);
}

async function renderContent(contentArea, mainContainer) {
  const isAr = getLang() === 'ar';
  contentArea.innerHTML = '';
  contentArea.append(loadingState(isAr ? 'جاري تحميل بيانات عقود المطاعم…' : 'Loading restaurant contracts…'));

  try {
    if (currentSubTab === 'contracts') {
      await renderContractsView(contentArea, mainContainer);
    } else {
      await renderSettlementsView(contentArea);
    }
  } catch (err) {
    contentArea.innerHTML = '';
    contentArea.append(errorState(err.message || (isAr ? 'فشل تحميل البيانات' : 'Failed to load data'), () => renderContent(contentArea, mainContainer)));
  }
}

async function renderContractsView(contentArea, mainContainer) {
  const isAr = getLang() === 'ar';
  const bookings = await api.get('/fleet/dedicated/bookings');

  contentArea.innerHTML = '';

  if (!bookings || !bookings.length) {
    contentArea.append(emptyState(
      isAr ? 'لا توجد عقود ورديات مطاعم مسندة لشركتكم حالياً.' : 'No dedicated restaurant shifts assigned to your fleet yet.'
    ));
    return;
  }

  // Calculate high-level KPIs
  const activeCount = bookings.filter(b => b.status === 'active').length;
  const assignedRidersCount = bookings.filter(b => b.rider && b.rider.rider_id).length;
  const totalMonthlyPayout = bookings
    .filter(b => b.status === 'active')
    .reduce((sum, b) => sum + (b.monthly_payout || 0), 0);
  const totalTodayOrders = bookings.reduce((sum, b) => sum + (b.today_orders_count || 0), 0);

  const metricsGrid = el('div', { class: 'metrics-grid', style: 'margin-bottom:20px' }, [
    metricCard(activeCount, isAr ? 'عقود الفروع النشطة' : 'Active Branch Contracts', 'blue'),
    metricCard(assignedRidersCount, isAr ? 'المناديب المسكنون' : 'Assigned Riders', 'green'),
    metricCard(`${totalMonthlyPayout.toLocaleString()} ${isAr ? 'ر.س' : 'SAR'}`, isAr ? 'إجمالي مستحقات الورديات من DOU' : 'Monthly Payout from DOU', 'purple'),
    metricCard(`${totalTodayOrders.toLocaleString()}`, isAr ? 'طلبات الفروع اليوم' : 'Today Branch Orders', 'amber'),
  ]);

  const cardsContainer = el('div', { style: 'display:grid;grid-template-columns:repeat(auto-fill, minmax(360px, 1fr));gap:16px' });

  bookings.forEach((b) => {
    const isPeak = b.shift_type === 'peak_3h';
    const shiftBadge = isPeak
      ? el('span', { class: 'badge badge-amber', style: 'font-weight:700' }, isAr ? '⚡ ذروة 3 ساعات' : '⚡ Peak 3h')
      : el('span', { class: 'badge badge-blue', style: 'font-weight:700' }, isAr ? '🌟 يومي 8 ساعات' : '🌟 Full Day 8h');

    let attendanceBadge;
    if (b.today_attendance.checkin_status === 'checked_in') {
      attendanceBadge = el('span', { class: 'badge badge-green' }, isAr ? '🟢 حاضر بالفرع' : '🟢 Checked In');
    } else if (b.today_attendance.checkin_status === 'completed') {
      attendanceBadge = el('span', { class: 'badge badge-gray' }, isAr ? '🏁 أنهى الوردية' : '🏁 Completed');
    } else {
      attendanceBadge = el('span', { class: 'badge badge-red' }, isAr ? '⚪ لم يحضر اليوم' : '⚪ Not Checked In');
    }

    const riderName = b.rider ? b.rider.name : (isAr ? '⚠️ غير مسند مندوب' : '⚠️ No rider assigned');
    const riderPhone = b.rider ? b.rider.phone || '—' : '—';

    const card = el('div', { class: 'card', style: 'background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;display:flex;flex-direction:column;justify-content:space-between' }, [
      el('div', {}, [
        el('div', { style: 'display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px' }, [
          el('div', {}, [
            el('h3', { style: 'margin:0 0 4px;font-size:16px;font-weight:800;color:var(--ink)' }, `🏬 ${b.merchant_name}`),
            el('div', { style: 'font-size:12px;color:var(--muted)' }, `📍 ${b.branch_name} — ${b.branch_city}`),
          ]),
          shiftBadge,
        ]),

        el('div', { style: 'background:var(--surface2, #f8fafc);border-radius:8px;padding:10px;margin:12px 0;font-size:12px;line-height:1.7' }, [
          el('div', { style: 'display:flex;justify-content:space-between' }, [
            el('span', { style: 'color:var(--muted)' }, isAr ? '⏰ مواعيد الوردية:' : '⏰ Shift Hours:'),
            el('b', {}, `${b.shift_start} — ${b.shift_end}`),
          ]),
          el('div', { style: 'display:flex;justify-content:space-between' }, [
            el('span', { style: 'color:var(--muted)' }, isAr ? '💵 دخل شركتكم الشهري من DOU:' : '💵 Monthly Payout from DOU:'),
            el('b', { style: 'color:var(--ink);font-weight:800' }, `${(b.monthly_payout || 0).toLocaleString()} ${isAr ? 'ر.س' : 'SAR'}`),
          ]),
          el('div', { style: 'display:flex;justify-content:space-between;align-items:center' }, [
            el('span', { style: 'color:var(--muted)' }, isAr ? 'حضور اليوم:' : 'Today Attendance:'),
            attendanceBadge,
          ]),
          el('div', { style: 'display:flex;justify-content:space-between' }, [
            el('span', { style: 'color:var(--muted)' }, isAr ? 'طلبات المطعم اليوم:' : 'Today Orders:'),
            el('b', {}, `${b.today_orders_count} ${isAr ? 'طلب مسلم' : 'delivered'}`),
          ]),
        ]),

        el('div', { style: 'border-top:1px dashed var(--border);padding-top:10px;margin-bottom:12px' }, [
          el('div', { style: 'font-size:11px;color:var(--muted);margin-bottom:4px' }, isAr ? 'المندوب المسند للفرع:' : 'Assigned Courier:'),
          el('div', { style: 'display:flex;justify-content:space-between;align-items:center' }, [
            el('b', { style: `font-size:13px;${!b.rider ? 'color:var(--red);' : ''}` }, `🛵 ${riderName}`),
            el('span', { style: 'font-size:12px;color:var(--muted)' }, riderPhone),
          ]),
        ]),
      ]),

      el('div', { style: 'display:flex;gap:8px;margin-top:8px' }, [
        el('button', {
          class: 'btn btn-primary btn-small btn-full',
          onclick: () => openAssignRiderModal(b, mainContainer)
        }, isAr ? 'تعيين / تغيير المندوب 🛵' : 'Assign / Change Rider 🛵')
      ])
    ]);

    cardsContainer.append(card);
  });

  contentArea.append(metricsGrid, cardsContainer);
}

async function openAssignRiderModal(booking, mainContainer) {
  const isAr = getLang() === 'ar';
  const overlay = modal(
    isAr ? `إسناد مندوب لفرع: ${booking.branch_name}` : `Assign Courier to ${booking.branch_name}`,
    loadingState(isAr ? 'جاري جلب قائمة المناديب المتاحين…' : 'Loading eligible couriers…')
  );

  try {
    const riders = await api.get('/fleet/dedicated/eligible-riders');
    overlay.querySelector('.modal-body').innerHTML = '';

    if (!riders || !riders.length) {
      overlay.querySelector('.modal-body').append(emptyState(
        isAr ? 'لا يوجد مناديب نشطين متاحين في شركتكم حالياً.' : 'No active couriers available in your fleet.'
      ));
      return;
    }

    const select = el('select', { class: 'input', style: 'width:100%;margin-bottom:16px;padding:8px 12px' }, [
      el('option', { value: '' }, isAr ? '— اختر مندوباً من القائمة —' : '— Select a courier —'),
      ...riders.map(r => el('option', {
        value: String(r.id),
        selected: booking.rider && booking.rider.rider_id === r.id
      }, `${r.name} (${r.phone || 'بدون هاتف'})`))
    ]);

    const submitBtn = el('button', { class: 'btn btn-primary btn-full' }, isAr ? 'تأكيد إسناد المندوب' : 'Confirm Assignment');
    submitBtn.onclick = async () => {
      const selectedId = Number(select.value);
      if (!selectedId) {
        showToast(isAr ? 'يرجى اختيار مندوب أولاً' : 'Please select a courier first', 'info');
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = isAr ? 'جاري الحفظ…' : 'Saving…';
      try {
        await api.post(`/fleet/dedicated/bookings/${booking.id}/assign-rider`, { rider_id: selectedId });
        overlay.close();
        loadDedicatedShifts(mainContainer, 'contracts');
      } catch (e) {
        showToast(e.message || (isAr ? 'فشل حفظ المندوب' : 'Failed to assign rider'), 'error');
        submitBtn.disabled = false;
        submitBtn.textContent = isAr ? 'تأكيد إسناد المندوب' : 'Confirm Assignment';
      }
    };

    const form = el('div', {}, [
      el('p', { style: 'font-size:13px;color:var(--muted);line-height:1.7;margin-bottom:14px' },
        isAr
          ? `المندوب المختار سيظهر اسمه فوراً لكاشير المطعم في فرع (${booking.branch_name})، وسيتمكن المندوب من تسجيل الحضور بالـ GPS واستلام طلبات الفرع.`
          : `The selected courier will appear on the restaurant cashier portal for ${booking.branch_name} and can check in via GPS and receive orders.`
      ),
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:6px' }, isAr ? 'اختر المندوب المكلف:' : 'Select Courier:'),
      select,
      submitBtn,
    ]);

    overlay.querySelector('.modal-body').append(form);
  } catch (err) {
    overlay.querySelector('.modal-body').innerHTML = '';
    overlay.querySelector('.modal-body').append(errorState(err.message));
  }
}

async function renderSettlementsView(contentArea) {
  const isAr = getLang() === 'ar';
  const now = new Date();
  const monthStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;

  const settlement = await api.get(`/fleet/dedicated/settlement?month=${monthStr}`);

  contentArea.innerHTML = '';

  const kpiRow = el('div', { class: 'metrics-grid', style: 'margin-bottom:20px' }, [
    metricCard(`${Number(settlement.total_payout_due || 0).toLocaleString()} ${settlement.currency}`, isAr ? 'إجمالي المستحقات للتحويل من DOU' : 'Total Payout Due from DOU', 'purple'),
    metricCard(`${settlement.line_items ? settlement.line_items.length : 0}`, isAr ? 'عدد العقود المفوترة' : 'Billed Contracts', 'blue'),
    metricCard(settlement.settlement_month, isAr ? 'شهر المطابقة' : 'Settlement Month', 'amber'),
  ]);

  const columns = [
    { key: 'merchant_name', label: isAr ? 'المطعم' : 'Restaurant' },
    { key: 'branch_name', label: isAr ? 'الفرع' : 'Branch' },
    { key: 'rider_name', label: isAr ? 'المندوب' : 'Rider' },
    {
      key: 'shift_type',
      label: isAr ? 'نوع الوردية' : 'Shift Type',
      render: (val) => val === 'peak_3h' ? (isAr ? 'ذروة 3س' : 'Peak 3h') : (isAr ? 'يومي 8س' : 'Daily 8h')
    },
    { key: 'active_days', label: isAr ? 'الأيام النشطة' : 'Active Days' },
    { key: 'days_in_month', label: isAr ? 'أيام الشهر' : 'Days in Month' },
    {
      key: 'monthly_payout_rate',
      label: isAr ? 'المستحق الشهري المعتمد' : 'Monthly Agreed Rate',
      render: (val) => `${Number(val || 0).toLocaleString()} ${settlement.currency}`
    },
    {
      key: 'prorated_payout',
      label: isAr ? 'المستحق الفعلي للتحويل' : 'Payout Due',
      render: (val) => el('b', { style: 'color:var(--primary, #2563eb)' }, `${Number(val || 0).toLocaleString()} ${settlement.currency}`)
    },
  ];

  const tableEl = table(columns, settlement.line_items || []);

  const statementBox = el('div', { class: 'card', style: 'background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-top:16px' }, [
    el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:16px' }, [
      el('div', {}, [
        el('h2', { style: 'margin:0 0 4px;font-size:18px' }, isAr ? `كشف الحساب والمستحقات الشهرية — ${settlement.tenant_name}` : `Monthly Settlement Statement — ${settlement.tenant_name}`),
        el('div', { style: 'font-size:12px;color:var(--muted)' }, isAr ? 'كشف حساب مستحقات التحويل من منصة DOU عن تشغيل الورديات المخصصة' : 'Statement of payouts due from DOU platform for dedicated shift operations'),
      ]),
      el('button', {
        class: 'btn btn-ghost btn-small',
        onclick: () => window.print()
      }, isAr ? '🖨️ طباعة كشف الحساب / PDF' : '🖨️ Print Statement / PDF')
    ]),
    tableEl
  ]);

  contentArea.append(kpiRow, statementBox);
}
