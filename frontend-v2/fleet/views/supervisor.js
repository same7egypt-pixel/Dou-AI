// Field Supervisor Unit — Mobile-first one-handed operational interface
// Connects 6 scoped endpoints:
//   - GET /supervisor/overview
//   - GET /supervisor/needs-attention
//   - GET /supervisor/attendance
//   - GET /supervisor/riders
//   - GET /supervisor/shifts
//   - GET /supervisor/performance

import { api } from '../../shared/api/client.js';
import { el, loadingState, emptyState, errorState, metricCard, badge, showToast } from '../../shared/components/ui.js';
import { getLang } from '../../shared/i18n/i18n.js';

export async function loadSupervisor(container) {
  container.innerHTML = '';
  const isAr = getLang() === 'ar';

  const shell = el('div', {
    class: 'supervisor-workspace',
    style: 'max-width:720px;margin:0 auto;padding:12px 14px 80px;direction:rtl;font-family:inherit;'
  });
  if (!isAr) shell.style.direction = 'ltr';

  container.append(shell);

  // Header banner
  const header = el('div', {
    class: 'card',
    style: 'padding:16px 20px;margin-bottom:14px;background:var(--card);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow-sm);'
  }, [
    el('div', { style: 'display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px' }, [
      el('div', { style: 'display:flex;align-items:center;gap:12px' }, [
        el('span', { style: 'font-size:28px;line-height:1' }, '📱'),
        el('div', {}, [
          el('h1', { style: 'font-size:18px;font-weight:800;margin:0;color:var(--ink)' },
            isAr ? 'وحدة المشرف الميداني' : 'Field Supervisor Unit'
          ),
          el('p', { style: 'font-size:12px;color:var(--muted);margin:3px 0 0' },
            isAr ? 'إدارة حضور وتحركات المناديب والورديات الميدانية بيد واحدة' : 'One-handed field management for attendance, riders & shifts'
          )
        ])
      ]),
      el('button', {
        class: 'btn btn-ghost btn-small',
        style: 'min-height:38px;padding:6px 14px;font-weight:600',
        onclick: () => loadCurrentTab()
      }, isAr ? '🔄 تحديث حي' : '🔄 Refresh')
    ])
  ]);
  shell.append(header);

  // Sub-tabs navigation (Horizontal scrollable pill buttons for easy thumb tapping)
  const tabs = [
    { id: 'overview', icon: '📊', label_ar: 'النظرة العامة', label_en: 'Overview' },
    { id: 'needs_attention', icon: '🚨', label_ar: 'تنبيهات الميدان', label_en: 'Needs Attention' },
    { id: 'attendance', icon: '📋', label_ar: 'التحضير والحضور', label_en: 'Attendance' },
    { id: 'riders', icon: '🚴', label_ar: 'مناديب فريقي', label_en: 'My Riders' },
    { id: 'shifts', icon: '⏰', label_ar: 'الورديات', label_en: 'Shifts' },
    { id: 'performance', icon: '📈', label_ar: 'الأداء والطلبات', label_en: 'Performance' },
  ];

  let activeTab = 'overview';
  const navContainer = el('div', {
    style: 'display:flex;gap:8px;overflow-x:auto;padding-bottom:8px;margin-bottom:14px;-webkit-overflow-scrolling:touch;'
  });

  const tabButtons = {};
  tabs.forEach(t => {
    const btn = el('button', {
      type: 'button',
      class: `btn ${activeTab === t.id ? 'btn-primary' : 'btn-ghost'}`,
      style: 'min-height:44px;padding:8px 16px;border-radius:12px;font-size:13px;font-weight:700;white-space:nowrap;display:flex;align-items:center;gap:6px;flex-shrink:0;',
      onclick: () => switchTab(t.id)
    }, [
      el('span', {}, t.icon),
      el('span', {}, isAr ? t.label_ar : t.label_en)
    ]);
    tabButtons[t.id] = btn;
    navContainer.append(btn);
  });
  shell.append(navContainer);

  // Dynamic Content Area
  const contentArea = el('div', { id: 'supervisor-tab-content' });
  shell.append(contentArea);

  function switchTab(tabId) {
    activeTab = tabId;
    Object.entries(tabButtons).forEach(([id, btn]) => {
      if (id === tabId) {
        btn.className = 'btn btn-primary';
      } else {
        btn.className = 'btn btn-ghost';
      }
    });
    loadCurrentTab();
  }

  async function loadCurrentTab() {
    contentArea.innerHTML = '';
    contentArea.append(loadingState(isAr ? 'جاري قراءة بيانات المشرف الميداني...' : 'Loading supervisor data...'));

    try {
      if (activeTab === 'overview') {
        await renderOverview(contentArea, isAr, switchTab);
      } else if (activeTab === 'needs_attention') {
        await renderNeedsAttention(contentArea, isAr, switchTab);
      } else if (activeTab === 'attendance') {
        await renderAttendance(contentArea, isAr);
      } else if (activeTab === 'riders') {
        await renderRiders(contentArea, isAr);
      } else if (activeTab === 'shifts') {
        await renderShifts(contentArea, isAr);
      } else if (activeTab === 'performance') {
        await renderPerformance(contentArea, isAr);
      }
    } catch (err) {
      contentArea.innerHTML = '';
      if (err.status === 403 || String(err.message).includes('Supervisor workspace access required')) {
        contentArea.append(renderAccessDeniedBanner(isAr));
      } else {
        contentArea.append(errorState(err.message, loadCurrentTab));
      }
    }
  }

  // Initial load
  loadCurrentTab();
}

function renderAccessDeniedBanner(isAr) {
  return el('div', {
    class: 'card',
    style: 'padding:24px;border:1px solid #f59e0b;background:#fffbeb;border-radius:14px;text-align:center;'
  }, [
    el('div', { style: 'font-size:36px;margin-bottom:8px' }, '🔒'),
    el('h3', { style: 'font-size:16px;font-weight:800;color:#92400e;margin:0 0 8px' },
      isAr ? 'صلاحية المشرف الميداني مطلوبة' : 'Supervisor Workspace Access Required'
    ),
    el('p', { style: 'font-size:13px;line-height:1.7;color:#b45309;margin:0 0 16px' },
      isAr
        ? 'هذه الشاشة مخصصة لحسابات المشرفين الميدانيين. لو محتاج تتابع الميدان من هنا، كلّم مدير الشركة يربط حسابك بفريق ميداني.'
        : 'This workspace is for field supervisor accounts. Ask your company admin to link your account to a field team if you need it.'
    ),
    // A working phone number and password used to be printed here. Demo
    // credentials on a screen a customer can open are credentials in public.
  ]);
}

// ── 1. OVERVIEW TAB ──
async function renderOverview(container, isAr, switchTab) {
  const data = await api.get('/supervisor/overview');
  container.innerHTML = '';

  // KPI Grid (One-hand mobile layout: 2 columns grid)
  const kpis = el('div', {
    style: 'display:grid;grid-template-columns:repeat(auto-fit, minmax(140px, 1fr));gap:10px;margin-bottom:16px;'
  }, [
    metricCard(data.assigned_riders, isAr ? 'المناديب المسندين' : 'Assigned Riders', 'blue', () => switchTab('riders')),
    metricCard(data.active_riders, isAr ? 'المناديب النشطين' : 'Active Riders', 'green', () => switchTab('riders')),
    metricCard(data.attendance_today, isAr ? 'حضور اليوم' : 'Attended Today', 'green', () => switchTab('attendance')),
    metricCard(
      data.absent_today,
      isAr ? 'غياب اليوم' : 'Absent Today',
      data.absent_today > 0 ? 'red' : 'gray',
      () => switchTab('attendance'),
      data.absent_today > 0 ? (isAr ? 'يحتاج متابعة' : 'Needs Action') : null
    ),
    metricCard(
      data.below_target,
      isAr ? 'دون المستهدف' : 'Below Target',
      data.below_target > 0 ? 'amber' : 'gray',
      () => switchTab('performance')
    ),
    metricCard(
      data.incomplete_onboarding,
      isAr ? 'تمهيد غير مكتمل' : 'Incomplete',
      data.incomplete_onboarding > 0 ? 'amber' : 'gray',
      () => switchTab('riders')
    ),
  ]);
  container.append(kpis);

  // Urgent Alert banner if absent riders or issues exist
  if (data.absent_today > 0 || data.incomplete_onboarding > 0) {
    const alertBox = el('div', {
      class: 'card',
      style: 'padding:14px 16px;margin-bottom:16px;background:var(--card);border:1px solid #ef4444;border-radius:12px;display:flex;align-items:center;justify-content:space-between;gap:12px;'
    }, [
      el('div', { style: 'display:flex;align-items:center;gap:10px' }, [
        el('span', { style: 'font-size:22px' }, '🚨'),
        el('div', {}, [
          el('h4', { style: 'margin:0;font-size:14px;color:var(--ink);font-weight:700' },
            isAr ? `يوجد ${data.absent_today} مناديب غائبين اليوم` : `${data.absent_today} riders absent today`
          ),
          el('p', { style: 'margin:2px 0 0;font-size:12px;color:var(--muted)' },
            isAr ? 'اضغط لمتابعة سجل الحضور والتواصل المباشر مع المناديب' : 'Click to inspect attendance and call riders'
          )
        ])
      ]),
      el('button', {
        class: 'btn btn-primary btn-small',
        style: 'min-height:40px;padding:6px 14px;flex-shrink:0;font-weight:700',
        onclick: () => switchTab('needs_attention')
      }, isAr ? 'فحص التنبيهات ➔' : 'Inspect ➔')
    ]);
    container.append(alertBox);
  }

  // Quick Action Buttons (Big Thumb Buttons)
  const actionRow = el('div', {
    style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px;'
  }, [
    el('button', {
      type: 'button',
      class: 'btn btn-secondary',
      style: 'min-height:50px;font-size:14px;font-weight:700;display:flex;align-items:center;justify-content:center;gap:8px;',
      onclick: () => switchTab('attendance')
    }, [
      el('span', {}, '📋'),
      el('span', {}, isAr ? 'كشف الحضور اليومي' : 'Daily Attendance')
    ]),
    el('button', {
      type: 'button',
      class: 'btn btn-secondary',
      style: 'min-height:50px;font-size:14px;font-weight:700;display:flex;align-items:center;justify-content:center;gap:8px;',
      onclick: () => switchTab('shifts')
    }, [
      el('span', {}, '⏰'),
      el('span', {}, isAr ? 'ورديات اليوم الميدانية' : 'Active Shifts')
    ])
  ]);
  container.append(actionRow);

  // Shifts overview card
  const shiftCard = el('div', {
    class: 'card',
    style: 'padding:16px;background:var(--card);border:1px solid var(--border);border-radius:12px;'
  }, [
    el('h3', { style: 'margin:0 0 10px;font-size:15px;font-weight:700;color:var(--ink)' },
      isAr ? 'ملخص التاريخ والتشغيل' : 'Operational Summary'
    ),
    el('div', { style: 'font-size:13px;color:var(--muted);line-height:1.8' }, [
      el('div', {}, `${isAr ? 'تاريخ اليوم:' : 'Today:'} ${data.period || new Date().toISOString().slice(0, 10)}`),
      el('div', {}, `${isAr ? 'إجمالي المناديب النشطين:' : 'Active Riders:'} ${data.active_riders}`),
      el('div', {}, `${isAr ? 'نسبة التحضير الميداني:' : 'Attendance Rate:'} ${data.active_riders ? Math.round((data.attendance_today / data.active_riders) * 100) : 0}%`)
    ])
  ]);
  container.append(shiftCard);
}

// ── 2. NEEDS ATTENTION TAB ──
async function renderNeedsAttention(container, isAr, switchTab) {
  const data = await api.get('/supervisor/needs-attention');
  container.innerHTML = '';

  const header = el('div', {
    style: 'margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;'
  }, [
    el('h3', { style: 'margin:0;font-size:15px;font-weight:800;color:var(--ink)' },
      isAr ? `تنبيهات واستثناءات الميدان (${data.total || 0})` : `Field Alerts & Exceptions (${data.total || 0})`
    ),
    el('span', { class: `badge badge-${(data.total || 0) > 0 ? 'red' : 'green'}` },
      (data.total || 0) > 0 ? (isAr ? 'إجراءات مطلوبة' : 'Action Required') : (isAr ? 'كل شيء منضبط' : 'All Clear')
    )
  ]);
  container.append(header);

  if (!data.items || data.items.length === 0) {
    container.append(emptyState(isAr ? 'لا توجد تنبيهات عاجلة اليوم. الأسطول الميداني يعمل بانضباط!' : 'No urgent alerts today. Field operations are running smoothly!'));
    return;
  }

  const list = el('div', { style: 'display:flex;flex-direction:column;gap:10px;' });

  data.items.forEach(item => {
    const isHigh = item.severity === 'high';
    const borderCol = isHigh ? '#ef4444' : '#f59e0b';
    const bgCol = isHigh ? 'rgba(239, 68, 68, 0.05)' : 'rgba(245, 158, 11, 0.05)';

    const card = el('div', {
      class: 'card',
      style: `padding:14px 16px;background:${bgCol};border:1px solid ${borderCol};border-radius:12px;display:flex;flex-direction:column;gap:8px;`
    }, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:flex-start;gap:10px' }, [
        el('div', { style: 'display:flex;align-items:center;gap:10px' }, [
          el('span', { style: 'font-size:20px' }, isHigh ? '🚨' : '⚠️'),
          el('div', {}, [
            el('h4', { style: 'margin:0;font-size:14px;font-weight:700;color:var(--ink)' },
              isAr ? item.title_ar : (item.title_en || item.title_ar)
            ),
            el('span', { style: 'font-size:12px;color:var(--muted)' },
              `${isAr ? 'العدد:' : 'Count:'} ${item.count}`
            )
          ])
        ]),
        el('span', { class: `badge badge-${isHigh ? 'red' : 'amber'}` },
          item.severity ? item.severity.toUpperCase() : 'ALERT'
        )
      ]),
      el('div', { style: 'display:flex;gap:8px;margin-top:4px' }, [
        item.signal === 'absent_riders' ? el('button', {
          type: 'button',
          class: 'btn btn-primary btn-small',
          style: 'min-height:42px;flex:1;font-weight:700',
          onclick: () => switchTab('attendance')
        }, isAr ? 'فتح كشف الحضور والتواصل ➔' : 'Open Attendance ➔') : null,

        item.signal === 'incomplete_onboarding' ? el('button', {
          type: 'button',
          class: 'btn btn-primary btn-small',
          style: 'min-height:42px;flex:1;font-weight:700',
          onclick: () => switchTab('riders')
        }, isAr ? 'استعراض المناديب وتجهيزهم ➔' : 'Review Riders ➔') : null,

        item.signal === 'below_target' ? el('button', {
          type: 'button',
          class: 'btn btn-primary btn-small',
          style: 'min-height:42px;flex:1;font-weight:700',
          onclick: () => switchTab('performance')
        }, isAr ? 'مراجعة أداء المناديب ➔' : 'Check Performance ➔') : null
      ].filter(Boolean))
    ]);
    list.append(card);
  });

  container.append(list);
}

// ── 3. ATTENDANCE TAB ──
async function renderAttendance(container, isAr) {
  const todayStr = new Date().toISOString().slice(0, 10);
  let selectedDate = todayStr;

  const topBar = el('div', {
    class: 'card',
    style: 'padding:12px 14px;margin-bottom:12px;background:var(--card);border:1px solid var(--border);border-radius:12px;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;'
  }, [
    el('div', { style: 'display:flex;align-items:center;gap:8px;flex:1;min-width:200px' }, [
      el('label', { style: 'font-size:13px;font-weight:700;color:var(--ink)' }, isAr ? 'التاريخ:' : 'Date:'),
      el('input', {
        type: 'date',
        class: 'input',
        value: selectedDate,
        style: 'min-height:40px;padding:4px 10px;font-size:13px;',
        onchange: (e) => {
          selectedDate = e.target.value;
          fetchAndDraw();
        }
      })
    ]),
    el('button', {
      type: 'button',
      class: 'btn btn-ghost btn-small',
      style: 'min-height:40px;padding:6px 12px;font-weight:700',
      onclick: () => {
        selectedDate = todayStr;
        topBar.querySelector('input').value = todayStr;
        fetchAndDraw();
      }
    }, isAr ? 'اليوم' : 'Today')
  ]);
  container.append(topBar);

  const listContainer = el('div', { style: 'display:flex;flex-direction:column;gap:10px;' });
  container.append(listContainer);

  async function fetchAndDraw() {
    listContainer.innerHTML = '';
    listContainer.append(loadingState(isAr ? 'جاري تحميل سجل التحضير...' : 'Loading attendance records...'));

    try {
      const records = await api.get(`/supervisor/attendance?attendance_date=${selectedDate}`);
      listContainer.innerHTML = '';

      if (!records || records.length === 0) {
        listContainer.append(emptyState(isAr ? `لا يوجد سجل حضور مسجل لتاريخ ${selectedDate}` : `No attendance logged for ${selectedDate}`));
        return;
      }

      records.forEach(rec => {
        const checkInTime = rec.check_in ? new Date(rec.check_in).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '—';
        const checkOutTime = rec.check_out ? new Date(rec.check_out).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : (isAr ? 'على رأس العمل' : 'Active');

        const card = el('div', {
          class: 'card',
          style: 'padding:14px 16px;background:var(--card);border:1px solid var(--border);border-radius:12px;display:flex;flex-direction:column;gap:8px;'
        }, [
          el('div', { style: 'display:flex;justify-content:space-between;align-items:center;' }, [
            el('div', { style: 'display:flex;align-items:center;gap:10px' }, [
              el('span', { style: 'font-size:22px' }, '👤'),
              el('div', {}, [
                el('h4', { style: 'margin:0;font-size:14px;font-weight:800;color:var(--ink)' }, rec.courier_name || `مندوب #${rec.courier_id}`),
                el('span', { style: 'font-size:12px;color:var(--muted)' }, `ID: ${rec.courier_id}`)
              ])
            ]),
            el('span', { class: `badge badge-${rec.is_late ? 'red' : 'green'}` },
              rec.is_late ? (isAr ? 'متأخر' : 'Late') : (isAr ? 'في الموعد' : 'On Time')
            )
          ]),
          el('div', { style: 'display:flex;justify-content:space-between;font-size:12px;color:var(--muted);background:var(--card-subtle, #f8fafc);padding:8px 12px;border-radius:8px;' }, [
            el('span', {}, `${isAr ? 'دخول:' : 'In:'} ${checkInTime}`),
            el('span', {}, `${isAr ? 'خروج:' : 'Out:'} ${checkOutTime}`),
            rec.shift_id ? el('span', {}, `${isAr ? 'وردية:' : 'Shift:'} #${rec.shift_id}`) : null
          ].filter(Boolean))
        ]);
        listContainer.append(card);
      });
    } catch (err) {
      listContainer.innerHTML = '';
      listContainer.append(errorState(err.message, fetchAndDraw));
    }
  }

  fetchAndDraw();
}

// ── 4. MY RIDERS TAB ──
async function renderRiders(container, isAr) {
  let searchVal = '';
  let statusVal = '';

  const filterBar = el('div', {
    class: 'card',
    style: 'padding:12px 14px;margin-bottom:12px;background:var(--card);border:1px solid var(--border);border-radius:12px;display:flex;gap:8px;flex-direction:column;'
  }, [
    el('input', {
      type: 'text',
      class: 'input',
      placeholder: isAr ? '🔍 ابحث بالاسم أو رقم الجوال...' : '🔍 Search by name or phone...',
      style: 'min-height:44px;padding:8px 12px;font-size:14px;',
      oninput: (e) => {
        searchVal = e.target.value;
        fetchAndDraw();
      }
    }),
    el('div', { style: 'display:flex;gap:6px;overflow-x:auto;-webkit-overflow-scrolling:touch;padding-bottom:2px;' }, [
      createFilterChip(isAr ? 'الكل' : 'All', '', true),
      createFilterChip(isAr ? 'نشط' : 'Active', 'ACTIVE', false),
      createFilterChip(isAr ? 'قيد التمهيد' : 'Onboarding', 'ONBOARDING', false),
      createFilterChip(isAr ? 'موقوف' : 'Suspended', 'SUSPENDED', false)
    ])
  ]);
  container.append(filterBar);

  function createFilterChip(label, val, active) {
    const chip = el('button', {
      type: 'button',
      class: `btn ${active ? 'btn-primary' : 'btn-ghost'} btn-small`,
      style: 'min-height:36px;padding:4px 12px;font-size:12px;font-weight:700;border-radius:20px;white-space:nowrap;',
      onclick: () => {
        statusVal = val;
        filterBar.querySelectorAll('button').forEach(b => b.className = 'btn btn-ghost btn-small');
        chip.className = 'btn btn-primary btn-small';
        fetchAndDraw();
      }
    }, label);
    return chip;
  }

  const listContainer = el('div', { style: 'display:flex;flex-direction:column;gap:10px;' });
  container.append(listContainer);

  async function fetchAndDraw() {
    listContainer.innerHTML = '';
    listContainer.append(loadingState(isAr ? 'جاري تحميل قائمة المناديب...' : 'Loading riders list...'));

    try {
      const params = new URLSearchParams();
      if (searchVal) params.set('search', searchVal);
      if (statusVal) params.set('status', statusVal);

      const riders = await api.get(`/supervisor/riders${params.toString() ? '?' + params.toString() : ''}`);
      listContainer.innerHTML = '';

      if (!riders || riders.length === 0) {
        listContainer.append(emptyState(isAr ? 'لم يتم العثور على مناديب مطابقين' : 'No matching riders found'));
        return;
      }

      riders.forEach(r => {
        const isOnline = Boolean(r.is_online);
        const card = el('div', {
          class: 'card',
          style: 'padding:14px 16px;background:var(--card);border:1px solid var(--border);border-radius:12px;display:flex;flex-direction:column;gap:10px;'
        }, [
          el('div', { style: 'display:flex;justify-content:space-between;align-items:center;' }, [
            el('div', { style: 'display:flex;align-items:center;gap:10px' }, [
              el('span', { style: `display:inline-block;width:12px;height:12px;border-radius:50%;background:${isOnline ? '#22c55e' : '#94a3b8'};box-shadow:${isOnline ? '0 0 6px #22c55e' : 'none'}` }),
              el('div', {}, [
                el('h4', { style: 'margin:0;font-size:15px;font-weight:800;color:var(--ink)' }, r.name),
                el('span', { style: 'font-size:12px;color:var(--muted)' }, r.work_city ? `${isAr ? 'المدينة:' : 'City:'} ${r.work_city}` : (r.phone || '—'))
              ])
            ]),
            el('span', { class: `badge badge-${r.employment_status === 'ACTIVE' ? 'green' : 'amber'}` },
              r.employment_status || 'UNKNOWN'
            )
          ]),
          el('div', { style: 'display:flex;gap:8px;margin-top:2px' }, [
            r.phone ? el('a', {
              href: `tel:${r.phone}`,
              class: 'btn btn-primary',
              style: 'flex:1;min-height:44px;display:flex;align-items:center;justify-content:center;gap:8px;font-size:13px;font-weight:700;text-decoration:none;'
            }, [
              el('span', {}, '📞'),
              el('span', {}, isAr ? 'اتصال مباشر' : 'Direct Call')
            ]) : null,
            el('button', {
              type: 'button',
              class: 'btn btn-ghost',
              style: 'min-height:44px;padding:6px 14px;font-size:13px;font-weight:600;',
              onclick: () => {
                showToast(isAr ? `معرف المندوب: ${r.id}\nالاسم: ${r.name}\nالهاتف: ${r.phone || 'غير مسجل'}\nالحالة: ${r.employment_status}` : `Rider ID: ${r.id}\nName: ${r.name}\nPhone: ${r.phone}\nStatus: ${r.employment_status}`, 'info');
              }
            }, isAr ? 'تفاصيل' : 'Details')
          ].filter(Boolean))
        ]);
        listContainer.append(card);
      });
    } catch (err) {
      listContainer.innerHTML = '';
      listContainer.append(errorState(err.message, fetchAndDraw));
    }
  }

  fetchAndDraw();
}

// ── 5. SHIFTS TAB ──
async function renderShifts(container, isAr) {
  container.innerHTML = '';
  container.append(loadingState(isAr ? 'جاري تحميل ورديات الفريق الميدانية...' : 'Loading supervisor shifts...'));

  try {
    const shifts = await api.get('/supervisor/shifts');
    container.innerHTML = '';

    if (!shifts || shifts.length === 0) {
      container.append(emptyState(isAr ? 'لا توجد ورديات نشطة لمناديب فريقك حالياً' : 'No active shifts for your team riders'));
      return;
    }

    const list = el('div', { style: 'display:flex;flex-direction:column;gap:10px;' });

    shifts.forEach(s => {
      const startTime = s.start_time ? new Date(s.start_time).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '—';
      const endTime = s.end_time ? new Date(s.end_time).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '—';
      const relevantCount = Array.isArray(s.relevant_riders) ? s.relevant_riders.length : 0;

      const card = el('div', {
        class: 'card',
        style: 'padding:14px 16px;background:var(--card);border:1px solid var(--border);border-radius:12px;display:flex;flex-direction:column;gap:8px;'
      }, [
        el('div', { style: 'display:flex;justify-content:space-between;align-items:center;' }, [
          el('div', {}, [
            el('h4', { style: 'margin:0;font-size:14px;font-weight:800;color:var(--ink)' }, s.title || s.name || `وردية #${s.id}`),
            el('span', { style: 'font-size:12px;color:var(--muted)' }, `${startTime} ➔ ${endTime}`)
          ]),
          el('span', { class: `badge badge-${s.status === 'OPEN' ? 'blue' : (s.status === 'IN_PROGRESS' ? 'green' : 'gray')}` },
            s.status || 'SCHEDULED'
          )
        ]),
        el('div', { style: 'display:flex;justify-content:space-between;font-size:12px;color:var(--muted);background:var(--card-subtle, #f8fafc);padding:8px 12px;border-radius:8px;' }, [
          el('span', {}, `${isAr ? 'مناديب فريقي المشتركون:' : 'My Team Riders:'} ${relevantCount}`),
          el('span', {}, `${isAr ? 'السعة الكلية:' : 'Total Capacity:'} ${s.capacity || '—'}`),
          el('span', {}, `${isAr ? 'المسندين:' : 'Assigned:'} ${s.assigned_count || 0}`)
        ])
      ]);
      list.append(card);
    });

    container.append(list);
  } catch (err) {
    container.innerHTML = '';
    container.append(errorState(err.message, () => renderShifts(container, isAr)));
  }
}

// ── 6. PERFORMANCE TAB ──
async function renderPerformance(container, isAr) {
  const currentPeriod = new Date().toISOString().slice(0, 7); // YYYY-MM
  let period = currentPeriod;

  const topBar = el('div', {
    class: 'card',
    style: 'padding:12px 14px;margin-bottom:12px;background:var(--card);border:1px solid var(--border);border-radius:12px;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;'
  }, [
    el('div', { style: 'display:flex;align-items:center;gap:8px;' }, [
      el('label', { style: 'font-size:13px;font-weight:700;color:var(--ink)' }, isAr ? 'شهر الأداء:' : 'Period:'),
      el('input', {
        type: 'month',
        class: 'input',
        value: period,
        style: 'min-height:40px;padding:4px 10px;font-size:13px;',
        onchange: (e) => {
          period = e.target.value;
          fetchAndDraw();
        }
      })
    ]),
    el('span', { style: 'font-size:12px;color:var(--muted)' },
      isAr ? 'مرتب تنازلياً حسب الإنجاز' : 'Ranked by completed orders'
    )
  ]);
  container.append(topBar);

  const listContainer = el('div', { style: 'display:flex;flex-direction:column;gap:10px;' });
  container.append(listContainer);

  async function fetchAndDraw() {
    listContainer.innerHTML = '';
    listContainer.append(loadingState(isAr ? 'جاري قراءة أداء المناديب...' : 'Loading performance metrics...'));

    try {
      const data = await api.get(`/supervisor/performance?period=${period}`);
      listContainer.innerHTML = '';

      const riders = data.riders || [];
      if (riders.length === 0) {
        listContainer.append(emptyState(isAr ? `لا توجد بيانات أداء مسجلة لفترة ${period}` : `No performance records for ${period}`));
        return;
      }

      // Sort descending by completed orders
      const sorted = [...riders].sort((a, b) => (b.completed_orders || 0) - (a.completed_orders || 0));

      sorted.forEach((r, idx) => {
        const isTop = idx < 3 && r.completed_orders > 0;
        const medal = idx === 0 ? '🥇' : (idx === 1 ? '🥈' : (idx === 2 ? '🥉' : `#${idx + 1}`));

        const card = el('div', {
          class: 'card',
          style: `padding:14px 16px;background:var(--card);border:1px solid ${isTop ? '#f59e0b' : 'var(--border)'};border-radius:12px;display:flex;align-items:center;justify-content:space-between;gap:12px;`
        }, [
          el('div', { style: 'display:flex;align-items:center;gap:12px' }, [
            el('span', { style: 'font-size:20px;font-weight:800;min-width:28px;text-align:center;' }, medal),
            el('div', {}, [
              el('h4', { style: 'margin:0;font-size:14px;font-weight:800;color:var(--ink)' }, r.courier_name || `مندوب #${r.courier_id}`),
              el('span', { style: 'font-size:12px;color:var(--muted)' }, `ID: ${r.courier_id}`)
            ])
          ]),
          el('div', { style: 'text-align:left;display:flex;flex-direction:column;align-items:flex-end;' }, [
            el('b', { style: 'font-size:16px;color:var(--primary);font-weight:900;' }, `${r.completed_orders || 0}`),
            el('span', { style: 'font-size:11px;color:var(--muted)' }, isAr ? 'طلب مكتمل' : 'orders')
          ])
        ]);
        listContainer.append(card);
      });
    } catch (err) {
      listContainer.innerHTML = '';
      listContainer.append(errorState(err.message, fetchAndDraw));
    }
  }

  fetchAndDraw();
}
