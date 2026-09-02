// Modern Payroll & Financial HR Operations — Frontend V2
import { api } from '../../shared/api/client.js';
import { appStore, isDeliveryPlatform } from '../../shared/state/store.js';
import { el, loadingState, emptyState, errorState, metricCard, table, button, modal, formRow, inputField, selectField, searchableSelect, aiPromptBar, escapeHtml } from '../../shared/components/ui.js';
import { openAIDrawer, getContextualPrompts } from '../shell.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

let activePayrollTab = 'ledger'; // ledger | adjustments | bonus | settlements
let selectedPayrollMonth = new Date().toISOString().slice(0, 7);

export async function loadPayroll(container) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';
  
  // 1. Header
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'العمليات المالية والمسيرات' : 'Financial Operations & Payroll'),
      el('h1', { text: isAr ? 'الرواتب والعمليات المالية' : 'Payroll & Financial Operations' })
    ]),
    el('div', { class: 'header-actions' }, [
      el('button', { class: 'btn btn-ghost', onclick: () => loadPayroll(container) }, `↻ ${t('تحديث البيانات')}`),
      el('button', { class: 'btn-ai', onclick: () => openAIDrawer(isAr ? 'تقرير الرواتب' : 'Payroll report') }, [
        el('span', { text: '✨' }),
        el('span', { text: isAr ? 'استفسار مالي ذكي' : 'Smart Financial Query' })
      ]),
    ]),
  ]));

  // 2. Contextual AI Prompt Chips
  const promptBar = aiPromptBar(getContextualPrompts('payroll'), (p) => openAIDrawer(p));
  if (promptBar) container.append(promptBar);

  // 3. Sub-Tabs Navigation
  const isPlatform = isDeliveryPlatform();
  const tabsList = [
    { id: 'ledger', label: isAr ? '💰 كشف الرواتب الشهري' : '💰 Monthly Payroll Ledger' },
    { id: 'adjustments', label: isAr ? '⚖️ السلف والخصومات والمخالفات' : '⚖️ Advances, Deductions & Penalties' },
    { id: 'bonus', label: isAr ? '🏆 خطط البونص والمتصدرين' : '🏆 Bonus Plans & Leaderboard' },
  ];
  if (isPlatform) {
    tabsList.push({ id: 'settlements', label: isAr ? '📑 تسويات مشغلي 3PL التجارية' : '📑 3PL Commercial Settlements' });
  }

  const tabsNav = el('div', { class: 'tabs', style: 'margin-bottom:16px' }, 
    tabsList.map(tab => el('button', {
      class: `tab ${activePayrollTab === tab.id ? 'active' : ''}`,
      onclick: () => {
        activePayrollTab = tab.id;
        loadPayrollTabContent(contentArea, container);
        tabsNav.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        const activeBtn = tabsNav.querySelector(`.tab:nth-child(${tabsList.findIndex(x => x.id === tab.id) + 1})`);
        if (activeBtn) activeBtn.classList.add('active');
      }
    }, tab.label))
  );
  container.append(tabsNav);

  const contentArea = el('div', { id: 'payroll-tab-content' });
  container.append(contentArea);

  loadPayrollTabContent(contentArea, container);
}

function loadPayrollTabContent(contentArea, mainContainer) {
  contentArea.innerHTML = '';
  if (activePayrollTab === 'ledger') {
    renderPayrollLedger(contentArea, mainContainer);
  } else if (activePayrollTab === 'adjustments') {
    renderAdjustments(contentArea);
  } else if (activePayrollTab === 'bonus') {
    renderBonusAndLeaderboard(contentArea);
  } else if (activePayrollTab === 'settlements') {
    renderSettlements(contentArea);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 1: كشف الرواتب والتسوية الشهرية للمناديب (MONTHLY RIDER SETTLEMENT & PAYROLL)
// ─────────────────────────────────────────────────────────────────────────────
async function renderPayrollLedger(container, mainContainer) {
  const isAr = getLang() === 'ar';
  container.append(loadingState(isAr ? 'جاري تجميع واحتساب مسير الرواتب وتسوية حسابات المناديب...' : 'Calculating monthly payroll ledger and rider settlements...'));

  try {
    const data = await api.get(`/hr/payroll?month=${selectedPayrollMonth}`).catch(async () => {
      return await api.get('/analytics/payroll/summary');
    });

    container.innerHTML = '';
    const status = (data.status || (data.finalized ? 'FINALIZED' : 'DRAFT')).toUpperCase();
    const isFinalized = status === 'FINALIZED' || data.finalized || false;
    const totals = data.totals || {};
    const rows = data.rows || data.riders || [];

    // 1. Period Workflow Stepper
    const stepperCard = el('div', { class: 'card', style: 'margin-bottom:16px;padding:16px 20px;background:var(--card);border:1px solid var(--border);border-radius:12px' }, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px' }, [
        el('div', {}, [
          el('h3', { style: 'margin:0;font-size:15px;color:var(--text);display:flex;align-items:center;gap:8px' }, [
            el('span', {}, isAr ? '📊 دورة إقفال مسير الشهر التشغيلي:' : '📊 Monthly Payroll Close Cycle:'),
            el('span', { style: 'font-family:monospace;font-size:14px;color:var(--primary)' }, selectedPayrollMonth)
          ]),
          el('p', { style: 'margin:2px 0 0 0;font-size:11px;color:var(--muted)' }, isAr ? 'التحول من المسودة الحية ➔ المراجعة ➔ الاعتماد ➔ الإقفال باللقطة المالية (Snapshot)' : 'Live Draft ➔ Review & Audit ➔ Approval ➔ Finalized Financial Snapshot')
        ]),
        el('div', { style: 'display:flex;align-items:center;gap:8px' }, [
          el('span', { class: `badge badge-${status === 'FINALIZED' ? 'green' : (status === 'APPROVED' ? 'green' : (status === 'UNDER_REVIEW' ? 'blue' : 'amber'))}`, style: 'font-size:12px;padding:4px 10px;font-weight:700' },
            status === 'FINALIZED' 
              ? (isAr ? '🔒 مقفل ومحفوظ بلقطة نهائية' : '🔒 Finalized & Locked Snapshot') 
              : (status === 'APPROVED' ? (isAr ? '✅ معتمد من الإدارة' : '✅ Management Approved') : (status === 'UNDER_REVIEW' ? (isAr ? '⏳ قيد المراجعة والتدقيق' : '⏳ Under Review & Audit') : (isAr ? '✏️ مسودة تشغيلية حية' : '✏️ Live Operational Draft')))
          )
        ])
      ]),

      // Visual Stepper
      el('div', { style: 'display:flex;align-items:center;gap:8px;margin-bottom:12px;overflow-x:auto;padding-bottom:4px' }, [
        renderStepBadge(isAr ? '1. مسودة الحساب (DRAFT)' : '1. Draft Ledger', status === 'DRAFT' || status === 'UNDER_REVIEW' || status === 'APPROVED' || status === 'FINALIZED', status === 'DRAFT'),
        el('span', { style: 'color:var(--muted)' }, '➔'),
        renderStepBadge(isAr ? '2. مراجعة وتدقيق (REVIEW)' : '2. Audit & Review', status === 'UNDER_REVIEW' || status === 'APPROVED' || status === 'FINALIZED', status === 'UNDER_REVIEW'),
        el('span', { style: 'color:var(--muted)' }, '➔'),
        renderStepBadge(isAr ? '3. اعتماد الإدارة (APPROVED)' : '3. Final Approval', status === 'APPROVED' || status === 'FINALIZED', status === 'APPROVED'),
        el('span', { style: 'color:var(--muted)' }, '➔'),
        renderStepBadge(isAr ? '4. إقفال وحفظ اللقطة (LOCKED)' : '4. Locked Snapshot', status === 'FINALIZED', status === 'FINALIZED'),
      ])
    ]);
    container.append(stepperCard);

    // 2. Toolbar Actions
    const toolbar = el('div', { class: 'card', style: 'display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;padding:12px 18px;margin-bottom:16px;background:var(--card);border:1px solid var(--border)' }, [
      el('div', { style: 'display:flex;align-items:center;gap:12px' }, [
        el('label', { style: 'font-size:13px;font-weight:700;color:var(--text)' }, isAr ? '📅 اختيار الفترة:' : '📅 Select Period:'),
        el('input', {
          type: 'month',
          id: 'payroll-month-input',
          value: selectedPayrollMonth,
          style: 'padding:6px 12px;border:1px solid var(--border);border-radius:8px;font-family:inherit;font-size:13px;background:var(--bg);color:var(--text)',
          onchange: (e) => {
            selectedPayrollMonth = e.target.value;
            renderPayrollLedger(container, mainContainer);
          }
        }),
      ]),
      el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' }, [
        !isFinalized ? el('button', {
          class: 'btn btn-primary btn-small',
          onclick: () => renderPayrollLedger(container, mainContainer)
        }, isAr ? '⚡ احتساب وتجميع المسير' : '⚡ Calculate & Refresh Ledger') : null,
        
        (!isFinalized && status === 'DRAFT' && appStore.get().role !== 'SUPERVISOR') ? el('button', {
          class: 'btn btn-small',
          style: 'background:#0284c7;color:#fff',
          onclick: () => changePayrollStatus(selectedPayrollMonth, 'UNDER_REVIEW', container, mainContainer)
        }, isAr ? '📤 إرسال للمراجعة والتدقيق' : '📤 Submit for Review') : null,

        (!isFinalized && status === 'UNDER_REVIEW' && appStore.get().role !== 'SUPERVISOR') ? el('button', {
          class: 'btn btn-small',
          style: 'background:#16a34a;color:#fff',
          onclick: () => changePayrollStatus(selectedPayrollMonth, 'APPROVED', container, mainContainer)
        }, isAr ? '✅ اعتماد المسير' : '✅ Approve Payroll') : null,

        (!isFinalized && (status === 'APPROVED' || status === 'UNDER_REVIEW' || status === 'DRAFT') && appStore.get().role !== 'SUPERVISOR') ? el('button', {
          class: 'btn btn-small',
          style: 'background:#0f172a;color:#38bdf8;border:1px solid #38bdf8;font-weight:700',
          onclick: () => finalizePayroll(selectedPayrollMonth, container, mainContainer)
        }, isAr ? '🔒 إقفال المسير وحفظ اللقطة (Snapshot)' : '🔒 Finalize & Lock Snapshot') : null,

        el('button', {
          class: 'btn btn-ghost btn-small',
          onclick: () => exportPayrollCsv(selectedPayrollMonth, rows)
        }, isAr ? '⬇ تصدير Excel / CSV' : '⬇ Export Excel / CSV'),

        el('button', {
          class: 'btn btn-ghost btn-small',
          style: 'color:#0284c7;font-weight:700',
          onclick: () => exportWpsFile(selectedPayrollMonth)
        }, isAr ? '🏦 ملف التحضير البنكي' : '🏦 Bank WPS File'),

        appStore.get().role !== 'SUPERVISOR' ? el('button', {
          class: 'btn btn-ghost btn-small',
          onclick: () => openSalaryStructuresListModal()
        }, isAr ? '📑 هياكل الرواتب' : '📑 Salary Structures') : null,

        appStore.get().role !== 'SUPERVISOR' ? el('button', {
          class: 'btn btn-primary btn-small',
          onclick: () => openCreateSalaryStructureModal()
        }, isAr ? '➕ هيكل رواتب جديد' : '➕ New Salary Structure') : null,
      ].filter(Boolean))
    ]);
    container.append(toolbar);

    // 3. KPI Summary Cards
    const grossTotal = totals.gross || totals.total || (totals.fixed || 0) + (totals.delivery || 0) + (totals.bonus || 0) + (totals.additions || 0) || 0;
    const deductionsTotal = totals.deductions || (totals.absences || 0) + (totals.late || 0) + (totals.advances || 0) + (totals.other_deductions || 0) || 0;
    const netTotal = totals.total || grossTotal - deductionsTotal;
    const curr = isAr ? ' ر.س' : ' SAR';

    container.append(el('div', { class: 'cards' }, [
      metricCard(`${(grossTotal || 0).toLocaleString(isAr ? 'ar-SA' : 'en-US')}${curr}`, isAr ? 'إجمالي الاستحقاقات (Gross)' : 'Gross Earnings', 'blue', null, isAr ? 'أساسي + إنتاجية طلبات + بونص' : 'Base + Delivery Pay + Bonus'),
      metricCard(data.couriers_count || rows.length || 0, isAr ? 'مناديب المسير المكتمل' : 'Total Eligible Drivers', 'blue', null, isAr ? 'كافة السائقين المسجلين' : 'All active registered drivers'),
      metricCard(`${(deductionsTotal || 0).toLocaleString(isAr ? 'ar-SA' : 'en-US')}${curr}`, isAr ? 'إجمالي الاستقطاعات' : 'Total Deductions', deductionsTotal > 0 ? 'alert' : 'blue', null, isAr ? 'غياب + تأخير + سلف + مخالفات' : 'Absence + Late + Advances + Penalties'),
      metricCard(`${(netTotal || 0).toLocaleString(isAr ? 'ar-SA' : 'en-US')}${curr}`, isAr ? 'صافي حساب المسير (Net)' : 'Net Payable', 'trend', null, isAr ? 'جاهز للتحويل والصرف البنكي' : 'Ready for bank disbursement'),
    ]));

    if (!rows.length) {
      container.append(emptyState(isAr ? 'لا توجد قيود رواتب مسجلة لهذا الشهر. اضغط "⚡ احتساب وتجميع المسير" لتوليد المستحقات من الحضور والإنتاجية.' : 'No payroll records for this period. Click "⚡ Calculate & Refresh Ledger" to compute.'));
      return;
    }

    // 4. Itemized Rider Settlement Table
    const modifiedOrders = new Map();

    const columns = [
      { key: 'name', label: isAr ? 'السائق والبيانات' : 'Driver Details', render: (v, r) => el('div', {}, [
        el('b', { style: 'display:block;color:var(--text);font-size:13px' }, v || '—'),
        el('div', { style: 'color:var(--muted);font-size:11px;display:flex;gap:6px' }, [
          el('span', {}, r.phone || ''),
          el('span', {}, '•'),
          el('span', {}, r.city || r.zone || (isAr ? 'الرياض' : 'Riyadh'))
        ])
      ]) },
      { key: 'driver_orders', label: isAr ? 'مسجل من السائق' : 'Driver Claimed', render: (_, r) => {
        const dOrders = r.driver_orders ?? r.orders ?? 0;
        return el('div', { style: 'text-align:center' }, [
          el('span', { class: 'badge badge-blue', style: 'font-weight:700;font-size:12px;padding:3px 8px' }, `📱 ${dOrders}`),
          el('small', { style: 'display:block;color:var(--muted);font-size:10px;margin-top:2px' }, isAr ? 'من تطبيق السائق' : 'DOU App Log')
        ]);
      }},
      { key: 'approved_orders', label: isAr ? 'الطلبات المعتمدة (هنقرستيشن)' : 'Approved Orders', render: (_, r) => {
        const appOrders = r.approved_orders ?? r.orders ?? 0;
        const dOrders = r.driver_orders ?? r.orders ?? 0;
        const isDiff = appOrders !== dOrders;
        if (isFinalized) {
          return el('div', { style: 'text-align:center' }, [
            el('b', { style: 'color:#0284c7;font-size:13px' }, `${appOrders}`),
            isDiff ? el('small', { style: 'display:block;color:#eab308;font-size:10px' }, isAr ? '✏️ معدل من المحاسب' : 'Accountant Adjusted') : null
          ]);
        }
        const input = el('input', {
          type: 'number',
          min: '0',
          value: appOrders,
          style: `width:75px;padding:5px 8px;border-radius:6px;border:1px solid ${isDiff ? '#0284c7' : 'var(--border)'};background:${isDiff ? 'rgba(2,132,199,0.06)' : 'var(--bg)'};color:var(--text);font-weight:700;text-align:center;font-size:13px`,
          onchange: (e) => {
            const val = Math.max(0, parseInt(e.target.value, 10) || 0);
            modifiedOrders.set(r.id, val);
            const saveBtn = document.getElementById('save-approved-orders-btn');
            if (saveBtn) {
              saveBtn.style.display = 'inline-flex';
              saveBtn.innerText = isAr ? `💾 حفظ تعديل (${modifiedOrders.size}) مندوب` : `💾 Save (${modifiedOrders.size}) Overrides`;
            }
          }
        });
        return el('div', { style: 'display:flex;flex-direction:column;align-items:center;gap:2px' }, [
          input,
          isDiff ? el('small', { style: 'color:#0284c7;font-size:10px;font-weight:600' }, isAr ? 'معدل بالفاتورة' : 'Invoice Verified') : null
        ]);
      }},
      { key: 'fixed', label: isAr ? 'الأساسي والبدلات' : 'Base & Allowances', render: (v) => `${(v || 0).toLocaleString(isAr ? 'ar-SA' : 'en-US')}${curr}` },
      { key: 'delivery', label: isAr ? 'أجر الطلبات' : 'Delivery Earnings', render: (v, r) => el('div', {}, [
        el('b', { style: 'color:var(--primary)' }, `${(v || 0).toLocaleString(isAr ? 'ar-SA' : 'en-US')}${curr}`),
        el('small', { style: 'display:block;color:var(--muted);font-size:10px' }, `${(r.approved_orders ?? r.orders ?? 0)} ${isAr ? 'طلب' : 'orders'} × ${r.per_delivery_rate || r.average_per_order || 0}${curr}`)
      ]) },
      { key: 'bonus', label: isAr ? 'حافز التارجت' : 'Target Bonus', render: (v) => (v > 0 ? el('span', { style: 'color:#16a34a;font-weight:700' }, `+${(v || 0).toLocaleString(isAr ? 'ar-SA' : 'en-US')}${curr}`) : `0${curr}`) },
      { key: 'gross', label: isAr ? 'إجمالي الاستحقاق' : 'Gross Total', render: (v, r) => {
        const val = v || (r.fixed || 0) + (r.delivery || 0) + (r.bonus || 0) + (r.additions || 0);
        return el('b', { style: 'color:#059669;font-size:12px' }, `${val.toLocaleString(isAr ? 'ar-SA' : 'en-US')}${curr}`);
      }},
      { key: 'absences_late', label: isAr ? 'خصم حضور (غياب/تأخير)' : 'Attendance Deductions', render: (_, r) => {
        const abs = (r.absence_deduction || 0) + (r.late_deduction || 0);
        return abs > 0 ? el('span', { style: 'color:#dc2626;font-weight:600' }, `-${abs.toLocaleString(isAr ? 'ar-SA' : 'en-US')}${curr}`) : `0${curr}`;
      }},
      { key: 'advances_other', label: isAr ? 'سلف وخصومات' : 'Advances & Penalties', render: (_, r) => {
        const adv = (r.advance_deduction || 0) + (r.other_deductions || 0);
        return adv > 0 ? el('span', { style: 'color:#e11d48;font-weight:600' }, `-${adv.toLocaleString(isAr ? 'ar-SA' : 'en-US')}${curr}`) : `0${curr}`;
      }},
      { key: 'total', label: isAr ? 'صافي حساب المندوب' : 'Net Settlement', render: (v) => el('div', { style: 'background:rgba(2,132,199,0.08);padding:4px 8px;border-radius:6px;display:inline-block' }, [
        el('b', { style: 'color:#0284c7;font-size:13px' }, `${(v || 0).toLocaleString(isAr ? 'ar-SA' : 'en-US')}${curr}`)
      ]) },
      { key: 'actions', label: isAr ? 'كشف الحساب' : 'Statement', render: (_, r) => el('button', {
        class: 'btn btn-ghost btn-small',
        style: 'color:#0284c7;font-weight:700',
        onclick: () => openRiderStatementModal(r.id, selectedPayrollMonth)
      }, isAr ? '📄 كشف مفصل' : '📄 Statement') }
    ];

    const saveApprovedOrdersBtn = el('button', {
      id: 'save-approved-orders-btn',
      class: 'btn btn-primary btn-small',
      style: 'display:none;background:#16a34a;color:#fff;font-weight:700',
      onclick: async () => {
        if (!modifiedOrders.size) return;
        try {
          const overrides = Array.from(modifiedOrders.entries()).map(([cid, count]) => ({
            courier_id: cid,
            approved_orders: count,
            notes: 'اعتماد المحاسب من شيت المنصة الرسمي'
          }));
          await api.post('/hr/payroll/override-orders', {
            month: selectedPayrollMonth,
            overrides
          });
          alert(isAr ? `✅ تم حفظ وتحديث طلبات (${overrides.length}) مندوب وإعادة احتساب المسير فوراً!` : `✅ Saved (${overrides.length}) rider overrides and recalculated ledger!`);
          renderPayrollLedger(container, mainContainer);
        } catch (err) {
          alert('❌ فشل حفظ التعديلات: ' + err.message);
        }
      }
    }, isAr ? '💾 حفظ تعديل الطلبات' : '💾 Save Approved Orders');

    container.append(el('div', { class: 'card', style: 'padding:16px;background:var(--card);border:1px solid var(--border);border-radius:12px' }, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px' }, [
        el('div', {}, [
          el('h3', { style: 'margin:0;font-size:15px;color:var(--text)' }, isAr ? `مسير رواتب وتسوية حسابات المناديب لشهر (${selectedPayrollMonth})` : `Monthly Driver Payroll Ledger & Settlement (${selectedPayrollMonth})`),
          el('p', { style: 'margin:2px 0 0 0;font-size:11px;color:var(--muted)' }, isAr ? 'يمكن للمحاسب تعديل خانة الطلبات المعتمدة لكل سائق بناءً على فاتورة المنصة ثم الضغط على حفظ لحساب الصافي بدقة.' : 'The accountant can edit the Approved Orders column based on the platform invoice.')
        ]),
        el('div', { style: 'display:flex;align-items:center;gap:8px' }, [
          saveApprovedOrdersBtn,
          el('span', { style: 'font-size:12px;color:var(--muted)' }, isAr ? `إجمالي المناديب: ${rows.length}` : `Total Drivers: ${rows.length}`)
        ])
      ]),
      table(columns, rows)
    ]));

  } catch (e) {
    container.innerHTML = '';
    container.append(errorState('تعذر تحميل بيانات مسير الرواتب: ' + e.message, () => renderPayrollLedger(container, mainContainer)));
  }
}

function renderStepBadge(title, isPassed, isCurrent) {
  const bg = isCurrent ? '#0284c7' : (isPassed ? '#16a34a' : 'var(--bg)');
  const color = (isCurrent || isPassed) ? '#fff' : 'var(--muted)';
  const border = (isCurrent || isPassed) ? 'none' : '1px solid var(--border)';
  return el('div', { style: `padding:4px 10px;border-radius:20px;font-size:11px;font-weight:700;background:${bg};color:${color};border:${border};white-space:nowrap` }, title);
}

async function changePayrollStatus(month, status, container, mainContainer) {
  try {
    await api.post('/hr/payroll/status', { month, status });
    alert(`✅ تم تحديث حالة مسير شهر (${month}) إلى: ${status}`);
    renderPayrollLedger(container, mainContainer);
  } catch (e) {
    alert('❌ تعذر تحديث حالة المسير: ' + e.message);
  }
}

async function finalizePayroll(month, container, mainContainer) {
  if (!confirm(`هل أنت متأكد من إقفال مسير رواتب شهر (${month}) نهائياً؟\n\nبمجرد الإقفال سيتم أخذ لقطة مالية ثابتة (Snapshot) تمنع أي تغيير بأثر رجعي، وستُسجل أي تعديلات مستقبلية كتسويات مستقلة.`)) return;
  try {
    const res = await api.post('/hr/payroll/finalize', { month });
    alert(`🔒 تم إقفال واعتماد مسير الرواتب لشهر (${month}) بنجاح!\nتم حفظ ${res.snapshots || 0} لقطة مالية للمناديب.`);
    renderPayrollLedger(container, mainContainer);
  } catch (e) {
    alert('❌ تعذر إقفال المسير: ' + e.message);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// RIDER ITEMIZED STATEMENT & PAYSLIP MODAL
// ─────────────────────────────────────────────────────────────────────────────
export async function openRiderStatementModal(courierId, month) {
  const loadingM = modal('كشف حساب ومسير المندوب الشهري', [loadingState('جاري تجميع وتدقيق كشف الحساب...')]);
  try {
    const res = await api.get(`/hr/payroll/rider/${courierId}/statement?month=${month}`);
    if (loadingM && loadingM.remove) loadingM.remove();

    const c = res.courier || {};
    const p = res.period || {};
    const s = res.statement || {};
    const b = res.bonus_details || {};
    const adj = res.adjustments || [];

    const isFinal = p.status === 'FINALIZED' || p.finalized;
    const statusLabel = isFinal ? '🔒 مقفل بلقطة مالية (Snapshot)' : (p.status === 'APPROVED' ? '✅ معتمد' : (p.status === 'UNDER_REVIEW' ? '⏳ قيد المراجعة' : '✏️ مسودة تشغيلية'));

    const content = el('div', { class: 'rider-statement-card', style: 'max-width:720px;font-size:13px;line-height:1.6' }, [
      // Top info
      el('div', { style: 'display:flex;justify-content:space-between;align-items:flex-start;background:var(--card);padding:14px 18px;border-radius:10px;border:1px solid var(--border);margin-bottom:14px' }, [
        el('div', {}, [
          el('h2', { style: 'margin:0 0 4px 0;font-size:17px;color:var(--text)' }, `${c.name || 'سائق'}`),
          el('div', { style: 'color:var(--muted);font-size:12px;display:flex;gap:12px;flex-wrap:wrap' }, [
            el('span', {}, `📱 ${c.phone || '—'}`),
            el('span', {}, `🏢 ${c.contract_name || 'عقد عام'}`),
            el('span', {}, `📍 ${c.city || 'الرياض'}`),
            el('span', { dir: 'ltr', style: 'font-family:monospace' }, `🏦 ${c.bank_iban || '—'}`)
          ])
        ]),
        el('div', { style: 'text-align:left' }, [
          el('div', { style: 'font-weight:700;font-size:13px;margin-bottom:4px;color:var(--primary)' }, `📅 شهر ${p.month || month}`),
          el('span', { class: `badge badge-${isFinal ? 'green' : 'amber'}`, style: 'font-size:11px' }, statusLabel)
        ])
      ]),

      // Itemized Equation Cards (Matched exactly to user specification)
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px' }, [
        // Gross Section
        el('div', { style: 'background:rgba(16,185,129,0.05);border:1px solid rgba(16,185,129,0.25);border-radius:10px;padding:14px' }, [
          el('div', { style: 'font-weight:800;color:#059669;font-size:14px;margin-bottom:10px;display:flex;justify-content:space-between' }, [
            el('span', {}, '🟢 الاستحقاقات (Earnings)'),
            el('span', {}, `${(s.gross_pay || 0).toLocaleString('ar-SA')} ر.س`)
          ]),
          el('div', { style: 'display:flex;flex-direction:column;gap:6px' }, [
            statementRowItem('راتب أساسي وبدلات ثابته', s.base_salary, false),
            statementRowItem(`طلبات/إنتاجية (${s.orders_count || 0} طلب × ${s.per_delivery_rate || 0} ر.س)`, s.delivery_pay, false),
            statementRowItem('حافز تحقيق التارجت (بونص)', s.target_bonus, false, b.achieved ? '🏆 محقق' : ''),
            statementRowItem('إضافي وبدلات أخرى', (s.overtime_pay || 0) + (s.other_additions || 0), false),
          ])
        ]),

        // Deductions Section
        el('div', { style: 'background:rgba(239,68,68,0.05);border:1px solid rgba(239,68,68,0.25);border-radius:10px;padding:14px' }, [
          el('div', { style: 'font-weight:800;color:#dc2626;font-size:14px;margin-bottom:10px;display:flex;justify-content:space-between' }, [
            el('span', {}, '🔴 الاستقطاعات (Deductions)'),
            el('span', {}, `-${(s.total_deductions || 0).toLocaleString('ar-SA')} ر.س`)
          ]),
          el('div', { style: 'display:flex;flex-direction:column;gap:6px' }, [
            statementRowItem('خصم غياب غير مبرر', s.absence_deduction, true),
            statementRowItem('خصم تأخير عن الوردية', s.late_deduction, true),
            statementRowItem('سلفة مستردة لهذا الشهر', s.advance_deduction, true),
            statementRowItem('خصومات ومخالفات أخرى', s.other_deduction, true),
          ])
        ])
      ]),

      // Net Total Highlight
      el('div', { style: 'background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);color:#fff;padding:16px 20px;border-radius:12px;margin-bottom:14px;display:flex;justify-content:space-between;align-items:center' }, [
        el('div', {}, [
          el('div', { style: 'font-size:12px;color:#94a3b8;font-weight:600' }, 'صافي حساب المندوب النهائي المستحق للصرف (Net Pay)'),
          el('div', { style: 'font-size:11px;color:#cbd5e1;margin-top:2px' }, `معادلة المسير: [${(s.gross_pay || 0).toLocaleString('ar-SA')} استحقاقات] - [${(s.total_deductions || 0).toLocaleString('ar-SA')} استقطاعات]`)
        ]),
        el('div', { style: 'font-size:24px;font-weight:900;color:#38bdf8' }, `${(s.net_pay || 0).toLocaleString('ar-SA')} ر.س`)
      ]),

      // Adjustments / Advances list if present
      adj.length ? el('div', { style: 'background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px;margin-bottom:14px' }, [
        el('h4', { style: 'margin:0 0 8px 0;font-size:13px;color:var(--text)' }, '📝 سجل التسويات والسلف المدققة (Adjustments & Advances)'),
        el('table', { style: 'width:100%;font-size:11px;border-collapse:collapse' }, [
          el('thead', {}, [
            el('tr', { style: 'color:var(--muted);border-bottom:1px solid var(--border);text-align:right' }, [
              el('th', { style: 'padding:4px 6px' }, 'النوع'),
              el('th', { style: 'padding:4px 6px' }, 'المبلغ'),
              el('th', { style: 'padding:4px 6px' }, 'البيان / السبب'),
              el('th', { style: 'padding:4px 6px' }, 'التاريخ')
            ])
          ]),
          el('tbody', {}, adj.map(a => el('tr', { style: 'border-bottom:1px solid rgba(255,255,255,0.05)' }, [
            el('td', { style: 'padding:4px 6px' }, a.kind),
            el('td', { style: 'padding:4px 6px;font-weight:700;color:' + (a.amount < 0 || a.kind !== 'OVERTIME' ? '#ef4444' : '#10b981') }, `${a.amount} ر.س`),
            el('td', { style: 'padding:4px 6px' }, a.note || '—'),
            el('td', { style: 'padding:4px 6px;color:var(--muted)' }, a.created_at ? a.created_at.slice(0, 10) : '—')
          ])))
        ])
      ]) : null,

      // Actions
      el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:14px' }, [
        el('button', {
          class: 'btn btn-ghost',
          onclick: () => downloadPayslip(c, p.month || month, s)
        }, '🖨️ طباعة قسيمة الراتب'),
        el('button', {
          class: 'btn btn-primary',
          onclick: () => m.remove()
        }, 'إغلاق')
      ])
    ]);

    const m = modal(`كشف حساب ومسير المندوب — شهر ${p.month || month}`, content);
  } catch (err) {
    if (loadingM && loadingM.remove) loadingM.remove();
    alert('تعذر تحميل كشف حساب المندوب: ' + err.message);
  }
}

function statementRowItem(label, amount, isDeduction = false, extra = '') {
  const val = (amount || 0);
  const color = isDeduction ? (val > 0 ? '#dc2626' : 'var(--text)') : (val > 0 ? '#059669' : 'var(--text)');
  const sign = isDeduction && val > 0 ? '-' : '';
  return el('div', { style: 'display:flex;justify-content:space-between;align-items:center;font-size:12px' }, [
    el('span', { style: 'color:var(--text)' }, `${label} ${extra ? `<small style="color:#0284c7">(${extra})</small>` : ''}`),
    el('b', { style: `color:${color};font-family:monospace` }, `${sign}${val.toLocaleString('ar-SA')} ر.س`)
  ]);
}

function downloadPayslip(rider, month, statement = null) {
  window.print();
}

function exportPayrollCsv(month, rows) {
  if (!rows || !rows.length) {
    alert('لا توجد بيانات لتصديرها.');
    return;
  }
  const headers = ['اسم السائق', 'الجوال', 'المدينة', 'الأساسي', 'الطلبات', 'أجر التوصيل', 'البونص', 'إجمالي الاستحقاق', 'الخصومات', 'صافي الراتب', 'رقم الآيبان IBAN'];
  const csvRows = [headers.join(',')];
  rows.forEach(r => {
    csvRows.push([
      `"${r.name || ''}"`,
      `"${r.phone || ''}"`,
      `"${r.city || r.zone || ''}"`,
      r.fixed || 0,
      r.orders || 0,
      r.delivery || 0,
      r.bonus || 0,
      r.gross || 0,
      r.deductions || 0,
      r.total || 0,
      `"${r.bank_iban || ''}"`
    ].join(','));
  });
  const blob = new Blob(['\ufeff' + csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `payroll_settlement_${month}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

async function exportWpsFile(month) {
  try {
    const token = localStorage.getItem('dou_token_v2');
    const res = await fetch(`/hr/payroll/wps-export?month=${month}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    if (!res.ok) throw new Error('فشل تحميل ملف التحضير البنكي');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `Payroll_Bank_Preparation_${month}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  } catch (e) {
    alert('❌ تعذر تصدير ملف التحضير البنكي: ' + e.message);
  }
}

async function openCreateSalaryStructureModal() {
  try {
    const [contractsRes, citiesRes] = await Promise.all([
      api.get('/hr/contract-structure').catch(() => []),
      api.get('/hr/operating-cities').catch(() => ({ cities: [] }))
    ]);

    const contracts = contractsRes || [];
    const cities = citiesRes.cities || citiesRes || [];

    const projectSelect = searchableSelect({
      id: 'sal-project-select',
      placeholder: '🔍 اختر المشروع / العقد التجاري...',
      options: [
        { value: '', label: 'عام (لكل مشاريع وعقود المنصة)' },
        ...contracts.map(c => ({
          value: String(c.id),
          label: c.name,
          sublabel: c.client_name ? `العميل: ${c.client_name} | سعر الطلب: ${c.client_rate_per_order || '—'} ر.س` : ''
        }))
      ],
      onChange: () => updateAutoNames()
    });

    const citySelect = searchableSelect({
      id: 'sal-city-select',
      placeholder: '🔍 اختر المدينة أو فرع التشغيل...',
      options: [
        { value: '', label: 'كل المدن والفروع التشغيلية' },
        ...cities.map(ct => ({ value: String(ct.id), label: ct.name, sublabel: ct.region ? `المنطقة: ${ct.region}` : '' }))
      ],
      onChange: () => updateAutoNames()
    });

    function updateAutoNames() {
      const projId = document.getElementById('sal-project-select')?.value;
      const cityId = document.getElementById('sal-city-select')?.value;
      const projObj = contracts.find(c => String(c.id) === projId);
      const cityObj = cities.find(c => String(c.id) === cityId);

      const pName = projObj ? projObj.name : '';
      const cName = cityObj ? cityObj.name : '';

      const nameInput = document.getElementById('sal-name');
      const codeInput = document.getElementById('sal-code');

      if (nameInput && (!nameInput.value || nameInput.dataset.auto === 'true')) {
        let suggestedName = 'سلم رواتب وبدلات';
        if (pName) suggestedName += ` - ${pName}`;
        if (cName) suggestedName += ` (${cName})`;
        nameInput.value = suggestedName;
        nameInput.dataset.auto = 'true';
      }

      if (codeInput && (!codeInput.value || codeInput.dataset.auto === 'true')) {
        const pCode = projObj ? projObj.name.replace(/[^a-zA-Z0-9]/g, '').slice(0, 5).toUpperCase() || 'PROJ' : 'GEN';
        const cCode = cityObj ? (cityObj.name === 'الرياض' ? 'RUH' : cityObj.name === 'جدة' ? 'JED' : cityObj.name === 'الدمام' ? 'DMM' : 'CT') : 'ALL';
        const year = new Date().getFullYear();
        codeInput.value = `SAL-${pCode}-${cCode}-${year}`;
        codeInput.dataset.auto = 'true';
      }
      updatePreview();
    }

    const previewBox = el('div', {
      id: 'sal-preview-box',
      style: 'background:var(--soft);border:1px solid var(--border);border-radius:10px;padding:12px 16px;font-size:12.5px;color:var(--text);line-height:1.6'
    });

    function updatePreview() {
      const base = parseFloat(document.getElementById('sal-base')?.value || 0);
      const housing = parseFloat(document.getElementById('sal-housing')?.value || 0);
      const transport = parseFloat(document.getElementById('sal-transport')?.value || 0);
      const rate = parseFloat(document.getElementById('sal-rate')?.value || 0);
      const totalFixed = base + housing + transport;

      const projId = document.getElementById('sal-project-select')?.value;
      const cityId = document.getElementById('sal-city-select')?.value;
      const projObj = contracts.find(c => String(c.id) === projId);
      const cityObj = cities.find(c => String(c.id) === cityId);

      previewBox.innerHTML = `
        <div style="display:flex;justify-content:space-between;margin-bottom:6px">
          <span>🏢 المشروع / العقد: <b>${escapeHtml(projObj ? projObj.name : 'عام (لكل العقود)')}</b></span>
          <span>📍 نطاق المدينة: <b>${escapeHtml(cityObj ? cityObj.name : 'كل المدن والفروع')}</b></span>
        </div>
        <div style="border-top:1px dashed var(--border);padding-top:6px">
          💵 إجمالي الراتب الثابت مع البدلات: <b>${totalFixed.toLocaleString('ar-SA')} ر.س</b> 
          (أساسي: ${base} + سكن: ${housing} + نقل: ${transport})
          ${rate > 0 ? `<br>⚡ عمولة التوصيل المعتمدة: <b>${rate} ر.س</b> لكل طلب منجز.` : ''}
        </div>
      `;
    }

    const content = el('form', { style: 'display:grid;gap:14px;direction:rtl' }, [
      el('div', { style: 'background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:14px' }, [
        el('div', { style: 'font-weight:700;font-size:13px;color:var(--ink);margin-bottom:10px' }, '🔗 ربط الهيكل المالي بالمشروع والمنطقة الجغرافية:'),
        el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:12px' }, [
          el('div', {}, [
            el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--muted)' }, '1️⃣ المشروع / العقد التجاري: *'),
            projectSelect
          ]),
          el('div', {}, [
            el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--muted)' }, '2️⃣ المدينة / فرع التشغيل: *'),
            citySelect
          ]),
        ])
      ]),
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:12px' }, [
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'اسم الهيكل المالي: *'),
          el('input', {
            id: 'sal-name',
            placeholder: 'مثال: سلم رواتب نينجا إكسبريس - الرياض',
            required: true,
            style: 'width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px',
            oninput: (e) => { e.target.dataset.auto = 'false'; }
          })
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'رمز الهيكل (الكود الفريد): *'),
          el('input', {
            id: 'sal-code',
            placeholder: 'SAL-NINJA-RUH-2026',
            required: true,
            style: 'width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px',
            oninput: (e) => { e.target.dataset.auto = 'false'; }
          })
        ])
      ]),
      el('div', { style: 'display:grid;grid-template-columns:repeat(4, 1fr);gap:10px' }, [
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--muted)' }, 'الراتب الأساسي (ر.س):'),
          el('input', { type: 'number', id: 'sal-base', placeholder: '2000', value: '2000', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px', oninput: updatePreview })
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--muted)' }, 'بدل السكن (ر.س):'),
          el('input', { type: 'number', id: 'sal-housing', placeholder: '500', value: '500', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px', oninput: updatePreview })
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--muted)' }, 'بدل النقل / البنزين:'),
          el('input', { type: 'number', id: 'sal-transport', placeholder: '300', value: '300', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px', oninput: updatePreview })
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--muted)' }, 'عمولة الطلب (ر.س/طلب):'),
          el('input', { type: 'number', step: '0.5', id: 'sal-rate', placeholder: '5.0', value: '5.0', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px', oninput: updatePreview })
        ]),
      ]),
      previewBox,
      el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:10px;padding-top:12px;border-top:1px solid var(--border)' }, [
        el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
        el('button', { type: 'submit', class: 'btn btn-primary' }, '💾 حفظ واعتماد هيكل الرواتب')
      ])
    ]);

    const m = modal('➕ إنشاء هيكل رواتب وبدلات رسمي مرتبط بالمشروع والمدينة', content);
    setTimeout(updateAutoNames, 50);

    content.onsubmit = async (e) => {
      e.preventDefault();
      const nameAr = document.getElementById('sal-name').value.trim();
      const code = document.getElementById('sal-code').value.trim();
      const base = parseFloat(document.getElementById('sal-base').value || 0);
      const housing = parseFloat(document.getElementById('sal-housing').value || 0);
      const transport = parseFloat(document.getElementById('sal-transport').value || 0);
      const rate = parseFloat(document.getElementById('sal-rate').value || 0);

      const projId = document.getElementById('sal-project-select').value;
      const cityId = document.getElementById('sal-city-select').value;
      const projObj = contracts.find(c => String(c.id) === projId);
      const cityObj = cities.find(c => String(c.id) === cityId);

      const descriptionMeta = JSON.stringify({
        project_id: projId ? Number(projId) : null,
        project_name: projObj ? projObj.name : 'عام',
        city_id: cityId ? Number(cityId) : null,
        city_name: cityObj ? cityObj.name : 'كل المدن'
      });

      try {
        const st = await api.post('/salary/structures', {
          name_ar: nameAr,
          code: code,
          description_ar: descriptionMeta,
          currency: 'SAR',
          cycle: 'MONTHLY'
        });
        if (base > 0) {
          await api.post(`/salary/structures/${st.id}/components`, {
            code: 'BASE', name_ar: 'الراتب الأساسي', category: 'BASE', calculation: 'FLAT', amount: base
          });
        }
        if (housing > 0) {
          await api.post(`/salary/structures/${st.id}/components`, {
            code: 'HOUSING', name_ar: 'بدل السكن', category: 'ALLOWANCE', calculation: 'FLAT', amount: housing
          });
        }
        if (transport > 0) {
          await api.post(`/salary/structures/${st.id}/components`, {
            code: 'TRANSPORT', name_ar: 'بدل النقل والبنزين', category: 'ALLOWANCE', calculation: 'FLAT', amount: transport
          });
        }
        if (rate > 0) {
          await api.post(`/salary/structures/${st.id}/components`, {
            code: 'PER_ORDER', name_ar: 'أجر التوصيل لكل طلب', category: 'COMMISSION', calculation: 'PER_DELIVERY', amount: rate
          });
        }
        alert(`✅ تم حفظ هيكل الرواتب بنجاح وربطه بالمشروع (${projObj ? projObj.name : 'عام'}) والمدينة (${cityObj ? cityObj.name : 'كل المدن'}).`);
        m.remove();
      } catch (err) {
        alert('❌ تعذر حفظ هيكل الرواتب: ' + err.message);
      }
    };
  } catch (err) {
    alert('❌ خطأ في تحميل بيانات المشاريع والمدن: ' + err.message);
  }
}

async function openSalaryStructuresListModal() {
  try {
    const structures = await api.get('/salary/structures').catch(() => []);
    const body = el('div', { style: 'display:grid;gap:14px;direction:rtl' });

    if (!structures.length) {
      body.append(emptyState('لا توجد هياكل رواتب مسجلة حالياً.'));
    } else {
      const cards = el('div', { style: 'display:grid;gap:10px' }, structures.map(st => {
        let meta = {};
        try { meta = JSON.parse(st.description_ar || '{}'); } catch(e){}
        const comps = st.components || [];
        const baseComp = comps.find(c => c.code === 'BASE')?.amount || 0;
        const housingComp = comps.find(c => c.code === 'HOUSING')?.amount || 0;
        const transComp = comps.find(c => c.code === 'TRANSPORT')?.amount || 0;
        const perOrderComp = comps.find(c => c.code === 'PER_ORDER')?.amount || 0;

        return el('div', { style: 'background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:14px;display:flex;justify-content:space-between;align-items:center' }, [
          el('div', {}, [
            el('div', { style: 'display:flex;align-items:center;gap:8px;margin-bottom:4px' }, [
              el('b', { style: 'font-size:14px;color:var(--text)' }, st.name_ar),
              el('span', { class: 'badge badge-blue', style: 'font-size:10px' }, st.code),
            ]),
            el('div', { style: 'font-size:12px;color:var(--muted);display:flex;flex-wrap:wrap;gap:14px;margin-top:6px' }, [
              el('span', {}, [el('span', {}, '🏢 المشروع: '), el('b', { style: 'color:var(--text)' }, meta.project_name || 'عام')]),
              el('span', {}, [el('span', {}, '📍 المدينة: '), el('b', { style: 'color:var(--text)' }, meta.city_name || 'كل المدن')]),
              el('span', {}, [el('span', {}, '💵 الإجمالي: '), el('b', { style: 'color:var(--text)' }, `${(baseComp + housingComp + transComp).toLocaleString('ar-SA')} ر.س`)]),
              perOrderComp > 0 ? el('span', {}, [el('span', {}, '⚡ عمولة الطلب: '), el('b', { style: 'color:var(--primary)' }, `${perOrderComp} ر.س`)]) : null
            ].filter(Boolean))
          ]),
          el('span', { class: 'badge badge-green' }, 'معتمد')
        ]);
      }));
      body.append(cards);
    }

    body.append(
      el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)' }, [
        el('button', { class: 'btn btn-primary btn-small', onclick: () => { m.remove(); openCreateSalaryStructureModal(); } }, '➕ إضافة هيكل جديد'),
        el('button', { class: 'btn btn-ghost btn-small', onclick: () => m.remove() }, 'إغلاق')
      ])
    );

    const m = modal('📋 دليل هياكل الرواتب والبدلات المعتمدة بالمشاريع والمدن', body);
  } catch (err) {
    alert('❌ تعذر تحميل قائمة هياكل الرواتب: ' + err.message);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 2: السلف والخصومات والمخالفات (ADVANCES & ADJUSTMENTS)
// ─────────────────────────────────────────────────────────────────────────────
async function renderAdjustments(container) {
  container.append(loadingState('جاري تحميل السلف والخصومات...'));

  try {
    const [adjustments, couriers] = await Promise.all([
      api.get('/hr/adjustments').catch(() => []),
      api.get('/hr/couriers').catch(async () => {
        const p = await api.get('/fleet/couriers/page?page=1&page_size=100');
        return p.rows || [];
      })
    ]);

    container.innerHTML = '';

    // Create adjustment form card
    const form = el('div', { class: 'card', style: 'padding:18px;margin-bottom:18px;background:var(--card);border:1px solid var(--border);border-radius:12px' }, [
      el('h3', { style: 'margin:0 0 14px 0;font-size:15px;color:var(--text)' }, '➕ إضافة قيد مالي جديد (سلفة / خصم / مخالفة / مكافأة)'),
      el('div', { style: 'display:grid;grid-template-columns:repeat(auto-fit, minmax(200px, 1fr));gap:12px;margin-bottom:12px' }, [
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;color:var(--muted);margin-bottom:4px' }, 'السائق: *'),
          searchableSelect({
            id: 'adj-courier-select',
            placeholder: '🔍 ابحث بالاسم أو الجوال أو رقم السائق...',
            options: couriers.map(c => ({
              value: String(c.id),
              label: `${c.name || 'سائق'} (#${c.id})`,
              sublabel: `📱 ${c.phone || '—'} | ${c.contract_name || 'عقد عام'}`,
              badge: c.employment_status === 'ACTIVE' || c.is_active ? 'نشط' : 'غير نشط',
              badgeColor: c.employment_status === 'ACTIVE' || c.is_active ? 'green' : 'gray'
            }))
          })
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;color:var(--muted);margin-bottom:4px' }, 'نوع القيد المالي:'),
          el('select', { id: 'adj-kind-select', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text)' }, [
            el('option', { value: 'ADVANCE' }, '💵 سلفة راتب (Advance)'),
            el('option', { value: 'DEDUCTION' }, '📉 خصم إداري / غياب (Deduction)'),
            el('option', { value: 'VIOLATION' }, '🚨 مخالفة مرورية / أضرار (Violation)'),
            el('option', { value: 'OVERTIME' }, '⏰ ساعات إضافية (Overtime)'),
          ])
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;color:var(--muted);margin-bottom:4px' }, 'المبلغ (ر.س):'),
          el('input', { type: 'number', id: 'adj-amount-input', placeholder: 'مثال: 500', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text)' })
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;color:var(--muted);margin-bottom:4px' }, 'فترة التطبيق:'),
          el('input', { type: 'month', id: 'adj-month-input', value: selectedPayrollMonth, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text)' })
        ]),
      ]),
      el('div', { style: 'margin-bottom:12px' }, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;color:var(--muted);margin-bottom:4px' }, 'السبب / الملاحظات:'),
        el('input', { type: 'text', id: 'adj-note-input', placeholder: 'مثال: سلفة شهرية تُخصم من راتب الشهر الحالي أو رقم المخالفة', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text)' })
      ]),
      el('button', {
        class: 'btn btn-primary',
        onclick: async () => {
          const courierId = document.getElementById('adj-courier-select').value;
          const kind = document.getElementById('adj-kind-select').value;
          const amount = parseFloat(document.getElementById('adj-amount-input').value);
          const month = document.getElementById('adj-month-input').value;
          const note = document.getElementById('adj-note-input').value;

          if (!courierId || !amount || isNaN(amount) || amount <= 0) {
            alert('الرجاء اختيار السائق وإدخال مبلغ صحيح.');
            return;
          }

          try {
            await api.post('/hr/adjustments', { courier_id: parseInt(courierId), kind, amount, month, note });
            alert('✅ تم حفظ القيد المالي بنجاح.');
            renderAdjustments(container);
          } catch (e) {
            alert('❌ تعذر حفظ القيد: ' + e.message);
          }
        }
      }, 'حفظ القيد المالي')
    ]);
    container.append(form);

    // Adjustments List Table
    if (!adjustments.length) {
      container.append(emptyState('لا توجد سلف أو خصومات مسجلة حالياً.'));
      return;
    }

    const kindMap = {
      ADVANCE: { label: '💵 سلفة راتب', badge: 'blue' },
      DEDUCTION: { label: '📉 خصم إداري', badge: 'alert' },
      VIOLATION: { label: '🚨 مخالفة مرورية', badge: 'alert' },
      OVERTIME: { label: '⏰ ساعات إضافية', badge: 'green' }
    };

    const columns = [
      { key: 'courier', label: 'السائق', render: (v) => el('b', { style: 'color:var(--text)' }, v) },
      { key: 'kind', label: 'نوع القيد', render: (v) => el('span', { class: `badge badge-${kindMap[v]?.badge || 'gray'}` }, kindMap[v]?.label || v) },
      { key: 'amount', label: 'المبلغ', render: (v) => el('b', { style: 'font-size:13px;color:var(--text)' }, `${(v || 0).toLocaleString('ar-SA')} ر.س`) },
      { key: 'month', label: 'شهر الاستحقاق' },
      { key: 'note', label: 'السبب / الملاحظات', render: (v) => v || '—' },
    ];

    container.append(el('div', { class: 'card', style: 'padding:16px;background:var(--card);border:1px solid var(--border);border-radius:12px' }, [
      el('h3', { style: 'margin:0 0 12px 0;font-size:15px;color:var(--text)' }, '📋 سجل السلف والخصومات المعتمدة'),
      table(columns, adjustments)
    ]));

  } catch (e) {
    container.innerHTML = '';
    container.append(errorState('تعذر تحميل السلف والخصومات: ' + e.message, () => renderAdjustments(container)));
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 3: خطط البونص والمتصدرين (BONUS PLANS & LEADERBOARD)
// ─────────────────────────────────────────────────────────────────────────────
async function renderBonusAndLeaderboard(container) {
  container.append(loadingState('جاري تحميل خطط البونص ولوحة المتصدرين...'));

  try {
    const [bonusPlans, leaderboard] = await Promise.all([
      api.get('/hr/bonus').catch(() => []),
      api.get('/hr/leaderboard').catch(() => ({ rows: [] }))
    ]);

    container.innerHTML = '';

    // 1. Leaderboard Cards
    const lbRows = leaderboard.rows || [];
    if (lbRows.length > 0) {
      container.append(el('div', { class: 'card', style: 'padding:18px;margin-bottom:18px;background:linear-gradient(135deg, rgba(37,99,235,0.05) 0%, rgba(16,185,129,0.05) 100%);border:1px solid rgba(16,185,129,0.2);border-radius:12px' }, [
        el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px' }, [
          el('h3', { style: 'margin:0;font-size:16px;color:var(--text)' }, '🏆 لوحة متصدري التوصيل والأداء لهذا الشهر'),
          el('span', { class: 'badge badge-green' }, 'أداء تنافسي مباشر')
        ]),
        table([
          { key: 'rank', label: 'الترتيب', render: (v) => el('b', { style: `font-size:14px;color:${v===1?'#eab308':(v===2?'#94a3b8':'#b45309')}` }, `#${v}`) },
          { key: 'name', label: 'السائق', render: (v, r) => el('div', {}, [
            el('b', { style: 'color:var(--text)' }, v),
            el('small', { style: 'display:block;color:var(--muted);font-size:11px' }, r.supervisor || 'بدون مشرف')
          ])},
          { key: 'month_orders', label: 'أوردرات الشهر', render: (v) => el('b', { style: 'color:var(--primary)' }, (v || 0).toLocaleString('ar-SA')) },
          { key: 'bonus', label: 'البونص المستحق', render: (v) => el('span', { style: 'color:#16a34a;font-weight:700' }, `+${(v || 0).toLocaleString('ar-SA')} ر.س`) },
          { key: 'estimated_pay', label: 'إجمالي الأرباح التقديرية', render: (v) => el('b', { style: 'color:var(--text)' }, `${(v || 0).toLocaleString('ar-SA')} ر.س`) },
          { key: 'avg_rating', label: 'التقييم', render: (v) => el('span', { style: 'color:#f59e0b;font-weight:700' }, `★ ${v ? Number(v).toFixed(1) : '5.0'}`) },
        ], lbRows.slice(0, 10))
      ]));
    }

    // 2. Bonus Plans Manager
    const isAdmin = appStore.get().role !== 'SUPERVISOR';
    const bonusColumns = [
      { key: 'plan_type', label: 'نوع الخطة', render: (v) => {
        const isFlat = v === 'FLAT_PER_ORDER';
        return el('span', { class: `badge badge-${isFlat ? 'green' : 'blue'}`, style: 'font-size:11.5px;padding:4px 8px' }, isFlat ? '⚡ سعر طلب مباشر' : '🎯 خطة تارجت وحافز');
      }},
      { key: 'contract', label: 'العقد والفرع', render: (v, r) => el('div', {}, [
        el('b', { style: 'display:block;color:var(--ink);font-size:12.5px' }, v || 'عام (لكل عقود الشركة)'),
        el('small', { style: 'color:var(--muted);font-size:11px' }, `فرع: ${r.city || 'الرياض'}`)
      ]) },
      { key: 'courier', label: 'نطاق التطبيق', render: (v) => el('span', { class: 'badge badge-gray' }, v || 'كل مناديب العقد') },
      { key: 'details', label: 'تفاصيل وشروط الخطة', render: (_, r) => {
        if (r.plan_type === 'FLAT_PER_ORDER') {
          return el('div', { style: 'display:flex;align-items:center;gap:6px' }, [
            el('span', { style: 'font-weight:700;color:var(--primary);font-size:13px;background:rgba(37,99,235,0.08);padding:2px 8px;border-radius:6px' }, `${r.flat_order_rate || 0} ر.س`),
            el('span', { style: 'color:var(--muted);font-size:11px' }, 'عن كل طلب منجز')
          ]);
        }
        return el('div', { style: 'font-size:12px;line-height:1.4' }, [
          el('div', { style: 'display:flex;align-items:center;gap:6px;flex-wrap:wrap' }, [
            el('span', { style: 'color:var(--muted);font-size:11px' }, 'المستهدف:'),
            el('b', { style: 'color:var(--ink)' }, `${(r.target_orders || 0).toLocaleString('ar-SA')} طلب`),
            el('span', { style: 'color:var(--muted);font-size:11px' }, '➔ الحافز:'),
            el('b', { style: 'color:#16a34a;background:rgba(22,163,74,0.1);padding:1px 6px;border-radius:4px' }, `${(r.bonus_amount || 0).toLocaleString('ar-SA')} ر.س`)
          ]),
          el('div', { style: 'color:var(--muted);font-size:11px;margin-top:3px;display:flex;gap:6px;align-items:center' }, [
            el('span', {}, `أجر الزيادة: +${r.over_target_rate || 0} ر.س/طلب`),
            el('span', { style: 'opacity:0.4' }, '|'),
            el('span', {}, `دون المستهدف: ${r.below_target_rate || 0} ر.س/طلب`)
          ])
        ]);
      }},
      { key: 'is_active', label: 'الحالة', render: (v) => el('span', { class: `badge badge-${v ? 'green' : 'gray'}` }, v ? '● نشطة ومطبقة' : '○ معطلة') },
    ];

    if (isAdmin) {
      bonusColumns.push({
        key: 'actions',
        label: 'إجراءات التحكم',
        render: (_, r) => el('div', { style: 'display:flex;gap:4px' }, [
          el('button', {
            class: 'btn btn-ghost btn-small',
            style: 'color:var(--primary);border-color:rgba(37,99,235,0.2);padding:2px 8px;font-size:11.5px',
            onclick: () => openEditBonusPlanModal(r, () => renderBonusAndLeaderboard(container))
          }, '✏️ تعديل'),
          el('button', {
            class: 'btn btn-ghost btn-small',
            style: 'color:var(--red);border-color:rgba(220,38,38,0.2);padding:2px 8px;font-size:11.5px',
            onclick: async () => {
              if (!confirm('هل تريد حذف/تعطيل خطة البونص هذه؟')) return;
              try {
                await api.del(`/hr/bonus/${r.id}`);
                alert('✅ تم حذف خطة البونص.');
                renderBonusAndLeaderboard(container);
              } catch (err) {
                alert('❌ تعذر الحذف: ' + err.message);
              }
            }
          }, '🗑️ حذف')
        ])
      });
    }

    container.append(el('div', { class: 'card', style: 'padding:18px;background:var(--card);border:1px solid var(--border);border-radius:12px' }, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:8px' }, [
        el('div', {}, [
          el('h3', { style: 'margin:0;font-size:15.5px;color:var(--text)' }, '🎯 خطط الحوافز والبونص التشغيلي'),
          el('p', { style: 'margin:4px 0 0 0;font-size:12px;color:var(--muted)' }, 'تُطبق تلقائياً في نهاية الشهر عند حساب كشف الرواتب والتحضير البنكي')
        ]),
        isAdmin ? el('button', {
          class: 'btn btn-primary btn-small',
          onclick: () => openCreateBonusPlanModal(() => renderBonusAndLeaderboard(container))
        }, '➕ إضافة خطة بونص جديدة') : null
      ]),
      bonusPlans.length ? table(bonusColumns, bonusPlans) : emptyState('لا توجد خطط بونص مفعلة حالياً.')
    ]));

  } catch (e) {
    container.innerHTML = '';
    container.append(errorState('تعذر تحميل خطط البونص: ' + e.message, () => renderBonusAndLeaderboard(container)));
  }
}

async function openCreateBonusPlanModal(onCreated) {
  try {
    const structure = await api.get('/hr/contract-structure').catch(() => []);
    const contracts = structure || [];

    const content = el('form', { style: 'display:grid;gap:14px;direction:rtl' });

    let currentContractBranches = contracts[0]?.branches || [];

    const contractSelect = el('select', {
      id: 'bp-contract',
      style: 'width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:13px',
      onchange: (e) => {
        const ct = contracts.find(c => String(c.id) === e.target.value);
        currentContractBranches = ct?.branches || [];
        updateBranchOptions();
      }
    }, [
      el('option', { value: '' }, 'عام (لكل عقود الشركة)'),
      ...contracts.map(c => el('option', { value: String(c.id) }, c.name))
    ]);

    const branchSelect = el('select', {
      id: 'bp-branch',
      style: 'width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font-size:13px'
    }, [
      el('option', { value: '' }, 'كل فروع العقد')
    ]);

    function updateBranchOptions() {
      branchSelect.innerHTML = '';
      branchSelect.append(el('option', { value: '' }, 'كل فروع العقد'));
      currentContractBranches.forEach(b => {
        branchSelect.append(el('option', { value: String(b.id) }, `فرع ${b.city || b.id}`));
      });
    }

    // Segmented Plan Type Selector
    let activePlanType = 'TARGET_TIER';

    const cardTargetTier = el('div', {
      id: 'btn-plan-target',
      style: 'padding:14px;border:2px solid var(--primary);background:rgba(37,99,235,0.06);border-radius:10px;cursor:pointer;transition:all 0.2s',
      onclick: () => setPlanType('TARGET_TIER')
    }, [
      el('div', { style: 'display:flex;align-items:center;gap:8px;margin-bottom:4px' }, [
        el('input', { type: 'radio', name: 'plan_type', value: 'TARGET_TIER', checked: true, style: 'width:auto;margin:0' }),
        el('b', { style: 'color:var(--primary);font-size:13.5px' }, '🎯 خطة التارجت والحافز')
      ]),
      el('p', { style: 'margin:0;font-size:11.5px;color:var(--muted);line-height:1.4' }, 'حافز مقطوع عند بلوغ المستهدف + سعر إضافي للزيادة وسعر لما دون الهدف.')
    ]);

    const cardFlatRate = el('div', {
      id: 'btn-plan-flat',
      style: 'padding:14px;border:1px solid var(--border);background:var(--bg);border-radius:10px;cursor:pointer;transition:all 0.2s',
      onclick: () => setPlanType('FLAT_PER_ORDER')
    }, [
      el('div', { style: 'display:flex;align-items:center;gap:8px;margin-bottom:4px' }, [
        el('input', { type: 'radio', name: 'plan_type', value: 'FLAT_PER_ORDER', style: 'width:auto;margin:0' }),
        el('b', { style: 'color:var(--text);font-size:13.5px' }, '⚡ سعر طلب ثابت ومباشر')
      ]),
      el('p', { style: 'margin:0;font-size:11.5px;color:var(--muted);line-height:1.4' }, 'أجر ثابت محدد عن كل طلب يتم تسليمه بدون اشتراط تحقيق تارجت شهري.')
    ]);

    const planTypeSwitcher = el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
      cardTargetTier, cardFlatRate
    ]);

    function setPlanType(type) {
      activePlanType = type;
      const r1 = cardTargetTier.querySelector('input');
      const r2 = cardFlatRate.querySelector('input');
      if (type === 'TARGET_TIER') {
        r1.checked = true; r2.checked = false;
        cardTargetTier.style.borderColor = 'var(--primary)';
        cardTargetTier.style.background = 'rgba(37,99,235,0.06)';
        cardFlatRate.style.borderColor = 'var(--border)';
        cardFlatRate.style.background = 'var(--bg)';
        targetSection.style.display = 'grid';
        flatSection.style.display = 'none';
      } else {
        r1.checked = false; r2.checked = true;
        cardTargetTier.style.borderColor = 'var(--border)';
        cardTargetTier.style.background = 'var(--bg)';
        cardFlatRate.style.borderColor = 'var(--primary)';
        cardFlatRate.style.background = 'rgba(37,99,235,0.06)';
        targetSection.style.display = 'none';
        flatSection.style.display = 'grid';
      }
      updateFormulaPreview();
    }

    const targetSection = el('div', { id: 'target-plan-section', style: 'display:grid;grid-template-columns:1fr 1fr;gap:12px' }, [
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, '🎯 مستهدف الطلبات الشهري (Target): *'),
        el('input', { type: 'number', id: 'bp-target', placeholder: 'مثال: 200', value: '200', required: true, style: 'width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:8px', oninput: updateFormulaPreview })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, '💰 مبلغ حافز التارجت المقطوع (ر.س): *'),
        el('input', { type: 'number', id: 'bp-bonus', placeholder: 'مثال: 500', value: '500', required: true, style: 'width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:8px', oninput: updateFormulaPreview })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, '📈 أجر الطلب الإضافي فوق التارجت (ر.س):'),
        el('input', { type: 'number', step: '0.5', id: 'bp-over-rate', placeholder: 'مثال: 3.0', value: '3.0', style: 'width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:8px', oninput: updateFormulaPreview })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, '📉 أجر الطلب عند عدم تحقيق التارجت (ر.س/طلب):'),
        el('input', { type: 'number', step: '0.5', id: 'bp-below-rate', placeholder: 'مثال: 12.0', value: '12.0', style: 'width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:8px', oninput: updateFormulaPreview })
      ]),
    ]);

    const flatSection = el('div', { id: 'flat-plan-section', style: 'display:none;grid-template-columns:1fr;gap:12px' }, [
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, '⚡ سعر الطلب الثابت المباشر (ر.س / أوردر): *'),
        el('input', { type: 'number', step: '0.5', id: 'bp-flat-rate', placeholder: 'مثال: 15.0', value: '15.0', style: 'width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:8px', oninput: updateFormulaPreview })
      ])
    ]);

    const previewBox = el('div', {
      id: 'bp-preview-box',
      style: 'background:var(--soft);border:1px solid var(--border);border-radius:8px;padding:10px 14px;font-size:12px;color:var(--ink);line-height:1.5'
    });

    function updateFormulaPreview() {
      if (activePlanType === 'TARGET_TIER') {
        const t = document.getElementById('bp-target')?.value || 200;
        const b = document.getElementById('bp-bonus')?.value || 500;
        const o = document.getElementById('bp-over-rate')?.value || 3;
        const u = document.getElementById('bp-below-rate')?.value || 12;
        previewBox.innerHTML = `<b>📊 معادلة الاحتساب:</b><br>
        • عند تحقيق ${t} طلب أو أكثر: <b>${b} ر.س</b> مقطوعة + <b>${o} ر.س</b> عن كل طلب إضافي.<br>
        • عند عدم تحقيق التارجت (مثال: 150 طلباً): 150 × ${u} ر.س = <b>${(150 * Number(u)).toLocaleString('ar-SA')} ر.س</b>.`;
      } else {
        const f = document.getElementById('bp-flat-rate')?.value || 15;
        previewBox.innerHTML = `<b>📊 معادلة الاحتساب المباشر:</b><br>
        • أجر الطلب الثابت: <b>${f} ر.س</b> عن كل طلب منجز (مثال: 150 طلباً = <b>${(150 * Number(f)).toLocaleString('ar-SA')} ر.س</b>).`;
      }
    }

    updateFormulaPreview();

    content.append(
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:12px' }, [
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, '📑 العقد التجاري:'),
          contractSelect
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, '📍 فرع التشغيل:'),
          branchSelect
        ]),
      ]),
      planTypeSwitcher,
      targetSection,
      flatSection,
      previewBox,
      el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:14px;padding-top:12px;border-top:1px solid var(--border)' }, [
        el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
        el('button', { type: 'submit', class: 'btn btn-primary' }, '💾 حفظ خطة البونص')
      ])
    );

    const m = modal('🏆 إضافة وتهيئة خطة بونص لعقد', content);

    content.onsubmit = async (e) => {
      e.preventDefault();
      const planType = activePlanType;
      const contractId = document.getElementById('bp-contract').value;
      const branchId = document.getElementById('bp-branch').value;

      const payload = {
        plan_type: planType,
        contract_id: contractId ? Number(contractId) : null,
        contract_branch_id: branchId ? Number(branchId) : null,
      };

      if (planType === 'TARGET_TIER') {
        payload.target_orders = parseInt(document.getElementById('bp-target').value || 0);
        payload.bonus_amount = parseFloat(document.getElementById('bp-bonus').value || 0);
        payload.over_target_rate = parseFloat(document.getElementById('bp-over-rate').value || 0);
        payload.below_target_rate = parseFloat(document.getElementById('bp-below-rate').value || 0);
      } else {
        payload.flat_order_rate = parseFloat(document.getElementById('bp-flat-rate').value || 0);
      }

      try {
        await api.post('/hr/bonus', payload);
        alert('✅ تم حفظ خطة البونص بنجاح.');
        m.remove();
        if (onCreated) onCreated();
      } catch (err) {
        alert('❌ تعذر حفظ خطة البونص: ' + err.message);
      }
    };

  } catch (e) {
    alert('تعذر تحميل بيانات العقود: ' + e.message);
  }
}

async function openEditBonusPlanModal(plan, onUpdated) {
  const isTarget = (plan.plan_type || 'TARGET_TIER') === 'TARGET_TIER';
  let activePlanType = isTarget ? 'TARGET_TIER' : 'FLAT_PER_ORDER';

  const content = el('form', { style: 'display:grid;gap:14px;direction:rtl' });

  const targetSection = el('div', { id: 'ebp-target-section', style: `display:${isTarget ? 'grid' : 'none'};gap:10px` }, [
    el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, '🎯 تارجت الطلبات الشهري: *'),
        el('input', { type: 'number', id: 'ebp-target', value: plan.target_orders || 250, required: isTarget, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, '💰 مبلغ الحافز المقطوع عند تحقيق التارجت (ر.س): *'),
        el('input', { type: 'number', step: '10', id: 'ebp-bonus', value: plan.bonus_amount || 1000, required: isTarget, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
      ]),
    ]),
    el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, '⚡ أجر كل طلب إضافي فوق التارجت (ر.س):'),
        el('input', { type: 'number', step: '0.5', id: 'ebp-over-rate', value: plan.over_target_rate || 14, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, '🔻 سعر الطلب في حال عدم تحقيق التارجت (ر.س):'),
        el('input', { type: 'number', step: '0.5', id: 'ebp-below-rate', value: plan.below_target_rate || 12, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
      ]),
    ])
  ]);

  const flatSection = el('div', { id: 'ebp-flat-section', style: `display:${!isTarget ? 'block' : 'none'}` }, [
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, '⚡ سعر التوصيل الثابت لكل طلب منجز (ر.س): *'),
      el('input', { type: 'number', step: '0.5', id: 'ebp-flat-rate', value: plan.flat_order_rate || 15, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
    ])
  ]);

  content.append(
    el('div', {}, [
      el('p', { style: 'margin:0 0 10px 0;font-size:13px;color:var(--text)' }, [
        el('span', {}, 'تعديل خطة بونص: '),
        el('b', {}, `${plan.contract_name || plan.contract || 'عقد عام'}${plan.branch ? ` — ${plan.branch}` : ''}`)
      ]),
    ]),
    targetSection,
    flatSection,
    el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:14px;padding-top:12px;border-top:1px solid var(--border)' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
      el('button', { type: 'submit', class: 'btn btn-primary' }, '💾 حفظ التعديلات')
    ])
  );

  const m = modal('✏️ تعديل خطة البونص والحوافز', content);

  content.onsubmit = async (e) => {
    e.preventDefault();
    const payload = {
      plan_type: activePlanType,
    };
    if (activePlanType === 'TARGET_TIER') {
      payload.target_orders = parseInt(document.getElementById('ebp-target').value || 0);
      payload.bonus_amount = parseFloat(document.getElementById('ebp-bonus').value || 0);
      payload.over_target_rate = parseFloat(document.getElementById('ebp-over-rate').value || 0);
      payload.below_target_rate = parseFloat(document.getElementById('ebp-below-rate').value || 0);
    } else {
      payload.flat_order_rate = parseFloat(document.getElementById('ebp-flat-rate').value || 0);
    }

    try {
      await api.patch(`/hr/bonus/${plan.id}`, payload);
      alert('✅ تم تعديل خطة البونص بنجاح.');
      m.remove();
      if (onUpdated) onUpdated();
    } catch (err) {
      alert('❌ تعذر التعديل: ' + err.message);
    }
  };
}



// ─────────────────────────────────────────────────────────────────────────────
// TAB 4: تسويات مشغلي 3PL التجارية (B2B COMMERCIAL SETTLEMENTS)
// ─────────────────────────────────────────────────────────────────────────────
async function renderSettlements(container) {
  container.append(loadingState('جاري تحميل تسويات مشغلي 3PL...'));

  try {
    const [settlements, operators] = await Promise.all([
      api.get('/analytics/operators/settlements').catch(() => []),
      api.get('/enterprise/operators').catch(() => [])
    ]);

    container.innerHTML = '';

    container.append(el('div', { class: 'card', style: 'padding:16px;background:var(--card);border:1px solid var(--border);border-radius:12px' }, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:14px' }, [
        el('div', {}, [
          el('h3', { style: 'margin:0;font-size:15px;color:var(--text)' }, '🤝 تسويات عقود شركات التشغيل (3PL Commercial Settlements)'),
          el('p', { style: 'margin:4px 0 0 0;font-size:12px;color:var(--muted)' }, 'حساب مستحقات الشركات المشغلة بناءً على الأوردرات المكتملة وشروط العقود')
        ]),
        el('button', {
          class: 'btn btn-primary btn-small',
          onclick: () => openCalculateSettlementModal(operators, () => renderSettlements(container))
        }, '➕ حساب تسوية مشغل جديدة')
      ]),
      settlements.length ? table([
        { key: 'operator_id', label: 'المشغل', render: (v) => {
          const op = operators.find(o => o.operator_tenant_id === v);
          return el('b', { style: 'color:var(--text)' }, op?.name || `مشغل #${v}`);
        }},
        { key: 'period_month', label: 'فترة التسوية' },
        { key: 'eligible_orders', label: 'الطلبات المكتملة', render: (v) => (v || 0).toLocaleString('ar-SA') },
        { key: 'base_amount', label: 'المبلغ الأساسي', render: (v) => `${(v || 0).toLocaleString('ar-SA')} ر.س` },
        { key: 'bonus_amount', label: 'البونص', render: (v) => `+${(v || 0).toLocaleString('ar-SA')} ر.س` },
        { key: 'penalty_amount', label: 'الغرامات', render: (v) => `-${(v || 0).toLocaleString('ar-SA')} ر.س` },
        { key: 'net_amount', label: 'صافي المستحق للمشغل', render: (v) => el('b', { style: 'color:var(--text);font-size:13px' }, `${(v || 0).toLocaleString('ar-SA')} ر.س`) },
        { key: 'status', label: 'الحالة', render: (v) => el('span', { class: `badge badge-${v === 'APPROVED' ? 'green' : 'amber'}` }, v === 'APPROVED' ? '✅ معتمد للصرف' : '✏️ مسودة') },
      ], settlements) : emptyState('لا توجد تسويات تجارية مسجلة. اضغط "حساب تسوية مشغل جديدة" لاحتساب مستحقات 3PL.')
    ]));

  } catch (e) {
    container.innerHTML = '';
    container.append(errorState('تعذر تحميل التسويات: ' + e.message, () => renderSettlements(container)));
  }
}

function openCalculateSettlementModal(operators, onSaved) {
  const form = el('form', { onsubmit: async (e) => {
    e.preventDefault();
    const opId = document.getElementById('calc-op-id').value;
    const month = document.getElementById('calc-op-month').value;
    if (!opId || !month) return alert('اختر المشغل والشهر.');
    try {
      await api.post(`/analytics/operators/settlement/save?operator_id=${opId}&period_month=${month}`);
      alert('✅ تم حساب وحفظ مسودة التسوية بنجاح.');
      if (m && m.remove) m.remove();
      onSaved();
    } catch (err) {
      alert('❌ فشل الحساب: ' + err.message);
    }
  }}, [
    el('div', { style: 'display:grid;gap:12px;margin-bottom:16px' }, [
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'شركة التشغيل 3PL:'),
        el('select', { id: 'calc-op-id', style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' }, [
          el('option', { value: '' }, 'اختر المشغل...'),
          ...operators.map(o => el('option', { value: String(o.operator_tenant_id) }, o.name || `مشغل #${o.operator_tenant_id}`))
        ])
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'شهر التسوية:'),
        el('input', { type: 'month', id: 'calc-op-month', value: selectedPayrollMonth, style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' })
      ]),
    ]),
    el('div', { style: 'display:flex;justify-content:flex-end;gap:8px' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => { if (m && m.remove) m.remove(); } }, 'إلغاء'),
      el('button', { type: 'submit', class: 'btn btn-primary' }, 'احتساب وحفظ التسوية')
    ])
  ]);
  const m = modal('حساب تسوية تجارية لشركة مشغلة 3PL', form);
}
