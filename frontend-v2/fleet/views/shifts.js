// Shifts, Daily Attendance & Attendance Corrections Review Queue (Batch 2A)
import { api } from '../../shared/api/client.js';
import { appStore } from '../../shared/state/store.js';
import {
  el, loadingState, emptyState, errorState, table, button, escapeHtml,
  modal, formRow, inputField, selectField, metricCard, badge, searchableSelect, showToast } from '../../shared/components/ui.js';
import { go } from '../shell.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

// A queue that silently swallows a failed request tells the manager there is
// nothing to approve. An unreviewed correction is an attendance record — and a
// salary — that stays wrong, so a failure here has to be visible. This keeps
// one dead source from blanking the screen, and reports what did not load.
async function loadSources(sources) {
  const settled = await Promise.all(
    sources.map((s) => s.get().then((data) => ({ ok: true, data }), () => ({ ok: false }))),
  );
  return {
    data: settled.map((r) => (r.ok ? r.data : [])),
    failed: sources.filter((_, i) => !settled[i].ok).map((s) => s.label),
  };
}

function partialLoadWarning(failed) {
  if (!failed.length) return null;
  return el('div', {
    style: 'display:flex;gap:8px;align-items:flex-start;padding:10px 12px;margin-bottom:10px;'
      + 'border:1px solid var(--danger,#c0392b);border-radius:8px;background:rgba(192,57,43,.07);font-size:12.5px',
  }, [
    el('span', { text: '⚠️' }),
    el('span', {}, `تعذّر تحميل ${failed.join(' و')} — القائمة تحت غير مكتملة، وقد تكون هناك طلبات لا تظهر. حدّث الصفحة.`),
  ]);
}

let currentTab = 'shifts'; // 'shifts' | 'attendance' | 'corrections'
let selectedAttendanceDate = new Date().toISOString().split('T')[0];
let selectedAttendanceStatus = '';

export async function loadShifts(container, tabOverride = null) {
  const isAr = getLang() === 'ar';
  const requestedTab = tabOverride || window.__shiftsInitialTab || new URLSearchParams(location.search).get('subtab') || currentTab;
  window.__shiftsInitialTab = null;
  currentTab = requestedTab;

  const role = appStore.get().role || localStorage.getItem('dou_role_v2');
  const canManageShifts = ['COMPANY', 'COMPANY_ADMIN', 'OPERATIONS'].includes(role);

  container.innerHTML = '';

  // Header & Navigation Tabs
  const tabButtons = [
    { id: 'shifts', label: isAr ? '📅 جدول الورديات' : '📅 Shifts Schedule' },
    { id: 'attendance', label: isAr ? '⏱️ الحضور اليومي' : '⏱️ Daily Attendance' },
    { id: 'corrections', label: isAr ? '📝 تصحيحات الحضور' : '📝 Attendance Corrections' },
    { id: 'overtime', label: isAr ? '⏰ العمل الإضافي' : '⏰ Overtime Requests' },
    { id: 'leaves', label: isAr ? '🌴 طلبات الإجازات' : '🌴 Leave Requests' },
  ];

  const headerActions = el('div', { id: 'tab-header-actions', style: 'display:flex;gap:8px;align-items:center' });

  const header = el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'تخطيط القوى والعمليات الميدانية' : 'Workforce Planning & Field Operations'),
      el('h1', { text: isAr ? 'الورديات والحضور' : 'Shifts & Attendance' }),
    ]),
    headerActions,
  ]);

  const tabsNav = el('div', { class: 'tabs', style: 'margin-bottom:16px' }, tabButtons.map((t) => {
    return el('button', {
      class: `tab ${currentTab === t.id ? 'active' : ''}`,
      'data-subtab': t.id,
      onclick: () => switchSubTab(t.id, container)
    }, t.label);
  }));

  const contentArea = el('div', { id: 'shifts-tab-content' });

  container.append(header, tabsNav, contentArea);
  renderActiveTab(contentArea, headerActions, canManageShifts);
}

function switchSubTab(tabId, container) {
  currentTab = tabId;
  container.querySelectorAll('.tab[data-subtab]').forEach((t) => {
    t.classList.toggle('active', t.dataset.subtab === tabId);
  });
  const contentArea = document.getElementById('shifts-tab-content');
  const headerActions = document.getElementById('tab-header-actions');
  const role = appStore.get().role || localStorage.getItem('dou_role_v2');
  const canManageShifts = ['COMPANY', 'COMPANY_ADMIN', 'OPERATIONS'].includes(role);
  renderActiveTab(contentArea, headerActions, canManageShifts);
}

function renderActiveTab(contentArea, headerActions, canManage) {
  const isAr = getLang() === 'ar';
  headerActions.innerHTML = '';
  contentArea.innerHTML = '';

  if (currentTab === 'shifts') {
    if (canManage) {
      headerActions.append(el('button', { class: 'btn btn-blue', onclick: () => openAddShift() }, isAr ? '+ إنشاء وردية' : '+ Create Shift'));
    }
    renderShiftsTab(contentArea, canManage);
  } else if (currentTab === 'attendance') {
    if (canManage) {
      headerActions.append(el('button', { class: 'btn btn-ghost', onclick: () => openAttendancePoliciesModal() }, isAr ? '⚙️ سياسات خصم الحضور' : '⚙️ Attendance Deduction Policies'));
    }
    renderAttendanceTab(contentArea, headerActions);
  } else if (currentTab === 'corrections') {
    renderCorrectionsTab(contentArea, headerActions, canManage);
  } else if (currentTab === 'overtime') {
    renderOvertimeTab(contentArea, headerActions, canManage);
  } else if (currentTab === 'leaves') {
    renderLeavesTab(contentArea, headerActions, canManage);
  }
}

// ----------------------------------------------------
// TAB 1: SHIFTS SCHEDULE
// ----------------------------------------------------
async function renderShiftsTab(container, canManage) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';
  const list = el('div', {}, [loadingState(isAr ? 'جاري تحميل جدول الورديات...' : 'Loading shifts schedule...')]);
  container.append(list);

  try {
    const shifts = await api.get('/fleet/shifts');
    if (!shifts.length) {
      list.replaceWith(emptyState(isAr ? 'لا توجد ورديات مجدولة. أنشئ أول وردية لتنظيم العمل.' : 'No scheduled shifts. Create your first shift to organize workforce.'));
      return;
    }
    list.replaceWith(table([
      { key: 'name', label: isAr ? 'الوردية' : 'Shift' },
      { key: 'zone', label: isAr ? 'المدينة / المنطقة' : 'City / Area', render: (v) => v || (isAr ? 'الرياض' : 'Riyadh') },
      { key: 'start_time', label: isAr ? 'التوقيت' : 'Timing', render: (_, r) => `${r.start_time || '—'} ➔ ${r.end_time || '—'}` },
      { key: 'status', label: isAr ? 'الحالة' : 'Status', render: (v) => badge(v === 'ACTIVE' ? (isAr ? 'نشطة' : 'Active') : (isAr ? 'مجدولة' : 'Scheduled'), v === 'ACTIVE' ? 'green' : 'blue') },
      { key: 'capacity', label: isAr ? 'المناديب / السعة' : 'Drivers / Capacity', render: (_, r) => {
        const count = r.courier_ids ? r.courier_ids.length : 0;
        const req = r.required_couriers || 0;
        const color = count >= req && req > 0 ? 'green' : 'amber';
        return el('span', { class: `badge badge-${color}` }, `${count} / ${req} ${isAr ? 'سائق' : 'Drivers'}`);
      }},
      { key: 'actions', label: isAr ? 'إجراءات التحكم والتعيين' : 'Actions', render: (_, row) => {
        const count = row.courier_ids ? row.courier_ids.length : 0;
        return el('div', { style: 'display:flex;gap:6px;align-items:center' }, [
          canManage ? el('button', {
            class: 'btn btn-blue btn-small',
            onclick: () => window.assignRiderToShift(row.id, row.name)
          }, isAr ? '➕ إسناد سائق' : '➕ Assign Driver') : null,
          el('button', {
            class: 'btn btn-ghost btn-small',
            onclick: () => window.viewShiftRidersModal(row.id, row.name)
          }, isAr ? `👥 المناديب (${count})` : `👥 Drivers (${count})`)
        ].filter(Boolean));
      }},
    ], shifts));
  } catch (e) {
    list.replaceWith(errorState('تعذر تحميل الورديات: ' + e.message));
  }
}

function openAddShift() {
  const content = el('form', { id: 'add-shift-form', style: 'display:grid;gap:12px' }, [
    formRow([
      inputField('shift-name', 'اسم الوردية: *', { required: true, placeholder: 'مثال: وردية الظهيرة نينجا' }),
      inputField('shift-zone', 'المدينة / المنطقة:', { value: 'الرياض' }),
    ]),
    formRow([
      inputField('shift-start', 'من الساعة (HH:MM): *', { type: 'time', value: '09:00', required: true }),
      inputField('shift-end', 'إلى الساعة (HH:MM): *', { type: 'time', value: '17:00', required: true }),
      inputField('shift-req', 'عدد السائقين المطلوب:', { type: 'number', min: '1', value: '2' }),
    ]),
    el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:10px' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
      el('button', { type: 'submit', class: 'btn btn-blue' }, '💾 حفظ وطرح الوردية')
    ]),
    el('span', { id: 'shift-msg', class: 'msg' }),
  ]);
  const m = modal('➕ إنشاء وطرح وردية جديدة', content);
  content.addEventListener('submit', async (e) => {
    e.preventDefault();
    const msg = document.getElementById('shift-msg');
    try {
      await api.post('/fleet/shifts', {
        name: document.getElementById('shift-name').value.trim(),
        zone: document.getElementById('shift-zone').value.trim(),
        start_time: document.getElementById('shift-start').value,
        end_time: document.getElementById('shift-end').value,
        required_couriers: Number(document.getElementById('shift-req').value) || 1,
      });
      msg.style.color = 'var(--green)'; msg.textContent = '✅ أُنشئت الوردية وطُرحت بنجاح.';
      setTimeout(() => { m.remove(); loadShifts(document.getElementById('content-area'), 'shifts'); }, 800);
    } catch (err) {
      msg.style.color = 'var(--red)'; msg.textContent = '❌ ' + err.message;
    }
  });
}

window.assignRiderToShift = async (shiftId, shiftName = '') => {
  try {
    const res = await api.get('/fleet/couriers/page?page=1&page_size=300');
    const rows = Array.isArray(res) ? res : (res?.rows || []);
    if (!rows.length) {
      modal('إسناد سائق', el('p', { text: 'لا يوجد سائقون متاحون في المنظومة.' }));
      return;
    }

    let searchQuery = '';
    let filterActiveOnly = false;

    const modalBody = el('div', { style: 'display:grid;gap:12px;direction:rtl;min-width:480px;max-width:580px' });

    // Header info
    modalBody.append(el('div', { style: 'background:var(--soft);border:1px solid var(--border);border-radius:8px;padding:10px 14px;font-size:13px' }, [
      el('span', { style: 'color:var(--muted)' }, 'الوردية المستهدفة: '),
      el('b', { style: 'color:var(--text)' }, shiftName || `وردية #${shiftId}`),
      el('span', { style: 'color:var(--muted);margin:0 8px' }, '·'),
      el('span', { style: 'color:var(--muted)' }, `إجمالي السائقين المتاحين: `),
      el('b', { style: 'color:var(--primary)' }, String(rows.length))
    ]));

    // Search input bar
    const searchInput = el('input', {
      type: 'text',
      id: 'shift-assign-search-input',
      class: 'input',
      placeholder: '🔍 اكتب اسم السائق، رقم الجوال، أو رقم الهوية للبحث الفوري...',
      style: 'width:100%;box-sizing:border-box;padding:11px 14px;font-size:13.5px;border-radius:8px;border:2px solid var(--primary);outline:none'
    });

    const filterRow = el('div', { style: 'display:flex;justify-content:space-between;align-items:center;font-size:12px' }, [
      el('span', { id: 'search-results-count', style: 'color:var(--muted)' }, `تم العثور على ${rows.length} سائق`),
      el('label', { style: 'display:flex;align-items:center;gap:5px;cursor:pointer;user-select:none' }, [
        el('input', {
          type: 'checkbox',
          id: 'filter-active-checkbox',
          onchange: (e) => { filterActiveOnly = e.target.checked; renderList(); }
        }),
        el('span', {}, 'إظهار السائقين النشطين فقط')
      ])
    ]);

    const listContainer = el('div', {
      id: 'shift-assign-riders-list',
      style: 'display:grid;gap:8px;max-height:340px;overflow-y:auto;padding-right:2px'
    });

    const statusMsg = el('div', { id: 'shift-assign-status-msg', class: 'msg', style: 'margin-top:4px' });

    modalBody.append(searchInput, filterRow, listContainer, statusMsg);

    const m = modal('🔍 إسناد وتعيين سائق للوردية', modalBody);

    function normalizeAr(text) {
      return String(text || '')
        .trim()
        .toLowerCase()
        .replace(/[أإآ]/g, 'ا')
        .replace(/ة/g, 'ه')
        .replace(/[ًٌٍَُِّْ]/g, '');
    }

    function renderList() {
      listContainer.innerHTML = '';
      const q = normalizeAr(searchQuery);

      const filtered = rows.filter(c => {
        if (filterActiveOnly && c.employment_status !== 'ACTIVE') return false;
        if (!q) return true;
        const nameNorm = normalizeAr(c.name);
        const phone = String(c.phone || '').replace(/\D/g, '');
        const idStr = String(c.id);
        const contract = normalizeAr(c.contract_name || c.courier_type || '');
        return nameNorm.includes(q) || phone.includes(q) || idStr.includes(q) || contract.includes(q);
      });

      const countEl = document.getElementById('search-results-count');
      if (countEl) countEl.textContent = `تم العثور على ${filtered.length} سائق`;

      if (!filtered.length) {
        listContainer.append(emptyState('لا يوجد سائق مطابق لبحثك. جرب كتابة اسم آخر أو رقم جوال.'));
        return;
      }

      filtered.forEach(c => {
        const isActive = c.employment_status === 'ACTIVE';
        const card = el('div', {
          style: 'background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px 14px;display:flex;justify-content:space-between;align-items:center;transition:border-color .15s ease',
          onmouseenter: () => card.style.borderColor = 'var(--primary)',
          onmouseleave: () => card.style.borderColor = 'var(--border)'
        }, [
          el('div', { style: 'display:flex;align-items:center;gap:10px' }, [
            el('div', { style: 'font-size:22px' }, '🛵'),
            el('div', {}, [
              el('div', { style: 'display:flex;align-items:center;gap:6px' }, [
                el('b', { style: 'font-size:13.5px;color:var(--text)' }, c.name),
                el('span', { class: `badge badge-${isActive ? 'green' : 'amber'}`, style: 'font-size:10px' }, isActive ? 'نشط' : 'جديد')
              ]),
              el('div', { style: 'font-size:11.5px;color:var(--muted);margin-top:2px' }, [
                el('span', {}, `📱 ${c.phone || '—'}`),
                el('span', { style: 'margin:0 6px' }, '·'),
                el('span', {}, `🏢 ${c.contract_name || c.courier_type || 'عقد عام'}`),
                c.city ? el('span', {}, ` (${c.city})`) : null
              ])
            ])
          ]),
          el('button', {
            class: 'btn btn-blue btn-small',
            style: 'white-space:nowrap',
            onclick: async () => {
              statusMsg.style.color = 'var(--primary)';
              statusMsg.textContent = `جاري إسناد ${c.name}...`;
              try {
                await api.post(`/shifts/${shiftId}/assign`, { courier_id: c.id });
                statusMsg.style.color = 'var(--green)';
                statusMsg.textContent = `✅ تم إسناد السائق ${c.name} للوردية بنجاح.`;
                setTimeout(() => {
                  m.remove();
                  loadShifts(document.getElementById('content-area'), 'shifts');
                }, 700);
              } catch (err) {
                statusMsg.style.color = 'var(--red)';
                statusMsg.textContent = '❌ ' + err.message;
              }
            }
          }, '➕ إسناد للوردية')
        ]);
        listContainer.append(card);
      });
    }

    searchInput.addEventListener('input', (e) => {
      searchQuery = e.target.value;
      renderList();
    });

    renderList();
    setTimeout(() => searchInput.focus(), 100);

  } catch (e) {
    modal('خطأ', el('p', { style: 'color:var(--red)', text: 'تعذر تحميل السائقين: ' + e.message }));
  }
};

window.viewShiftRidersModal = async (shiftId, shiftName = '') => {
  try {
    const riders = await api.get(`/shifts/${shiftId}/riders`);
    const body = el('div', { style: 'display:grid;gap:12px;direction:rtl;min-width:400px' });

    body.append(el('p', { style: 'margin:0;font-size:13px;color:var(--text)' }, [
      el('span', {}, 'قائمة المناديب المسندين في: '),
      el('b', {}, shiftName || `الوردية #${shiftId}`)
    ]));

    if (!riders.length) {
      body.append(emptyState('لا يوجد مناديب مسندين لهذه الوردية حالياً.'));
    } else {
      const listDiv = el('div', { style: 'display:grid;gap:8px' }, riders.map(r => {
        return el('div', { style: 'background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px 14px;display:flex;justify-content:space-between;align-items:center' }, [
          el('div', {}, [
            el('b', { style: 'font-size:13px;color:var(--text)' }, r.name),
            el('div', { style: 'font-size:11px;color:var(--muted);margin-top:2px' }, `📱 ${r.phone || '—'}`)
          ]),
          el('button', {
            class: 'btn btn-ghost btn-small',
            style: 'color:#dc2626',
            onclick: async () => {
              if (!confirm(`هل أنت متأكد من إزالة السائق ${r.name} من هذه الوردية؟`)) return;
              try {
                await api.post(`/shifts/${shiftId}/remove`, { courier_id: r.id });
                m.remove();
                window.viewShiftRidersModal(shiftId, shiftName);
                loadShifts(document.getElementById('content-area'), 'shifts');
              } catch (err) {
                showToast('❌ تعذر إزالة السائق: ' + err.message, 'error');
              }
            }
          }, '🗑️ إزالة')
        ]);
      }));
      body.append(listDiv);
    }

    body.append(el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)' }, [
      el('button', { class: 'btn btn-blue btn-small', onclick: () => { m.remove(); window.assignRiderToShift(shiftId, shiftName); } }, '➕ إضافة سائق آخر'),
      el('button', { class: 'btn btn-ghost btn-small', onclick: () => m.remove() }, 'إغلاق')
    ]));

    const m = modal('👥 المناديب المسندين للوردية', body);
  } catch (err) {
    modal('خطأ', el('p', { style: 'color:var(--red)', text: 'تعذر تحميل المناديب: ' + err.message }));
  }
};

async function openAttendancePoliciesModal() {
  try {
    const policies = await api.get('/hr/attendance-policies');
    const latePolicy = policies.find(p => p.event_type === 'LATE') || {};
    const absPolicy = policies.find(p => p.event_type === 'ABSENCE') || {};

    const content = el('form', { style: 'display:grid;gap:14px;min-width:450px' }, [
      el('div', { style: 'background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px' }, [
        el('h4', { style: 'margin:0 0 8px 0;font-size:13px;color:var(--text)' }, '⏱️ سياسة التأخير عن الوردية (Late Check-in)'),
        el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
          el('div', {}, [
            el('label', { style: 'display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:3px' }, 'فترة السماح (بالدقائق):'),
            el('input', { type: 'number', id: 'pol-late-grace', value: latePolicy.grace_minutes || 15, style: 'width:100%;padding:6px;border:1px solid var(--border);border-radius:6px' })
          ]),
          el('div', {}, [
            el('label', { style: 'display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:3px' }, 'مبلغ خصم التأخير (ر.س):'),
            el('input', { type: 'number', id: 'pol-late-amount', value: latePolicy.deduction_amount || 25, style: 'width:100%;padding:6px;border:1px solid var(--border);border-radius:6px' })
          ])
        ])
      ]),
      el('div', { style: 'background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px' }, [
        el('h4', { style: 'margin:0 0 8px 0;font-size:13px;color:var(--text)' }, '🚫 سياسة الغياب بدون إذن (Unexcused Absence)'),
        el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
          el('div', {}, [
            el('label', { style: 'display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:3px' }, 'طريقة الحساب:'),
            el('select', { id: 'pol-abs-method', style: 'width:100%;padding:6px;border:1px solid var(--border);border-radius:6px' }, [
              el('option', { value: 'FIXED', selected: absPolicy.calculation_method === 'FIXED' }, 'مبلغ ثابت (ر.س)'),
              el('option', { value: 'DAILY_RATE_MULTIPLIER', selected: absPolicy.calculation_method === 'DAILY_RATE_MULTIPLIER' }, 'خصم أجر يوم (1x)'),
            ])
          ]),
          el('div', {}, [
            el('label', { style: 'display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:3px' }, 'مبلغ الخصم أو المعامل:'),
            el('input', { type: 'number', id: 'pol-abs-amount', value: absPolicy.deduction_amount || 100, style: 'width:100%;padding:6px;border:1px solid var(--border);border-radius:6px' })
          ])
        ])
      ]),
      el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:10px' }, [
        el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
        el('button', { type: 'submit', class: 'btn btn-primary' }, 'حفظ السياسات')
      ])
    ]);

    const m = modal('⚙️ ضبط سياسات وقواعد خصومات الحضور والغياب', content);
    content.onsubmit = async (e) => {
      e.preventDefault();
      const lateGrace = parseInt(document.getElementById('pol-late-grace').value || 15);
      const lateAmount = parseFloat(document.getElementById('pol-late-amount').value || 0);
      const absMethod = document.getElementById('pol-abs-method').value;
      const absAmount = parseFloat(document.getElementById('pol-abs-amount').value || 0);

      try {
        await api.post('/hr/attendance-policies', {
          event_type: 'LATE',
          calculation_method: 'FIXED',
          grace_minutes: lateGrace,
          deduction_amount: lateAmount,
          is_active: true
        });
        await api.post('/hr/attendance-policies', {
          event_type: 'ABSENCE',
          calculation_method: absMethod,
          grace_minutes: 0,
          deduction_amount: absAmount,
          is_active: true
        });
        showToast('✅ تم حفظ وتفعيل سياسات الحضور والخصم الآلي بنجاح.', 'success');
        m.remove();
      } catch (err) {
        showToast('❌ تعذر حفظ السياسات: ' + err.message, 'error');
      }
    };
  } catch (err) {
    showToast('❌ خطأ: ' + err.message, 'error');
  }
}
async function renderAttendanceTab(container, headerActions) {
  const todayStr = new Date().toISOString().split('T')[0];
  const yesterdayStr = new Date(Date.now() - 86400000).toISOString().split('T')[0];

  const isAr = getLang() === 'ar';
  headerActions.append(
    el('button', {
      class: `btn-ghost btn-small ${selectedAttendanceDate === todayStr ? 'active' : ''}`,
      onclick: () => { selectedAttendanceDate = todayStr; refreshAttendance(); }
    }, isAr ? 'اليوم' : 'Today'),
    el('button', {
      class: `btn-ghost btn-small ${selectedAttendanceDate === yesterdayStr ? 'active' : ''}`,
      onclick: () => { selectedAttendanceDate = yesterdayStr; refreshAttendance(); }
    }, isAr ? 'أمس' : 'Yesterday'),
    el('button', { class: 'btn btn-ghost btn-small', onclick: () => refreshAttendance() }, `↻ ${t('تحديث')}`)
  );

  const controls = el('div', { class: 'filters', style: 'display:flex;gap:12px;align-items:center;margin-bottom:16px' }, [
    el('div', { style: 'display:flex;align-items:center;gap:6px' }, [
      el('label', { text: isAr ? 'تاريخ الحضور:' : 'Attendance Date:' }),
      el('input', {
        id: 'att-date-picker',
        type: 'date',
        value: selectedAttendanceDate,
        onchange: (e) => { selectedAttendanceDate = e.target.value; refreshAttendance(); }
      }),
    ]),
    el('div', { style: 'display:flex;align-items:center;gap:6px' }, [
      el('label', { text: isAr ? 'الحالة:' : 'Status:' }),
      el('select', {
        id: 'att-status-filter',
        onchange: (e) => { selectedAttendanceStatus = e.target.value; refreshAttendance(); }
      }, [
        el('option', { value: '' }, isAr ? 'كل الحالات' : 'All Statuses'),
        el('option', { value: 'PRESENT' }, isAr ? 'حاضر في الوقت' : 'On Time (Present)'),
        el('option', { value: 'LATE' }, isAr ? 'متأخر' : 'Late'),
        el('option', { value: 'IN_PROGRESS' }, isAr ? 'قيد العمل' : 'In Progress'),
        el('option', { value: 'EARLY_LEAVE' }, isAr ? 'مغادرة مبكرة' : 'Early Leave'),
      ]),
    ]),
  ]);

  const metricsWrap = el('div', { class: 'cards', id: 'att-metrics', style: 'margin-bottom:16px' });
  const tableWrap = el('div', { id: 'att-table-wrap' }, [loadingState(isAr ? 'جاري تحميل سجلات الحضور...' : 'Loading attendance records...')]);

  container.append(controls, metricsWrap, tableWrap);

  async function refreshAttendance() {
    tableWrap.innerHTML = '';
    tableWrap.append(loadingState(isAr ? 'جاري تحميل سجلات الحضور...' : 'Loading attendance records...'));

    const dateInput = document.getElementById('att-date-picker');
    if (dateInput) dateInput.value = selectedAttendanceDate;

    try {
      const data = await api.get(`/fleet/attendance?attendance_date=${selectedAttendanceDate}`);
      const records = data || [];

      // Compute metrics
      const total = records.length;
      const onTime = records.filter((r) => r.status === 'PRESENT').length;
      const late = records.filter((r) => r.status === 'LATE' || r.is_late).length;
      const inProgress = records.filter((r) => r.status === 'IN_PROGRESS' || !r.check_out).length;

      metricsWrap.innerHTML = '';
      metricsWrap.append(
        metricCard(total, isAr ? 'إجمالي الحضور' : 'Total Attendance'),
        metricCard(onTime, isAr ? 'حاضر بالموعد' : 'On Time', 'good'),
        metricCard(late, isAr ? 'متأخر' : 'Late', late ? 'alert' : 'normal'),
        metricCard(inProgress, isAr ? 'في الميدان الآن' : 'In Field Now')
      );

      let filtered = records;
      if (selectedAttendanceStatus) {
        filtered = records.filter((r) => r.status === selectedAttendanceStatus);
      }

      if (!filtered.length) {
        tableWrap.replaceChildren(emptyState(isAr ? `لا توجد سجلات حضور مسجلة لتاريخ ${selectedAttendanceDate}.` : `No attendance records found for ${selectedAttendanceDate}.`));
        return;
      }

      tableWrap.replaceChildren(table([
        { key: 'name', label: isAr ? 'السائق' : 'Driver', render: (v, row) => el('b', { text: v || (isAr ? `سائق #${row.courier_id || '—'}` : `Driver #${row.courier_id || '—'}`) }) },
        { key: 'shift', label: isAr ? 'الوردية' : 'Shift', render: (v) => v || (isAr ? 'وردية افتراضية' : 'Default Shift') },
        { key: 'check_in', label: isAr ? 'وقت الحضور' : 'Check-in Time', render: (v) => v ? new Date(v).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '—' },
        { key: 'check_out', label: isAr ? 'وقت الانصراف' : 'Check-out Time', render: (v) => v ? new Date(v).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '—' },
        { key: 'hours', label: isAr ? 'ساعات العمل' : 'Working Hours', render: (v, row) => v ? `${v} ${isAr ? 'س' : 'hrs'}` : (row.scheduled_hours ? `${row.scheduled_hours} ${isAr ? 'س (مجدولة)' : 'hrs (sched)'}` : '—') },
        { key: 'status', label: isAr ? 'الحالة' : 'Status', render: (v) => {
          const isLate = v === 'LATE';
          const isPresent = v === 'PRESENT';
          const inProg = v === 'IN_PROGRESS';
          const lbl = isPresent ? (isAr ? 'حاضر' : 'Present') : isLate ? (isAr ? 'متأخر' : 'Late') : inProg ? (isAr ? 'قيد العمل' : 'Working') : (isAr ? (v || 'مسجل') : (v || 'Logged'));
          const col = isPresent ? 'green' : isLate ? 'amber' : inProg ? 'blue' : 'gray';
          return badge(lbl, col);
        }},
        { key: 'late_minutes', label: isAr ? 'الملاحظات' : 'Notes', render: (v, row) => {
          if (v > 0) return el('span', { style: 'color:var(--red);font-size:12px' }, isAr ? `تأخير ${v} د` : `Late ${v}m`);
          if (row.early_leave_minutes > 0) return el('span', { style: 'color:var(--amber);font-size:12px' }, isAr ? `خروج مبكر ${row.early_leave_minutes} د` : `Early leave ${row.early_leave_minutes}m`);
          return el('span', { style: 'color:var(--green);font-size:12px' }, isAr ? 'منضبط' : 'On track');
        }},
      ], filtered));
    } catch (e) {
      tableWrap.replaceChildren(errorState((isAr ? 'تعذر تحميل الحضور: ' : 'Failed to load attendance: ') + e.message));
    }
  }

  refreshAttendance();
}

// ----------------------------------------------------
// TAB 3: ATTENDANCE CORRECTIONS QUEUE
// ----------------------------------------------------
let selectedCorrectionStatus = 'ALL';

async function renderCorrectionsTab(container, canManage) {
  container.innerHTML = '';

  const filterSelect = el('select', {
    id: 'corr-status-filter',
    class: 'select',
    onchange: (e) => { selectedCorrectionStatus = e.target.value; refreshCorrections(); }
  }, [
    el('option', { value: 'ALL', selected: selectedCorrectionStatus === 'ALL' }, '📋 كل طلبات التصحيح (ALL)'),
    el('option', { value: 'PENDING', selected: selectedCorrectionStatus === 'PENDING' }, '⏳ قيد المراجعة (PENDING)'),
    el('option', { value: 'APPROVED', selected: selectedCorrectionStatus === 'APPROVED' }, '✅ معتمدة (APPROVED)'),
    el('option', { value: 'REJECTED', selected: selectedCorrectionStatus === 'REJECTED' }, '❌ مرفوضة (REJECTED)'),
  ]);

  const infoBanner = el('div', {
    style: 'background:var(--soft);border:1px solid var(--border);border-radius:10px;padding:12px 16px;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;font-size:12.5px;color:var(--text)'
  }, [
    el('div', { style: 'display:flex;align-items:center;gap:8px' }, [
      el('span', { style: 'font-size:16px' }, '⏱️'),
      el('span', {}, [
        el('b', {}, 'أثر اعتماد تصحيح الحضور: '),
        el('span', {}, 'يُعدل وقت الحضور الفعلي في سجل الحضور فورياً ويُعاد احتساب ساعات العمل والتأخير.')
      ])
    ]),
    el('div', { id: 'corr-quick-filters', style: 'display:flex;gap:6px' })
  ]);

  const metricsWrap = el('div', { class: 'cards', id: 'corr-metrics', style: 'margin-bottom:16px' });
  const tableWrap = el('div', { id: 'corr-table-wrap' }, [loadingState('جاري تحميل طابور التصحيحات...')]);

  container.append(infoBanner, metricsWrap, tableWrap);

  async function refreshCorrections() {
    tableWrap.replaceChildren(loadingState('جاري تحميل طابور وسجل التصحيحات...'));

    try {
      const { data: [analyticsList, timekeepingList], failed } = await loadSources([
        { label: 'سجل التصحيحات', get: () => api.get('/analytics/attendance/corrections?status_filter=ALL') },
        { label: 'طابور المراجعة', get: () => api.get('/timekeeping/corrections') },
      ]);

      const mappedTk = (timekeepingList || []).map((r) => ({
        id: r.id,
        source: 'timekeeping',
        courier_id: r.courier_id,
        courier_name: r.courier_name || `سائق #${r.courier_id}`,
        status: r.status,
        reason: r.reason,
        original_check_in: null,
        corrected_check_in: r.requested_check_in,
        corrected_check_out: r.requested_check_out,
        requested_at: r.created_at || r.decided_at,
        review_note: r.decision_note,
      }));

      const combined = [...(analyticsList || [])];
      for (const tk of mappedTk) {
        if (!combined.some((c) => c.id === tk.id && c.courier_id === tk.courier_id)) {
          combined.push(tk);
        }
      }

      const all = combined;
      const pendingCount = all.filter((c) => c.status === 'PENDING').length;
      const approvedCount = all.filter((c) => c.status === 'APPROVED').length;
      const rejectedCount = all.filter((c) => c.status === 'REJECTED').length;

      // Quick filter pills
      const quickFiltersWrap = document.getElementById('corr-quick-filters');
      if (quickFiltersWrap) {
        quickFiltersWrap.innerHTML = '';
        [
          { id: 'ALL', label: 'الكل', count: all.length, color: 'blue' },
          { id: 'PENDING', label: 'قيد المراجعة', count: pendingCount, color: 'amber' },
          { id: 'APPROVED', label: 'المعتمدة', count: approvedCount, color: 'green' },
          { id: 'REJECTED', label: 'المرفوضة', count: rejectedCount, color: 'red' },
        ].forEach(f => {
          const isActive = selectedCorrectionStatus === f.id;
          quickFiltersWrap.append(el('button', {
            class: `btn btn-small ${isActive ? 'btn-primary' : 'btn-ghost'}`,
            style: isActive ? '' : 'border:1px solid var(--border)',
            onclick: () => {
              selectedCorrectionStatus = f.id;
              filterSelect.value = f.id;
              refreshCorrections();
            }
          }, `${f.label} (${f.count})`));
        });
      }

      // Interactive Metric Cards
      metricsWrap.innerHTML = '';
      const createCorrCard = (count, title, color, statusKey, hint) => {
        const isSel = selectedCorrectionStatus === statusKey;
        return el('div', {
          style: `cursor:pointer;transition:all .15s ease;border:${isSel ? '2px solid var(--primary)' : '1px solid var(--border)'};border-radius:12px;background:${isSel ? 'var(--soft)' : 'var(--card)'};padding:2px`,
          onclick: () => {
            selectedCorrectionStatus = statusKey;
            filterSelect.value = statusKey;
            refreshCorrections();
          }
        }, [metricCard(count, title, color, null, hint)]);
      };

      metricsWrap.append(
        createCorrCard(all.length, 'إجمالي طلبات التصحيح', 'blue', 'ALL', 'اضغط لعرض كافة الطلبات'),
        createCorrCard(pendingCount, 'قيد المراجعة والبت', pendingCount ? 'alert' : 'blue', 'PENDING', 'بانتظار قرار الإدارة'),
        createCorrCard(approvedCount, 'معتمد ومعدل بالحضور', 'trend', 'APPROVED', 'مصححة ومسجلة في السجل'),
        createCorrCard(rejectedCount, 'مرفوض', 'normal', 'REJECTED', 'الطلبات المرفوضة')
      );

      let rows = all;
      if (selectedCorrectionStatus !== 'ALL') {
        rows = all.filter((c) => c.status === selectedCorrectionStatus);
      }

      const warning = partialLoadWarning(failed);

      if (!rows.length) {
        // "Nothing to review" is only true when everything actually loaded.
        tableWrap.replaceChildren(...[
          warning,
          failed.length
            ? emptyState('لم تُحمّل كل المصادر — لا يمكن تأكيد أن الطابور فارغ.')
            : emptyState('لا توجد طلبات تصحيح حضور ضمن هذه التصفية.'),
        ].filter(Boolean));
        return;
      }

      tableWrap.replaceChildren(...[warning, table([
        { key: 'id', label: '#', render: (v) => `#${v}` },
        { key: 'courier_name', label: 'السائق', render: (v, row) => el('b', { text: v || `سائق #${row.courier_id}` }) },
        { key: 'original_check_in', label: 'الدخول الأصلي', render: (v) => v ? new Date(v).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '—' },
        { key: 'corrected_check_in', label: 'الدخول المصحح', render: (v) => v ? el('b', { style: 'color:var(--green)', text: new Date(v).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) }) : '—' },
        { key: 'reason', label: 'سبب التصحيح', render: (v) => el('span', { style: 'font-size:13px', text: v || '—' }) },
        { key: 'requested_at', label: 'تاريخ الطلب', render: (v) => v ? new Date(v).toLocaleDateString('en-GB') : '—' },
        { key: 'status', label: 'الحالة', render: (v) => {
          const isPending = v === 'PENDING';
          const isApp = v === 'APPROVED';
          return el('span', { class: `badge badge-${isPending ? 'amber' : isApp ? 'green' : 'alert'}` }, isPending ? '⏳ قيد المراجعة' : isApp ? '✅ معتمد' : '❌ مرفوض');
        }},
        { key: 'actions', label: 'الإجراء والملاحظات', render: (_, row) => {
          if (row.status === 'PENDING' && canManage) {
            return el('button', {
              class: 'btn btn-blue btn-small',
              onclick: () => openReviewCorrectionModal(row, refreshCorrections)
            }, 'مراجعة واتخاذ قرار');
          }
          if (row.review_note) {
            return el('small', { style: 'color:var(--text-muted)' }, row.review_note);
          }
          return '—';
        }},
      ], rows)].filter(Boolean));
    } catch (e) {
      tableWrap.replaceChildren(errorState('تعذر تحميل تصحيحات الحضور: ' + e.message));
    }
  }

  refreshCorrections();
}

function openReviewCorrectionModal(corr, onReviewed) {
  const content = el('div', { class: 'review-correction-modal' }, [
    el('div', { class: 'card', style: 'margin-bottom:16px;background:var(--surface-sunken)' }, [
      el('div', { style: 'display:flex;justify-content:space-between;margin-bottom:8px' }, [
        el('b', { text: `طلب تصحيح #${corr.id}` }),
        badge('قيد المراجعة', 'amber'),
      ]),
      el('p', { style: 'margin:4px 0' }, `👤 السائق: ${corr.courier_name || '#' + corr.courier_id}`),
      el('p', { style: 'margin:4px 0' }, `⏱️ الدخول الأصلي: ${corr.original_check_in ? new Date(corr.original_check_in).toLocaleString('en-US') : 'غير مسجل'}`),
      el('p', { style: 'margin:4px 0;color:var(--green)' }, `✨ الدخول المطلوب: ${corr.corrected_check_in ? new Date(corr.corrected_check_in).toLocaleString('en-US') : 'غير محدد'}`),
      el('p', { style: 'margin:4px 0' }, `📝 سبب الطلب: ${corr.reason || '—'}`),
    ]),
    el('div', { style: 'margin-bottom:16px' }, [
      el('label', { text: 'ملاحظة المراجع (اختياري):', style: 'display:block;margin-bottom:4px;font-weight:600' }),
      el('textarea', {
        id: 'correction-review-note',
        rows: 3,
        style: 'width:100%;box-sizing:border-box;padding:8px;border-radius:6px;border:1px solid var(--border)',
        placeholder: 'أدخل سبب القبول أو الرفض...'
      }),
    ]),
    el('div', { style: 'display:flex;gap:8px;justify-content:flex-end' }, [
      el('button', {
        class: 'btn btn-green',
        onclick: async () => submitDecision(corr, 'APPROVED', m, onReviewed)
      }, '✅ اعتماد التصحيح'),
      el('button', {
        class: 'btn btn-red',
        onclick: async () => submitDecision(corr, 'REJECTED', m, onReviewed)
      }, '❌ رفض التصحيح'),
    ]),
    el('div', { id: 'corr-decision-msg', class: 'msg', style: 'margin-top:8px' }),
  ]);

  const m = modal('مراجعة طلب تصحيح الحضور', content);
}

async function submitDecision(corr, decision, modalInstance, onDone) {
  const msg = document.getElementById('corr-decision-msg');
  const note = document.getElementById('correction-review-note')?.value.trim() || null;
  msg.textContent = 'جاري حفظ القرار...';
  try {
    if (corr && corr.source === 'timekeeping') {
      await api.post(`/timekeeping/corrections/${corr.id}/decide`, {
        decision,
        note,
      });
    } else {
      const id = typeof corr === 'object' ? corr.id : corr;
      await api.post(`/analytics/attendance/corrections/${id}/review`, {
        decision,
        note,
      });
    }
    msg.style.color = 'var(--green)';
    msg.textContent = decision === 'APPROVED' ? '✅ تم اعتماد التصحيح وتحديث سجل الحضور.' : '❌ تم رفض طلب التصحيح.';
    setTimeout(() => {
      modalInstance.remove();
      if (onDone) onDone();
    }, 800);
  } catch (e) {
    msg.style.color = 'var(--red)';
    msg.textContent = '❌ تعذر إتمام الإجراء: ' + e.message;
  }
}

// ----------------------------------------------------
// TAB 4: OVERTIME APPROVALS QUEUE (Timekeeping W1-E4)
// ----------------------------------------------------
let selectedOvertimeStatus = 'ALL';

async function renderOvertimeTab(container, headerActions, canManage) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';

  const filterSelect = el('select', {
    id: 'overtime-status-filter',
    class: 'select',
    onchange: (e) => {
      selectedOvertimeStatus = e.target.value;
      refreshOvertime();
    }
  }, [
    el('option', { value: 'ALL', ...(selectedOvertimeStatus === 'ALL' ? { selected: 'selected' } : {}) }, isAr ? '📋 كل طلبات الإضافي (ALL)' : '📋 All Overtime (ALL)'),
    el('option', { value: 'PENDING', ...(selectedOvertimeStatus === 'PENDING' ? { selected: 'selected' } : {}) }, isAr ? '⏳ قيد المراجعة (PENDING)' : '⏳ Pending Review (PENDING)'),
    el('option', { value: 'APPROVED', ...(selectedOvertimeStatus === 'APPROVED' ? { selected: 'selected' } : {}) }, isAr ? '✅ معتمدة (APPROVED)' : '✅ Approved (APPROVED)'),
    el('option', { value: 'REJECTED', ...(selectedOvertimeStatus === 'REJECTED' ? { selected: 'selected' } : {}) }, isAr ? '❌ مرفوضة (REJECTED)' : '❌ Rejected (REJECTED)'),
  ]);

  headerActions.append(
    filterSelect,
    el('button', { class: 'btn btn-ghost', onclick: () => refreshOvertime() }, isAr ? '↻ تحديث' : '↻ Refresh')
  );

  const infoBanner = el('div', {
    style: 'background:var(--soft);border:1px solid var(--border);border-radius:10px;padding:12px 16px;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;font-size:12.5px;color:var(--text)'
  }, [
    el('div', { style: 'display:flex;align-items:center;gap:8px' }, [
      el('span', { style: 'font-size:16px' }, '⏰'),
      el('span', {}, [
        el('b', {}, isAr ? 'اعتماد العمل الإضافي: ' : 'Overtime Approval: '),
        el('span', {}, isAr ? 'يتم احتساب الدقائق المعتمدة وإضافتها تلقائياً إلى بنود مسير الرواتب الشهرية.' : 'Approved overtime minutes are automatically calculated and added to monthly payroll additions.')
      ])
    ]),
    el('div', { id: 'ot-quick-filters', style: 'display:flex;gap:6px' })
  ]);

  const metricsWrap = el('div', { class: 'cards', id: 'ot-metrics', style: 'margin-bottom:16px' });
  const tableWrap = el('div', { id: 'ot-table-wrap' }, [loadingState(isAr ? 'جاري تحميل طابور العمل الإضافي...' : 'Loading overtime queue...')]);

  container.append(infoBanner, metricsWrap, tableWrap);

  async function refreshOvertime() {
    tableWrap.replaceChildren(loadingState(isAr ? 'جاري تحديث البيانات...' : 'Updating data...'));
    try {
      const allRows = await api.get('/timekeeping/overtime');
      const all = allRows || [];
      const pendingCount = all.filter(r => r.status === 'PENDING').length;
      const approvedCount = all.filter(r => r.status === 'APPROVED').length;
      const rejectedCount = all.filter(r => r.status === 'REJECTED').length;
      const approvedMinutes = all.filter(r => r.status === 'APPROVED').reduce((sum, r) => sum + (Number(r.approved_minutes) || 0), 0);

      // Quick filter buttons
      const quickFiltersWrap = document.getElementById('ot-quick-filters');
      if (quickFiltersWrap) {
        quickFiltersWrap.innerHTML = '';
        [
          { id: 'ALL', label: isAr ? 'الكل' : 'All', count: all.length, color: 'blue' },
          { id: 'PENDING', label: isAr ? 'قيد المراجعة' : 'Pending', count: pendingCount, color: 'amber' },
          { id: 'APPROVED', label: isAr ? 'المعتمدة' : 'Approved', count: approvedCount, color: 'green' },
          { id: 'REJECTED', label: isAr ? 'المرفوضة' : 'Rejected', count: rejectedCount, color: 'red' },
        ].forEach(f => {
          const isActive = selectedOvertimeStatus === f.id;
          quickFiltersWrap.append(el('button', {
            class: `btn btn-small ${isActive ? 'btn-primary' : 'btn-ghost'}`,
            style: isActive ? '' : 'border:1px solid var(--border)',
            onclick: () => {
              selectedOvertimeStatus = f.id;
              filterSelect.value = f.id;
              refreshOvertime();
            }
          }, `${f.label} (${f.count})`));
        });
      }

      // Metric Cards
      metricsWrap.innerHTML = '';
      const createOtCard = (count, title, color, statusKey, hint) => {
        const isSel = selectedOvertimeStatus === statusKey;
        return el('div', {
          style: `cursor:pointer;transition:all .15s ease;border:${isSel ? '2px solid var(--primary)' : '1px solid var(--border)'};border-radius:12px;background:${isSel ? 'var(--soft)' : 'var(--card)'};padding:2px`,
          onclick: () => {
            selectedOvertimeStatus = statusKey;
            filterSelect.value = statusKey;
            refreshOvertime();
          }
        }, [metricCard(count, title, color, null, hint)]);
      };

      metricsWrap.append(
        createOtCard(all.length, isAr ? 'إجمالي طلبات الإضافي' : 'Total Requests', 'blue', 'ALL', isAr ? 'اضغط لعرض كافة الطلبات' : 'Click to view all'),
        createOtCard(pendingCount, isAr ? 'قيد المراجعة' : 'Pending Review', pendingCount ? 'alert' : 'blue', 'PENDING', isAr ? 'بانتظار قرار الإدارة' : 'Awaiting decision'),
        createOtCard(approvedCount, isAr ? 'طلبات معتمدة' : 'Approved Requests', 'trend', 'APPROVED', isAr ? `${Math.round(approvedMinutes / 60 * 10) / 10} ساعة معتمدة` : `${Math.round(approvedMinutes / 60 * 10) / 10} hrs approved`),
        createOtCard(rejectedCount, isAr ? 'مرفوضة' : 'Rejected', 'normal', 'REJECTED', isAr ? 'الطلبات المرفوضة' : 'Rejected requests')
      );

      let filtered = all;
      if (selectedOvertimeStatus !== 'ALL') {
        filtered = all.filter(r => r.status === selectedOvertimeStatus);
      }

      if (!filtered.length) {
        tableWrap.replaceChildren(emptyState(isAr ? 'لا توجد طلبات عمل إضافي ضمن هذه التصفية.' : 'No overtime requests found matching this filter.'));
        return;
      }

      tableWrap.replaceChildren(table([
        { key: 'id', label: '#', render: (v) => `#${v}` },
        { key: 'courier_name', label: isAr ? 'السائق' : 'Driver', render: (v, row) => el('b', { text: v || (isAr ? `سائق #${row.courier_id}` : `Driver #${row.courier_id}`) }) },
        { key: 'overtime_date', label: isAr ? 'التاريخ' : 'Date', render: (v) => v || '—' },
        { key: 'requested_minutes', label: isAr ? 'الوقت المطلوب' : 'Requested', render: (v) => `${v} ${isAr ? 'دقيقة' : 'min'} (${Math.round((v / 60) * 10) / 10} ${isAr ? 'س' : 'hr'})` },
        { key: 'approved_minutes', label: isAr ? 'الوقت المعتمد' : 'Approved', render: (v, row) => row.status === 'APPROVED' ? el('b', { style: 'color:var(--green)', text: `${v || 0} ${isAr ? 'دقيقة' : 'min'}` }) : '—' },
        { key: 'status', label: isAr ? 'الحالة' : 'Status', render: (v) => {
          const isPending = v === 'PENDING';
          const isApp = v === 'APPROVED';
          return el('span', { class: `badge badge-${isPending ? 'amber' : isApp ? 'green' : 'alert'}` }, isPending ? (isAr ? '⏳ قيد المراجعة' : '⏳ Pending') : isApp ? (isAr ? '✅ معتمد' : '✅ Approved') : (isAr ? '❌ مرفوض' : '❌ Rejected'));
        }},
        { key: 'actions', label: isAr ? 'الإجراء' : 'Actions', render: (_, row) => {
          if (row.status === 'PENDING' && canManage) {
            return el('button', {
              class: 'btn btn-blue btn-small',
              onclick: () => openReviewOvertimeModal(row, refreshOvertime)
            }, isAr ? 'مراجعة واتخاذ قرار' : 'Review & Decide');
          }
          return '—';
        }},
      ], filtered));
    } catch (e) {
      tableWrap.replaceChildren(errorState((isAr ? 'تعذر تحميل طلبات العمل الإضافي: ' : 'Failed to load overtime: ') + e.message));
    }
  }

  refreshOvertime();
}

function openReviewOvertimeModal(ot, onReviewed) {
  const isAr = getLang() === 'ar';
  const content = el('div', { class: 'review-overtime-modal' }, [
    el('div', { class: 'card', style: 'margin-bottom:16px;background:var(--surface-sunken)' }, [
      el('div', { style: 'display:flex;justify-content:space-between;margin-bottom:8px' }, [
        el('b', { text: `${isAr ? 'طلب عمل إضافي' : 'Overtime Request'} #${ot.id}` }),
        badge(isAr ? 'قيد المراجعة' : 'Pending Review', 'amber'),
      ]),
      el('p', { style: 'margin:4px 0' }, `👤 ${isAr ? 'السائق' : 'Driver'}: ${ot.courier_name || '#' + ot.courier_id}`),
      el('p', { style: 'margin:4px 0' }, `📅 ${isAr ? 'تاريخ العمل الإضافي' : 'Date'}: ${ot.overtime_date}`),
      el('p', { style: 'margin:4px 0;font-weight:700' }, `⏱️ ${isAr ? 'الدقائق المطلوبة' : 'Requested Minutes'}: ${ot.requested_minutes} ${isAr ? 'دقيقة' : 'minutes'}`),
    ]),
    el('div', { style: 'margin-bottom:14px' }, [
      el('label', { text: isAr ? 'الدقائق المعتمدة للعمل الإضافي:' : 'Approved Overtime Minutes:', style: 'display:block;margin-bottom:4px;font-weight:600' }),
      el('input', {
        type: 'number',
        id: 'ot-approved-minutes',
        value: ot.requested_minutes,
        min: 1,
        style: 'width:100%;box-sizing:border-box;padding:8px;border-radius:6px;border:1px solid var(--border)'
      }),
    ]),
    el('div', { style: 'display:flex;gap:8px;justify-content:flex-end' }, [
      el('button', {
        class: 'btn btn-green',
        onclick: async () => {
          const mins = parseInt(document.getElementById('ot-approved-minutes')?.value || ot.requested_minutes, 10);
          submitOvertimeDecision(ot.id, 'APPROVED', mins, m, onReviewed);
        }
      }, isAr ? '✅ اعتماد الإضافي' : '✅ Approve Overtime'),
      el('button', {
        class: 'btn btn-red',
        onclick: async () => submitOvertimeDecision(ot.id, 'REJECTED', 0, m, onReviewed)
      }, isAr ? '❌ رفض الطلب' : '❌ Reject Request'),
    ]),
    el('div', { id: 'ot-decision-msg', class: 'msg', style: 'margin-top:8px' }),
  ]);

  const m = modal(isAr ? 'مراجعة طلب العمل الإضافي' : 'Review Overtime Request', content);
}

async function submitOvertimeDecision(overtimeId, decision, approvedMinutes, modalInstance, onDone) {
  const isAr = getLang() === 'ar';
  const msg = document.getElementById('ot-decision-msg');
  if (msg) msg.textContent = isAr ? 'جاري حفظ القرار...' : 'Saving decision...';
  try {
    await api.post(`/timekeeping/overtime/${overtimeId}/decide`, {
      decision,
      approved_minutes: approvedMinutes,
    });
    if (msg) {
      msg.style.color = 'var(--green)';
      msg.textContent = decision === 'APPROVED' ? (isAr ? '✅ تم اعتماد العمل الإضافي بنجاح.' : '✅ Overtime approved successfully.') : (isAr ? '❌ تم رفض الطلب.' : '❌ Request rejected.');
    }
    setTimeout(() => {
      modalInstance.remove();
      if (onDone) onDone();
    }, 800);
  } catch (e) {
    if (msg) {
      msg.style.color = 'var(--red)';
      msg.textContent = (isAr ? '❌ تعذر إتمام الإجراء: ' : '❌ Failed: ') + e.message;
    }
  }
}

// ----------------------------------------------------
// TAB 4: LEAVE APPROVALS QUEUE (Batch 2B)
// ----------------------------------------------------
let selectedLeaveStatus = 'ALL';

async function renderLeavesTab(container, headerActions, canManage) {
  container.innerHTML = '';

  const filterSelect = el('select', {
    id: 'leave-status-filter',
    class: 'select',
    onchange: (e) => {
      selectedLeaveStatus = e.target.value;
      refreshLeaves();
    }
  }, [
    el('option', { value: 'ALL', ...(selectedLeaveStatus === 'ALL' ? { selected: 'selected' } : {}) }, '📋 جميع طلبات الإجازات (ALL)'),
    el('option', { value: 'PENDING', ...(selectedLeaveStatus === 'PENDING' ? { selected: 'selected' } : {}) }, '⏳ قيد المراجعة (PENDING)'),
    el('option', { value: 'APPROVED', ...(selectedLeaveStatus === 'APPROVED' ? { selected: 'selected' } : {}) }, '✅ معتمدة ومسجلة (APPROVED)'),
    el('option', { value: 'REJECTED', ...(selectedLeaveStatus === 'REJECTED' ? { selected: 'selected' } : {}) }, '❌ مرفوضة (REJECTED)'),
  ]);

  headerActions.append(
    filterSelect,
    el('button', { class: 'btn btn-ghost', onclick: () => refreshLeaves() }, '↻ تحديث')
  );

  const infoBanner = el('div', {
    style: 'background:var(--soft);border:1px solid var(--border);border-radius:10px;padding:12px 16px;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;font-size:12.5px;color:var(--text)'
  }, [
    el('div', { style: 'display:flex;align-items:center;gap:8px' }, [
      el('span', { style: 'font-size:16px' }, '🌴'),
      el('span', {}, [
        el('b', {}, 'أثر اعتماد الإجازة: '),
        el('span', {}, 'تُسجل في سجل الحضور (فلا يُحسب غائباً) + تُوثق في ملف السائق (Rider 360) + تظهر معتمدة في تطبيق السائق.')
      ])
    ]),
    el('div', { id: 'leave-quick-filters', style: 'display:flex;gap:6px' })
  ]);

  const metricsWrap = el('div', { class: 'cards', id: 'central-leave-metrics', style: 'margin-bottom:16px' });
  const tableWrap = el('div', { id: 'central-leave-table-wrap' }, [loadingState('جاري تحميل طابور وسجل طلبات الإجازات...')]);

  container.append(infoBanner, metricsWrap, tableWrap);

  async function refreshLeaves() {
    tableWrap.replaceChildren(loadingState('جاري تحديث البيانات...'));
    try {
      const [all, filtered] = await Promise.all([
        api.get('/leave/requests?status_filter=ALL'),
        api.get(`/leave/requests?status_filter=${selectedLeaveStatus}`),
      ]);

      const allList = all || [];
      const pendingCount = allList.filter(r => r.status === 'PENDING' || r.status === 'SUPERVISOR_APPROVED').length;
      const approvedCount = allList.filter(r => r.status === 'APPROVED').length;
      const rejectedCount = allList.filter(r => r.status === 'REJECTED').length;

      // Update quick filter buttons
      const quickFiltersWrap = document.getElementById('leave-quick-filters');
      if (quickFiltersWrap) {
        quickFiltersWrap.innerHTML = '';
        [
          { id: 'ALL', label: 'الكل', count: allList.length, color: 'blue' },
          { id: 'PENDING', label: 'قيد المراجعة', count: pendingCount, color: 'amber' },
          { id: 'APPROVED', label: 'المعتمدة', count: approvedCount, color: 'green' },
          { id: 'REJECTED', label: 'المرفوضة', count: rejectedCount, color: 'red' },
        ].forEach(f => {
          const isActive = selectedLeaveStatus === f.id;
          quickFiltersWrap.append(el('button', {
            class: `btn btn-small ${isActive ? 'btn-primary' : 'btn-ghost'}`,
            style: isActive ? '' : 'border:1px solid var(--border)',
            onclick: () => {
              selectedLeaveStatus = f.id;
              filterSelect.value = f.id;
              refreshLeaves();
            }
          }, `${f.label} (${f.count})`));
        });
      }

      // Interactive Metric Cards
      metricsWrap.innerHTML = '';
      const createMetricCard = (count, title, color, statusKey, hint) => {
        const isSel = selectedLeaveStatus === statusKey;
        return el('div', {
          style: `cursor:pointer;transition:all .15s ease;border:${isSel ? '2px solid var(--primary)' : '1px solid var(--border)'};border-radius:12px;background:${isSel ? 'var(--soft)' : 'var(--card)'};padding:2px`,
          onclick: () => {
            selectedLeaveStatus = statusKey;
            filterSelect.value = statusKey;
            refreshLeaves();
          }
        }, [metricCard(count, title, color, null, hint)]);
      };

      metricsWrap.append(
        createMetricCard(allList.length, 'إجمالي طلبات الإجازة', 'blue', 'ALL', 'اضغط لعرض كافة الطلبات'),
        createMetricCard(pendingCount, 'قيد المراجعة والبت', pendingCount ? 'alert' : 'blue', 'PENDING', 'بانتظار قرار الإدارة'),
        createMetricCard(approvedCount, 'معتمدة ومسجلة بالسجل', 'trend', 'APPROVED', 'مسجلة في الحضور وملف السائق'),
        createMetricCard(rejectedCount, 'مرفوضة مع السبب', 'normal', 'REJECTED', 'الطلبات المرفوضة مع إبداء السبب')
      );

      const rows = filtered || [];
      if (!rows.length) {
        tableWrap.replaceChildren(emptyState(`لا توجد طلبات إجازة مطابقة لفلتر «${filterSelect.options[filterSelect.selectedIndex]?.text || selectedLeaveStatus}».`));
        return;
      }

      tableWrap.replaceChildren(table([
        { key: 'id', label: '#', render: (v) => `#${v}` },
        { key: 'courier_name', label: 'السائق', render: (v, r) => el('div', {}, [
          el('a', {
            href: '#',
            style: 'color:var(--primary);font-weight:700;text-decoration:none;display:block',
            onclick: (e) => {
              e.preventDefault();
              window.__rider360InitialId = r.courier_id;
              window.__rider360InitialTab = 'leave';
              go('rider360');
            }
          }, v || `سائق #${r.courier_id}`),
          el('small', { style: 'color:var(--muted);font-size:11px' }, 'ملف السائق ↗')
        ]) },
        { key: 'leave_type_name', label: 'نوع الإجازة', render: (v) => v || 'إجازة سنوية' },
        { key: 'dates', label: 'فترة الإجازة', render: (_, r) => `${r.from_date || '—'} ➔ ${r.to_date || '—'}` },
        { key: 'days', label: 'المدة', render: (v) => el('b', {}, `${v || 1} يوم`) },
        { key: 'reason', label: 'سبب الطلب', render: (v) => el('span', { style: 'font-size:12px;color:var(--text)' }, v || '—') },
        { key: 'status', label: 'الحالة', render: (v) => {
          if (v === 'APPROVED') return el('span', { class: 'badge badge-green' }, '✅ معتمد');
          if (v === 'PENDING') return el('span', { class: 'badge badge-amber' }, '⏳ قيد المراجعة');
          if (v === 'SUPERVISOR_APPROVED') return el('span', { class: 'badge badge-amber' }, '🤝 معتمد مبدئياً');
          return el('span', { class: 'badge badge-alert' }, '❌ مرفوض');
        }},
        { key: 'decision_note', label: 'قرار الإدارة والملاحظات', render: (_, r) => {
          if (r.status === 'APPROVED') {
            return el('div', { style: 'font-size:11px;color:#16a34a' }, [
              el('b', {}, '✓ مسجلة بالحضور وملف السائق'),
              r.comment ? el('div', { style: 'color:var(--muted)' }, r.comment) : null
            ].filter(Boolean));
          }
          if (r.status === 'REJECTED') {
            return el('div', { style: 'font-size:11px;color:#dc2626' }, r.comment || 'تم رفض الطلب');
          }
          return el('span', { style: 'color:var(--muted);font-size:11px' }, 'بانتظار القرار');
        }},
        { key: 'actions', label: 'الإجراء', render: (_, r) => {
          if (canManage && (r.status === 'PENDING' || r.status === 'SUPERVISOR_APPROVED')) {
            return el('button', {
              class: 'btn btn-blue btn-small',
              onclick: () => openCentralLeaveDecisionModal(r, () => refreshLeaves())
            }, '⚡ اتخاذ قرار');
          }
          return el('span', { style: 'color:var(--muted);font-size:12px' }, 'مكتمل');
        }},
      ], rows));
    } catch (e) {
      tableWrap.replaceChildren(errorState('تعذر تحميل طلبات الإجازات: ' + e.message));
    }
  }

  refreshLeaves();
}

function openCentralLeaveDecisionModal(req, onReviewed) {
  const content = el('div', { class: 'review-leave-modal', style: 'direction:rtl' }, [
    el('div', { class: 'card', style: 'margin-bottom:16px;background:var(--soft);border:1px solid var(--border);border-radius:10px;padding:12px' }, [
      el('div', { style: 'display:flex;justify-content:space-between;margin-bottom:8px' }, [
        el('b', { text: `طلب إجازة #${req.id}` }),
        badge('قيد المراجعة', 'amber'),
      ]),
      el('p', { style: 'margin:4px 0;font-size:13px' }, `👤 السائق: ${req.courier_name || '#' + req.courier_id}`),
      el('p', { style: 'margin:4px 0;font-size:13px' }, `🌴 نوع الإجازة: ${req.leave_type_name || 'إجازة سنوية'}`),
      el('p', { style: 'margin:4px 0;font-size:13px' }, `📅 الفترة: من ${req.from_date} إلى ${req.to_date} (${req.days} أيام)`),
      el('p', { style: 'margin:4px 0;font-size:13px' }, `📝 سبب الإجازة: ${req.reason || '—'}`),
    ]),
    el('div', { style: 'margin-bottom:16px' }, [
      el('label', { text: 'ملاحظة الاعتماد أو الرفض (تظهر للمندوب):', style: 'display:block;margin-bottom:4px;font-weight:700;font-size:12px' }),
      el('textarea', {
        id: 'leave-review-note',
        rows: 3,
        style: 'width:100%;box-sizing:border-box;padding:8px 12px;border-radius:8px;border:1px solid var(--border);font-size:13px',
        placeholder: 'أدخل ملاحظات إدارية أو سبب الرفض...'
      }),
    ]),
    el('div', { style: 'display:flex;gap:8px;justify-content:flex-end' }, [
      el('button', {
        class: 'btn btn-green',
        style: 'background:#16a34a;color:#fff;font-weight:700;padding:8px 16px;border-radius:8px;border:0;cursor:pointer',
        onclick: async () => submitCentralLeaveDecision(req.id, 'APPROVED', m, onReviewed)
      }, '✅ اعتماد الإجازة'),
      el('button', {
        class: 'btn btn-red',
        style: 'background:#dc2626;color:#fff;font-weight:700;padding:8px 16px;border-radius:8px;border:0;cursor:pointer',
        onclick: async () => submitCentralLeaveDecision(req.id, 'REJECTED', m, onReviewed)
      }, '❌ رفض الإجازة'),
    ]),
    el('div', { id: 'leave-central-dec-msg', class: 'msg', style: 'margin-top:8px' }),
  ]);

  const m = modal('مراجعة طلب الإجازة واتخاذ القرار', content);
}

async function submitCentralLeaveDecision(reqId, decision, modalInstance, onDone) {
  const msg = document.getElementById('leave-central-dec-msg');
  const comment = document.getElementById('leave-review-note')?.value.trim() || null;
  msg.textContent = 'جاري حفظ القرار...';
  try {
    await api.post(`/leave/requests/${reqId}/admin-decide`, {
      decision,
      comment,
    });
    msg.style.color = 'var(--green)';
    msg.textContent = decision === 'APPROVED' ? '✅ تم اعتماد الإجازة وتوثيقها بسجل الحضور وملف السائق.' : '❌ تم رفض طلب الإجازة.';
    setTimeout(() => {
      modalInstance.remove();
      if (onDone) onDone();
    }, 800);
  } catch (e) {
    msg.style.color = 'var(--red)';
    msg.textContent = '❌ تعذر إتمام الإجراء: ' + e.message;
  }
}

