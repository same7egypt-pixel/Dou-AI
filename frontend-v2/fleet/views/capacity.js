// Modern Capacity, Commercial Contracts & Platform Ecosystem Operations — Frontend V2
import { api } from '../../shared/api/client.js';
import { appStore, isDeliveryPlatform, can } from '../../shared/state/store.js';
import { el, loadingState, emptyState, errorState, metricCard, button, modal, formRow, inputField, selectField, table, badge, searchableSelect } from '../../shared/components/ui.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

let activeCapacityTab = 'capacity'; // capacity | contracts | operators | settlements

export async function loadCapacity(container) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';
  const isPlatform = isDeliveryPlatform();
  const role = appStore.get().role || localStorage.getItem('dou_role_v2') || 'COMPANY_ADMIN';
  const isAdmin = ['COMPANY', 'COMPANY_ADMIN', 'DOU_ADMIN', 'DOU_OPS'].includes(role);

  const titleText = isPlatform 
    ? (isAr ? 'تخطيط السعة والمنظومة التشغيلية' : 'Capacity Planning & Ecosystem')
    : (isAr ? 'تخطيط السعة والعقود التجارية' : 'Capacity Planning & Commercial Contracts');

  const headerActions = [
    el('button', { class: 'btn btn-ghost', onclick: () => loadCapacity(container) }, isAr ? '↻ تحديث' : '↻ Refresh'),
  ];

  // The operating structure — contracts, cities, branches, supervisors — belongs
  // to every account that manages riders. A platform used to have it replaced by
  // the vendor network rather than added to it, so an account holding
  // MANAGE_RIDERS and MANAGE_SUPERVISORS had no screen that could create the
  // contract, branch and supervisor that adding a rider requires. It could not
  // add a single rider.
  if (isAdmin && activeCapacityTab === 'contracts') {
    headerActions.unshift(
      el('button', { class: 'btn btn-primary', onclick: () => openCreateContractModal(container) }, isAr ? '➕ إنشاء عقد تجاري جديد' : '➕ New Commercial Contract'),
      el('button', { class: 'btn btn-secondary', onclick: () => openSupervisorsManagementModal(container) }, isAr ? '👔 إدارة المشرفين' : '👔 Manage Supervisors')
    );
  } else if (isAdmin && activeCapacityTab === 'operators') {
    headerActions.unshift(
      el('button', { class: 'btn btn-primary', onclick: () => openAddOperatorModal(container) }, isAr ? '➕ إضافة / ربط شركة لوجستية' : '➕ Link 3PL Partner')
    );
  } else if (isPlatform && activeCapacityTab === 'settlements' && isAdmin) {
    headerActions.unshift(
      el('button', { class: 'btn btn-primary', onclick: () => openCalculateSettlementModal(container) }, isAr ? '➕ حساب تسوية مشغل جديدة' : '➕ Calculate 3PL Settlement')
    );
  }

  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isPlatform ? (isAr ? 'إدارة المنظومة والشركات' : 'Ecosystem & Partner Management') : (isAr ? 'الهيكل التشغيلي والعقود' : 'Operational Structure & Contracts')),
      el('h1', { text: titleText })
    ]),
    el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' }, headerActions),
  ]));

  // Sub-Tabs Navigation
  const tabsList = [
    { id: 'capacity', label: isAr ? '📊 تخطيط السعة والاحتياج' : '📊 Capacity & Demand Planning' },
    { id: 'contracts', label: isAr ? '📑 العقود التجارية وفروع التشغيل' : '📑 Commercial Contracts & Branches' },
  ];
  // Added for a platform, never substituted for the structure above.
  if (can('MANAGE_OPERATORS')) {
    tabsList.push({ id: 'operators', label: isAr ? '🏢 الشركات اللوجستية المشغلة (3PL)' : '🏢 3PL Operating Partners' });
  }
  if (can('OPERATOR_SETTLEMENTS')) {
    tabsList.push({ id: 'settlements', label: isAr ? '💼 تسويات ومستحقات مشغلي 3PL' : '💼 3PL Commercial Settlements' });
  }
  // A tab the account can no longer reach must not stay selected.
  if (!tabsList.some((tab) => tab.id === activeCapacityTab)) activeCapacityTab = 'capacity';

  const tabsNav = el('div', { class: 'tabs', style: 'margin-bottom:16px' }, 
    tabsList.map(tab => el('button', {
      class: `tab ${activeCapacityTab === tab.id ? 'active' : ''}`,
      onclick: () => {
        activeCapacityTab = tab.id;
        loadCapacity(container);
      }
    }, tab.label))
  );
  container.append(tabsNav);

  const contentArea = el('div', { id: 'cap-tab-content' });
  container.append(contentArea);

  if (activeCapacityTab === 'capacity') {
    renderCapacityPlanning(contentArea, container, isPlatform);
  } else if (activeCapacityTab === 'contracts') {
    renderContractsManagement(contentArea, container, isAdmin);
  } else if (activeCapacityTab === 'operators') {
    renderPlatformOperators(contentArea, container, isAdmin);
  } else if (activeCapacityTab === 'settlements') {
    renderPlatformSettlements(contentArea, container, isAdmin);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 1: تخطيط السعة وتوزيع الورديات (CAPACITY PLANNING)
// ─────────────────────────────────────────────────────────────────────────────
async function renderCapacityPlanning(contentArea, mainContainer, isPlatform) {
  const isAr = getLang() === 'ar';
  const filters = el('div', { class: 'filters', style: 'margin-bottom:16px' }, [
    el('select', { id: 'cap-scope-type', onchange: () => loadCapacityMetrics(contentArea, isPlatform) }, [
      el('option', { value: '' }, isAr ? 'كل الشركة' : 'All Scopes (Company)'),
      el('option', { value: 'PROJECT' }, isAr ? 'مشروع' : 'Project'),
      el('option', { value: 'BRANCH' }, isAr ? 'فرع' : 'Branch'),
      el('option', { value: 'OPERATOR' }, isAr ? 'مشغّل' : 'Operator'),
    ]),
    el('input', { id: 'cap-scope-id', type: 'number', placeholder: isAr ? 'رقم النطاق' : 'Scope ID', onchange: () => loadCapacityMetrics(contentArea, isPlatform) }),
    el('input', { id: 'cap-required', type: 'number', placeholder: isAr ? 'عدد مطلوب' : 'Required Count', min: '0' }),
    el('input', { id: 'cap-effective', type: 'date', value: new Date().toISOString().slice(0, 10) }),
    el('button', { class: 'btn btn-blue', onclick: () => saveRequirement(mainContainer) }, isAr ? 'حفظ الاحتياج' : 'Save Requirement'),
  ]);
  contentArea.append(filters);

  const resultsDiv = el('div', { id: 'cap-results' }, [loadingState(isAr ? 'جاري تحميل بيانات السعة...' : 'Loading capacity data...')]);
  contentArea.append(resultsDiv);

  loadCapacityMetrics(contentArea, isPlatform);
}

async function loadCapacityMetrics(container, isPlatform) {
  const isAr = getLang() === 'ar';
  const result = document.getElementById('cap-results') || container;
  const scopeType = document.getElementById('cap-scope-type')?.value || '';
  const scopeId = document.getElementById('cap-scope-id')?.value || '';
  const params = new URLSearchParams();
  if (scopeType) params.set('scope_type', scopeType);
  if (scopeId) params.set('scope_id', scopeId);

  try {
    const [capData, healthData] = await Promise.all([
      api.get('/analytics/capacity/status' + (params.toString() ? '?' + params : '')).catch(() => ({})),
      isPlatform ? api.get('/analytics/operators/health').catch(() => null) : Promise.resolve(null),
    ]);

    result.innerHTML = '';

    // Platform Health Cards
    if (isPlatform && healthData) {
      result.append(el('div', { class: 'card', style: 'margin-bottom:16px' }, [
        el('h3', { text: isAr ? '🌐 مؤشرات المنظومة التشغيلية' : '🌐 Ecosystem Operations KPIs' }),
        el('div', { class: 'cards', style: 'margin-top:12px' }, [
          metricCard(healthData.total_operators || 0, isAr ? 'إجمالي المشغلين المرتبطين' : 'Total Linked 3PL Operators'),
          metricCard(healthData.riders_without_assignment || 0, isAr ? 'سائقون بانتظار إسناد مشغل' : 'Drivers Awaiting 3PL Assignment', healthData.riders_without_assignment > 0 ? 'alert' : 'trend'),
          metricCard(healthData.pending_settlements || 0, isAr ? 'تسويات B2B معلقة' : 'Pending B2B Settlements', healthData.pending_settlements > 0 ? 'amber' : 'trend'),
        ])
      ]));
    }

    // Capacity Cards
    result.append(el('div', { class: 'cards' }, [
      metricCard(capData.required || 0, isAr ? 'المطلوب' : 'Required'),
      metricCard(capData.available || 0, isAr ? 'المتاح' : 'Available'),
      metricCard(capData.assigned || 0, isAr ? 'الموزع على ورديات' : 'Assigned to Shifts'),
      metricCard(capData.active || 0, isAr ? 'الحاضر فعلياً' : 'Actually Present'),
      metricCard(capData.shortage || 0, isAr ? 'العجز' : 'Shortage / Deficit', 'alert'),
      metricCard(capData.surplus || 0, isAr ? 'الفائض' : 'Surplus', 'trend'),
    ]));

  } catch (e) {
    result.innerHTML = '';
    result.append(errorState((isAr ? 'تعذر تحميل بيانات السعة: ' : 'Failed to load capacity data: ') + e.message));
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB 2: إدارة العقود / الشركات اللوجستية المشغلة
// ─────────────────────────────────────────────────────────────────────────────
async function renderContractsManagement(contentArea, mainContainer, isAdmin) {
  // No platform redirect. The vendor network has its own tab now; this one is
  // the operating structure, and every account type needs it.
  contentArea.append(loadingState('جاري تحميل العقود وفروع التشغيل...'));

  try {
    const contracts = await api.get('/hr/contracts').catch(() => ({ rows: [] }));
    const rows = contracts.rows || [];

    contentArea.innerHTML = '';

    // Header Metrics
    const totalBranches = rows.reduce((acc, c) => acc + (c.branches?.length || 0), 0);
    const expiringCount = rows.filter(c => c.status === 'EXPIRING' || c.status === 'EXPIRED').length;
    const totalCouriers = rows.reduce((acc, c) => acc + (c.couriers_count || 0), 0);

    contentArea.append(el('div', { class: 'cards', style: 'margin-bottom:16px' }, [
      metricCard(rows.length, 'إجمالي العقود التجارية النشطة', 'blue'),
      metricCard(totalBranches, 'إجمالي فروع التشغيل والمدن', 'blue'),
      metricCard(totalCouriers, 'المناديب المسندين للعقود', 'blue'),
      metricCard(expiringCount, 'عقود تتطلب تجديداً', expiringCount > 0 ? 'alert' : 'trend'),
    ]));

    if (!rows.length) {
      contentArea.append(emptyState('لا توجد عقود تجارية مسجلة حالياً. اضغط "➕ إنشاء عقد تجاري جديد" لإضافة أول عقد.'));
      return;
    }

    // Contracts List
    const contractsList = el('div', { style: 'display:grid;gap:16px' });
    rows.forEach(ct => {
      const isExpiring = ct.status === 'EXPIRING' || (ct.days_left !== null && ct.days_left <= 30 && ct.days_left >= 0);
      const isExpired = ct.status === 'EXPIRED' || (ct.days_left !== null && ct.days_left < 0);
      const statusBadge = isExpired ? el('span', { class: 'badge badge-alert' }, 'منتهي الصلاحية') :
                          isExpiring ? el('span', { class: 'badge badge-amber' }, `ينتهي خلال ${ct.days_left} يوم`) :
                          el('span', { class: 'badge badge-green' }, 'ساري ونشط');

      const branchesList = el('div', { style: 'display:grid;grid-template-columns:repeat(auto-fill, minmax(260px, 1fr));gap:10px;margin-top:12px' });
      (ct.branches || []).forEach(b => {
        branchesList.append(el('div', { style: 'background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px 14px' }, [
          el('div', { style: 'display:flex;justify-content:space-between;align-items:center' }, [
            el('b', { style: 'color:var(--text);font-size:14px' }, `📍 ${b.city || 'الفرع'}`),
            el('span', { class: 'badge badge-blue', style: 'font-size:11px' }, `${b.couriers_count || 0} سائق`)
          ]),
          el('div', { style: 'font-size:11.5px;color:var(--muted);margin-top:4px;display:flex;align-items:center;justify-content:space-between' }, [
            el('div', { style: 'display:flex;align-items:center;gap:4px' }, [
              el('span', {}, '👔 المشرف: '),
              el('span', { style: 'color:var(--text);font-weight:600' }, (b.supervisors && b.supervisors.length) ? b.supervisors.map(s => s.name).join('، ') : (b.supervisor || 'بدون مشرف'))
            ]),
            isAdmin ? el('button', {
              class: 'btn btn-ghost btn-small',
              style: 'padding:1px 6px;font-size:10.5px;color:var(--red)',
              title: 'حذف هذا الفرع',
              onclick: async () => {
                if (!confirm(`هل تريد بالتأكيد حذف فرع (${b.city}) من هذا العقد؟`)) return;
                try {
                  await api.delete(`/hr/contract-branches/${b.id}`);
                  alert('✅ تم حذف الفرع بنجاح.');
                  loadCapacity(mainContainer);
                } catch (err) {
                  alert('❌ تعذر الحذف: ' + err.message);
                }
              }
            }, '🗑️') : null
          ])
        ]));
      });

      const cardActions = [];
      if (isAdmin) {
        cardActions.push(
          el('button', { class: 'btn btn-ghost btn-small', onclick: () => openAddBranchToContractModal(ct, mainContainer) }, '➕ إضافة فرع'),
          el('button', { class: 'btn btn-ghost btn-small', onclick: () => openRenewContractModal(ct, mainContainer) }, '🔄 تجديد العقد'),
          el('button', { class: 'btn btn-ghost btn-small', style: 'color:var(--primary)', onclick: () => openEditContractModal(ct, mainContainer) }, '✏️ تعديل'),
          el('button', {
            class: 'btn btn-ghost btn-small',
            style: 'color:var(--red)',
            onclick: async () => {
              if (!confirm(`هل تريد بالتأكيد حذف / تعطيل العقد (${ct.name})؟`)) return;
              try {
                await api.delete(`/hr/contracts/${ct.id}`);
                alert('✅ تم تعطيل / حذف العقد بنجاح.');
                loadCapacity(mainContainer);
              } catch (err) {
                alert('❌ تعذر الحذف: ' + err.message);
              }
            }
          }, '🗑️ حذف')
        );
      }

      const card = el('div', { class: 'card', style: 'padding:18px;background:var(--card);border:1px solid var(--border);border-radius:12px' }, [
        el('div', { style: 'display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px' }, [
          el('div', {}, [
            el('div', { style: 'display:flex;align-items:center;gap:8px' }, [
              el('h3', { style: 'margin:0;font-size:16px;color:var(--text)' }, ct.name),
              statusBadge,
              ct.client_rate_per_order ? el('span', { class: 'badge badge-blue' }, `سعر الطلب: ${ct.client_rate_per_order} ر.س`) : null,
            ]),
            el('div', { style: 'font-size:12px;color:var(--muted);margin-top:4px' }, [
              el('span', {}, `العميل: ${ct.client_name || ct.name} | تاريخ البداية: ${ct.start_date ? ct.start_date.slice(0, 10) : '—'} | تاريخ الانتهاء: ${ct.end_date ? ct.end_date.slice(0, 10) : '—'}`)
            ])
          ]),
          el('div', { style: 'display:flex;gap:4px;flex-wrap:wrap' }, cardActions)
        ]),
        el('div', { style: 'margin-top:14px;border-top:1px solid var(--border);padding-top:10px' }, [
          el('div', { style: 'font-size:12px;font-weight:700;color:var(--muted);margin-bottom:6px' }, `فروع التشغيل والمدن المعتمدة (${ct.branches?.length || 0}):`),
          branchesList
        ])
      ]);

      contractsList.append(card);
    });

    contentArea.append(contractsList);

  } catch (e) {
    contentArea.innerHTML = '';
    contentArea.append(errorState('تعذر تحميل العقود: ' + e.message, () => renderContractsManagement(contentArea, mainContainer, isAdmin)));
  }
}

async function renderPlatformOperators(contentArea, mainContainer, isAdmin) {
  contentArea.append(loadingState('جاري تحميل بيانات الشركات اللوجستية المشغلة...'));

  try {
    const [operatorsData, healthData, couriersData] = await Promise.all([
      api.get('/enterprise/operators').catch(() => []),
      api.get('/analytics/operators/health').catch(() => ({ operators: [] })),
      api.get('/fleet/couriers/page?page=1&page_size=100').catch(() => ({ rows: [], total: 0 }))
    ]);

    const operators = operatorsData || [];
    const healthList = healthData.operators || [];
    const couriers = couriersData.rows || [];
    const totalCouriers = couriersData.total || couriers.length;
    const directFreelancers = couriers.filter(c => c.courier_type === 'FREELANCER').length;
    const operatorCouriers = Math.max(0, totalCouriers - directFreelancers);

    contentArea.innerHTML = '';

    // Every number here is the tenant's own, or it is not shown. This screen used
    // to invent what it lacked: `operators.length || 2`, a hardcoded 98.4% SLA,
    // and two fictional companies with fabricated CR numbers — so a platform
    // with no vendors was shown an imaginary business as if it were its own.
    contentArea.append(el('div', { class: 'cards', style: 'margin-bottom:16px' }, [
      metricCard(operators.length, 'الشركات اللوجستية المشغلة (3PL)', 'blue'),
      metricCard(operatorCouriers, 'مناديب شركات 3PL', 'blue'),
      metricCard(directFreelancers, 'مناديب فريلانسر مستقلين', 'trend'),
      metricCard(totalCouriers, 'إجمالي المناديب في المنظومة', 'good'),
    ]));

    if (!operators.length) {
      contentArea.append(emptyState(
        'لا توجد شركات لوجستية مرتبطة بعد. اضغط «➕ إضافة / ربط شركة لوجستية» لربط شركة مسجّلة في DOU بمنصتك.'
      ));
      return;
    }
    const displayOps = operators;

    const list = el('div', { style: 'display:grid;gap:16px' });
    displayOps.forEach(op => {
      const h = healthList.find(x => x.operator_id === op.id || x.operator_id === op.operator_tenant_id) || {};
      // No `|| 28 : 20`. A vendor with no riders reads zero, which is a fact the
      // platform needs rather than a gap to paper over.
      const opRidersCount = couriers.filter(c => c.operator_id === op.id || c.operator_id === op.operator_tenant_id).length
        || h.active_couriers || 0;
      const dash = (v) => (v === null || v === undefined || v === '' ? '—' : v);

      const card = el('div', { class: 'card', style: 'padding:18px;background:var(--card);border:1px solid var(--border);border-radius:12px' }, [
        el('div', { style: 'display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px' }, [
          el('div', {}, [
            el('div', { style: 'display:flex;align-items:center;gap:8px' }, [
              el('h3', { style: 'margin:0;font-size:16px;color:var(--text)' }, `🏢 ${op.name || op.operator_name || 'شركة لوجستية مشغلة'}`),
              el('span', { class: 'badge badge-green' }, '● شريك 3PL معتمد'),
              op.rate_per_order ? el('span', { class: 'badge badge-blue' }, `سعر التوصيل: ${op.rate_per_order} ر.س / طلب`) : null,
            ]),
            el('div', { style: 'font-size:12px;color:var(--muted);margin-top:4px' }, [
              el('span', {}, `طبيعة الشراكة: ${dash(op.relationship_type)} | السجل التجاري: ${dash(op.cr_number)} | نسبة تحقيق السعة: ${dash(h.sla_fulfillment)}`)
            ])
          ]),
          el('div', { style: 'display:flex;gap:6px' }, [
            el('button', {
              class: 'btn btn-ghost btn-small',
              onclick: () => {
                activeCapacityTab = 'settlements';
                loadCapacity(mainContainer);
              }
            }, '💼 تسوية مالية B2B'),
          ])
        ]),
        el('div', { style: 'margin-top:14px;border-top:1px solid var(--border);padding-top:10px;display:grid;grid-template-columns:repeat(auto-fill, minmax(200px, 1fr));gap:10px' }, [
          el('div', { style: 'background:var(--bg);padding:8px 12px;border-radius:8px;border:1px solid var(--border)' }, [
            el('small', { style: 'display:block;color:var(--muted);font-size:11px' }, 'مناديب الشركة المسندين:'),
            el('b', { style: 'color:var(--text);font-size:14px' }, `${opRidersCount} سائق`)
          ]),
          el('div', { style: 'background:var(--bg);padding:8px 12px;border-radius:8px;border:1px solid var(--border)' }, [
            el('small', { style: 'display:block;color:var(--muted);font-size:11px' }, 'معدل الطلبات اليومية:'),
            el('b', { style: 'color:var(--primary);font-size:14px' }, `${dash(h.daily_orders)} طلب/يوم`)
          ]),
          el('div', { style: 'background:var(--bg);padding:8px 12px;border-radius:8px;border:1px solid var(--border)' }, [
            el('small', { style: 'display:block;color:var(--muted);font-size:11px' }, 'مدن ونطاقات التغطية:'),
            el('b', { style: 'color:var(--text);font-size:12px' }, dash(op.cities))
          ]),
        ])
      ]);
      list.append(card);
    });

    contentArea.append(list);

  } catch (e) {
    contentArea.innerHTML = '';
    contentArea.append(errorState('تعذر تحميل بيانات الشركات اللوجستية: ' + e.message, () => renderPlatformOperators(contentArea, mainContainer, isAdmin)));
  }
}

export async function openAddOperatorModal(mainContainer) {
  // This form used to be a mock: its submit handler read the company name,
  // showed "✅ تم ربط الشركة اللوجستية بنجاح" and closed — no API call, nothing
  // saved. It also asked for a CR number, a rate and a free-text city list, none
  // of which PlatformOperator can store, so even a wired version of that form
  // would have discarded them.
  //
  // What the relationship actually is: DOU administration creates companies, and
  // a platform links the ones it already works with. So the form asks for the
  // one thing that identifies an existing company without letting a platform
  // enumerate every tenant on DOU — the phone its admin signs in with.
  const isAr = getLang() === 'ar';
  let sources = [];
  try {
    sources = await api.get('/enterprise/source-platforms');
  } catch (err) {
    alert('❌ تعذر تحميل بيانات المنصة: ' + err.message);
    return;
  }

  const content = el('form', { style: 'display:grid;gap:14px;direction:rtl' }, [
    el('p', { style: 'margin:0;font-size:12px;color:var(--muted);line-height:1.7' },
      'الشركات تُنشأ من إدارة DOU. هنا تربط شركة لوجستية مسجّلة بالفعل لتصبح مورّدًا لمنصتك — ' +
      'أدخل جوال دخول مسؤول الشركة كما هو مسجّل لديه.'),

    el('div', {}, [
      el('label', { for: 'op-phone', style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' },
        'جوال دخول مسؤول الشركة: *'),
      el('input', {
        id: 'op-phone', required: true, placeholder: '9665xxxxxxxx', inputmode: 'numeric',
        style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px'
      }),
    ]),

    sources.length > 1 ? el('div', {}, [
      el('label', { for: 'op-source', style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' },
        'منصة المصدر:'),
      el('select', { id: 'op-source', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' },
        sources.map(sp => el('option', { value: String(sp.id) }, sp.name || sp.code))),
    ]) : null,

    el('div', {}, [
      el('label', { for: 'op-relationship', style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' },
        'طبيعة الشراكة:'),
      el('select', { id: 'op-relationship', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' }, [
        el('option', { value: 'OPERATOR' }, 'مشغّل 3PL'),
        el('option', { value: 'PARTNER' }, 'شريك تشغيلي'),
      ]),
    ]),

    el('p', { id: 'op-msg', style: 'margin:0;font-size:12px;min-height:16px' }),

    el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:6px;padding-top:12px;border-top:1px solid var(--border)' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
      el('button', { type: 'submit', class: 'btn btn-primary', id: 'op-submit' }, '💾 ربط الشركة المشغلة')
    ])
  ].filter(Boolean));

  const m = modal('🏢 ربط شركة لوجستية مشغلة (3PL Partner)', content);

  content.onsubmit = async (e) => {
    e.preventDefault();
    const msg = document.getElementById('op-msg');
    const btn = document.getElementById('op-submit');
    const sourceSelect = document.getElementById('op-source');
    btn.disabled = true;
    msg.style.color = 'var(--muted)';
    msg.textContent = '⏳ جاري الربط…';
    try {
      const res = await api.post('/enterprise/operators/link', {
        admin_phone: document.getElementById('op-phone').value.trim(),
        relationship_type: document.getElementById('op-relationship').value,
        ...(sourceSelect ? { source_platform_id: Number(sourceSelect.value) } : {}),
      });
      msg.style.color = 'var(--green)';
      msg.textContent = `✅ تم ربط «${res.name}» بالمنصة.`;
      setTimeout(() => { m.remove(); loadCapacity(mainContainer); }, 1200);
    } catch (err) {
      msg.style.color = 'var(--red)';
      msg.textContent = '❌ ' + err.message;
      btn.disabled = false;
    }
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// MODALS: CREATE CONTRACT, RENEW, ADD BRANCH, ADD SUPERVISOR
// ─────────────────────────────────────────────────────────────────────────────
export async function openCreateContractModal(mainContainer) {
  try {
    const [citiesData, supervisorsData] = await Promise.all([
      api.get('/hr/operating-cities').catch(() => []),
      api.get('/hr/supervisors').catch(() => []),
    ]);

    const cities = citiesData.cities || citiesData || [];
    const supervisors = supervisorsData || [];

    const defaultCityOptions = cities.length ? cities : [
      { id: 1, name: 'الرياض' },
      { id: 2, name: 'جدة' },
      { id: 3, name: 'الدمام' },
      { id: 4, name: 'مكة المكرمة' },
    ];

    let branchesList = [
      { city_id: defaultCityOptions[0]?.id || 1, city: defaultCityOptions[0]?.name || 'الرياض', supervisor_ids: [] }
    ];

    const modalContent = el('form', { style: 'display:grid;gap:14px' });

    function renderBranchInputs() {
      let branchesContainer = modalContent.querySelector('#branches-container');
      if (!branchesContainer) {
        branchesContainer = el('div', { id: 'branches-container', style: 'display:grid;gap:10px' });
      }
      branchesContainer.innerHTML = '';

      branchesList.forEach((b, idx) => {
        const row = el('div', { style: 'display:flex;gap:10px;align-items:center;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px' }, [
          el('div', { style: 'flex:1' }, [
            el('label', { style: 'display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:3px' }, 'المدينة / الفرع:'),
            el('select', {
              style: 'width:100%;padding:6px;border:1px solid var(--border);border-radius:6px;background:var(--card);color:var(--text)',
              onchange: (e) => {
                const opt = defaultCityOptions.find(c => String(c.id) === e.target.value);
                b.city_id = Number(e.target.value);
                b.city = opt ? opt.name : 'المدينة';
              }
            }, defaultCityOptions.map(c => el('option', { value: String(c.id), selected: b.city_id === c.id }, c.name)))
          ]),
          el('div', { style: 'flex:1.5' }, [
            el('label', { style: 'display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:3px' }, 'المشرف المسؤول (أو عدة مشرفين):'),
            el('select', {
              style: 'width:100%;padding:6px;border:1px solid var(--border);border-radius:6px;background:var(--card);color:var(--text)',
              onchange: (e) => {
                b.supervisor_ids = e.target.value ? [Number(e.target.value)] : [];
              }
            }, [
              el('option', { value: '' }, 'بدون مشرف حالياً'),
              ...supervisors.map(s => el('option', { value: String(s.id), selected: b.supervisor_ids.includes(s.id) }, s.name))
            ])
          ]),
          branchesList.length > 1 ? el('button', {
            type: 'button',
            class: 'btn btn-ghost btn-small',
            style: 'color:var(--red);align-self:flex-end',
            onclick: () => {
              branchesList.splice(idx, 1);
              renderBranchInputs();
            }
          }, '✖') : null
        ].filter(Boolean));

        branchesContainer.append(row);
      });

      return branchesContainer;
    }

    modalContent.append(
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:12px' }, [
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'اسم العقد: *'),
          el('input', { id: 'ct-name', placeholder: 'مثال: عقد هنقرستيشن - الرياض والشرقية', required: true, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'اسم العميل / المنصة:'),
          el('input', { id: 'ct-client', placeholder: 'مثال: HungerStation', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
        ]),
      ]),
      el('div', { style: 'display:grid;grid-template-columns:repeat(3, 1fr);gap:12px' }, [
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'سعر الطلب للعميل (ر.س):'),
          el('input', { type: 'number', step: '0.5', id: 'ct-rate', placeholder: 'مثال: 16.00', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'تاريخ البداية:'),
          el('input', { type: 'date', id: 'ct-start', value: new Date().toISOString().slice(0, 10), style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'تاريخ الانتهاء:'),
          el('input', { type: 'date', id: 'ct-end', value: new Date(Date.now() + 365*24*3600*1000).toISOString().slice(0, 10), style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
        ]),
      ]),
      el('div', { style: 'margin-top:10px' }, [
        el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:8px' }, [
          el('label', { style: 'font-size:13px;font-weight:700' }, '📍 فروع التشغيل والمشرفين التابعين للعقد:'),
          el('button', {
            type: 'button',
            class: 'btn btn-ghost btn-small',
            onclick: () => {
              branchesList.push({ city_id: defaultCityOptions[0]?.id || 1, city: defaultCityOptions[0]?.name || 'الرياض', supervisor_ids: [] });
              renderBranchInputs();
            }
          }, '➕ إضافة فرع آخر')
        ]),
        renderBranchInputs()
      ]),
      el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:14px' }, [
        el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
        el('button', { type: 'submit', class: 'btn btn-primary' }, 'حفظ وإنشاء العقد')
      ])
    );

    const m = modal('➕ إنشاء عقد تجاري جديد وفروع التشغيل', modalContent);

    modalContent.onsubmit = async (e) => {
      e.preventDefault();
      const name = document.getElementById('ct-name').value;
      const clientName = document.getElementById('ct-client').value || name;
      const rate = document.getElementById('ct-rate').value ? parseFloat(document.getElementById('ct-rate').value) : null;
      const startDate = document.getElementById('ct-start').value;
      const endDate = document.getElementById('ct-end').value;

      try {
        await api.post('/hr/contracts', {
          name,
          client_name: clientName,
          client_rate_per_order: rate,
          contract_type: 'COMMERCIAL',
          start_date: startDate,
          end_date: endDate,
          cities: branchesList.map(b => ({
            city_id: b.city_id,
            city: b.city,
            supervisor_ids: b.supervisor_ids,
            supervisor_id: b.supervisor_ids[0] || null
          }))
        });

        alert('✅ تم إنشاء العقد وفروع التشغيل بنجاح.');
        m.remove();
        loadCapacity(mainContainer);
      } catch (err) {
        alert('❌ تعذر إنشاء العقد: ' + err.message);
      }
    };

  } catch (e) {
    alert('❌ خطأ في فتح نموذج العقد: ' + e.message);
  }
}

async function openRenewContractModal(contract, mainContainer) {
  const content = el('form', { style: 'display:grid;gap:12px' }, [
    el('p', { style: 'color:var(--text);font-size:14px;margin:0' }, `تجديد العقد: <b>${contract.name}</b>`),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'مدة التجديد (بالشهور):'),
      el('select', { id: 'renew-months', style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' }, [
        el('option', { value: '6' }, '6 أشهر'),
        el('option', { value: '12', selected: true }, 'سنة كاملة (12 شهر)'),
        el('option', { value: '24' }, 'سنتان (24 شهر)'),
      ])
    ]),
    el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:10px' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
      el('button', { type: 'submit', class: 'btn btn-primary' }, 'تأكيد التجديد')
    ])
  ]);

  const m = modal('🔄 تجديد العقد التجاري', content);
  content.onsubmit = async (e) => {
    e.preventDefault();
    const months = parseInt(document.getElementById('renew-months').value);
    try {
      await api.post(`/hr/contracts/${contract.id}/renew`, { months });
      alert('✅ تم تجديد العقد بنجاح.');
      m.remove();
      loadCapacity(mainContainer);
    } catch (err) {
      alert('❌ تعذر تجديد العقد: ' + err.message);
    }
  };
}

async function openAddBranchToContractModal(contract, mainContainer) {
  try {
    const [citiesData, supervisorsData] = await Promise.all([
      api.get('/hr/operating-cities').catch(() => []),
      api.get('/hr/supervisors').catch(() => []),
    ]);

    const cities = citiesData.cities || citiesData || [];
    const supervisors = supervisorsData || [];

    const content = el('form', { style: 'display:grid;gap:12px' }, [
      el('p', { style: 'margin:0;font-size:13px' }, [
        el('span', {}, 'إضافة فرع تشغيلي للعقد: '),
        el('b', {}, contract.name)
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'المدينة / المنطقة: *'),
        searchableSelect({
          id: 'branch-city-select',
          placeholder: '🔍 ابحث عن المدينة...',
          options: cities.map(c => ({ value: String(c.id), label: c.name })),
          value: cities[0] ? String(cities[0].id) : '1'
        })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'المشرف المراد إضافته للفرع:'),
        searchableSelect({
          id: 'branch-sup-select',
          placeholder: '🔍 ابحث عن المشرف المسؤول...',
          options: [
            { value: '', label: 'بدون مشرف' },
            ...supervisors.map(s => ({
              value: String(s.id),
              label: s.name,
              sublabel: s.phone ? `📱 ${s.phone}` : ''
            }))
          ]
        })
      ]),
      el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:10px' }, [
        el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
        el('button', { type: 'submit', class: 'btn btn-primary' }, 'حفظ الفرع')
      ])
    ]);

    const m = modal('➕ إضافة فرع أو مشرف لنفس المدينة', content);
    content.onsubmit = async (e) => {
      e.preventDefault();
      const cityId = document.getElementById('branch-city-select').value;
      const supId = document.getElementById('branch-sup-select').value;
      const cityObj = cities.find(c => String(c.id) === cityId);

      const updatedBranches = (contract.branches || []).map(b => ({
        id: b.id,
        city_id: b.city_id,
        city: b.city,
        supervisor_id: b.supervisor_id,
        supervisor_ids: b.supervisor_ids || (b.supervisor_id ? [b.supervisor_id] : [])
      }));

      const existingBranch = updatedBranches.find(b => Number(b.city_id) === Number(cityId));
      if (existingBranch) {
        if (!supId) {
          alert('هذا الفرع موجود بالفعل. اختر المشرف الجديد المراد إضافته.');
          return;
        }
        const supervisorId = Number(supId);
        if (existingBranch.supervisor_ids.includes(supervisorId)) {
          alert('هذا المشرف معيّن بالفعل على الفرع.');
          return;
        }
        existingBranch.supervisor_ids.push(supervisorId);
      } else {
        updatedBranches.push({
          city_id: Number(cityId),
          city: cityObj ? cityObj.name : 'الفرع الجديد',
          supervisor_id: supId ? Number(supId) : null,
          supervisor_ids: supId ? [Number(supId)] : []
        });
      }

      try {
        await api.patch(`/hr/contracts/${contract.id}`, {
          branches: updatedBranches
        });
        alert(existingBranch ? '✅ تم إضافة المشرف إلى نفس الفرع بنجاح.' : '✅ تم إضافة الفرع بنجاح.');
        m.remove();
        loadCapacity(mainContainer);
      } catch (err) {
        alert('❌ تعذر إضافة الفرع: ' + err.message);
      }
    };

  } catch (err) {
    alert('❌ خطأ: ' + err.message);
  }
}

export async function openAddSupervisorModal(mainContainer) {
  const content = el('form', { style: 'display:grid;gap:12px' }, [
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'اسم المشرف: *'),
      el('input', { id: 'sup-name', placeholder: 'مثال: أحمد عبد الله', required: true, style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' })
    ]),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'رقم الجوال: *'),
      el('input', { id: 'sup-phone', placeholder: '966500000000', required: true, style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' })
    ]),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'كلمة المرور:'),
      el('input', { type: 'password', id: 'sup-password', placeholder: 'اتركه فارغاً للافتراضي (123456)', style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' })
    ]),
    el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:10px' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
      el('button', { type: 'submit', class: 'btn btn-primary' }, 'إنشاء المشرف')
    ])
  ]);

  const m = modal('👔 إضافة مشرف ميداني جديد', content);
  content.onsubmit = async (e) => {
    e.preventDefault();
    const name = document.getElementById('sup-name').value;
    const phone = document.getElementById('sup-phone').value;
    const password = document.getElementById('sup-password').value || '123456';
    try {
      await api.post('/hr/supervisors', { name, phone, password });
      alert('✅ تم إنشاء حساب المشرف بنجاح.');
      m.remove();
      loadCapacity(mainContainer);
    } catch (err) {
      alert('❌ تعذر إنشاء المشرف: ' + err.message);
    }
  };
}

export async function openEditContractModal(contract, mainContainer) {
  const content = el('form', { style: 'display:grid;gap:12px;direction:rtl' }, [
    el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'اسم العقد التجاري: *'),
        el('input', { id: 'ect-name', value: contract.name || '', required: true, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'اسم العميل / المنصة:'),
        el('input', { id: 'ect-client', value: contract.client_name || contract.name || '', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
      ]),
    ]),
    el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'سعر توصيل الطلب للعميل (ر.س):'),
        el('input', { type: 'number', step: '0.5', id: 'ect-rate', value: contract.client_rate_per_order || 16.5, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'الحالة:'),
        el('select', { id: 'ect-status', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' }, [
          el('option', { value: 'ACTIVE', selected: contract.status === 'ACTIVE' }, '🟢 ساري ونشط'),
          el('option', { value: 'EXPIRED', selected: contract.status === 'EXPIRED' }, '🔴 منتهي الصلاحية'),
          el('option', { value: 'SUSPENDED', selected: contract.status === 'SUSPENDED' }, '⚪ معلق مؤقتاً')
        ])
      ]),
    ]),
    el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'تاريخ البداية:'),
        el('input', { type: 'date', id: 'ect-start', value: contract.start_date ? contract.start_date.slice(0, 10) : '', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'تاريخ الانتهاء:'),
        el('input', { type: 'date', id: 'ect-end', value: contract.end_date ? contract.end_date.slice(0, 10) : '', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
      ]),
    ]),
    el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:14px;padding-top:12px;border-top:1px solid var(--border)' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
      el('button', { type: 'submit', class: 'btn btn-primary' }, '💾 حفظ التعديل')
    ])
  ]);

  const m = modal(`✏️ تعديل بيانات العقد: ${contract.name}`, content);

  content.onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api.patch(`/hr/contracts/${contract.id}`, {
        name: document.getElementById('ect-name').value.trim(),
        client_name: document.getElementById('ect-client').value.trim(),
        client_rate_per_order: parseFloat(document.getElementById('ect-rate').value || 0),
        status: document.getElementById('ect-status').value,
        start_date: document.getElementById('ect-start').value || undefined,
        end_date: document.getElementById('ect-end').value || undefined,
      });
      alert('✅ تم تعديل بيانات العقد بنجاح.');
      m.remove();
      loadCapacity(mainContainer);
    } catch (err) {
      alert('❌ تعذر التعديل: ' + err.message);
    }
  };
}

export async function openSupervisorsManagementModal(mainContainer) {
  try {
    const supervisors = await api.get('/hr/supervisors').catch(() => []);

    const content = el('div', { style: 'display:grid;gap:14px;min-width:650px;direction:rtl' }, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:center' }, [
        el('div', {}, [
          el('h3', { style: 'margin:0;font-size:15px;color:var(--text)' }, `إدارة المشرفين الميدانيين (${supervisors.length})`),
          el('p', { style: 'margin:4px 0 0 0;font-size:12px;color:var(--muted)' }, 'إنشاء وتعديل وحذف حسابات المشرفين وإسنادهم للفروع')
        ]),
        el('button', {
          class: 'btn btn-primary btn-small',
          onclick: () => openAddSupervisorModal(mainContainer)
        }, '➕ إضافة مشرف جديد')
      ]),
      supervisors.length ? table([
        { key: 'name', label: 'اسم المشرف', render: (v) => el('b', { style: 'color:var(--text)' }, v) },
        { key: 'phone', label: 'رقم الجوال', render: (v) => el('span', { dir: 'ltr' }, v) },
        { key: 'couriers_count', label: 'المناديب المسندين', render: (v) => el('span', { class: 'badge badge-blue' }, `${v || 0} سائق`) },
        { key: 'actions', label: 'إجراءات', render: (_, s) => el('div', { style: 'display:flex;gap:4px' }, [
          el('button', {
            class: 'btn btn-ghost btn-small',
            style: 'color:var(--primary)',
            onclick: () => openEditSupervisorModal(s, () => { m.remove(); openSupervisorsManagementModal(mainContainer); })
          }, '✏️ تعديل'),
          el('button', {
            class: 'btn btn-ghost btn-small',
            style: 'color:var(--red)',
            onclick: async () => {
              if (!confirm(`هل تريد بالتأكيد حذف المشرف (${s.name})؟`)) return;
              try {
                await api.delete(`/hr/supervisors/${s.id}`);
                alert('✅ تم حذف المشرف بنجاح.');
                m.remove();
                openSupervisorsManagementModal(mainContainer);
                loadCapacity(mainContainer);
              } catch (err) {
                alert('❌ تعذر الحذف: ' + err.message);
              }
            }
          }, '🗑️ حذف'),
        ])}
      ], supervisors) : emptyState('لا يوجد مشرفون مسجلون حالياً.')
    ]);

    const m = modal('👔 إدارة المشرفين الميدانيين', content);
  } catch (err) {
    alert('❌ خطأ في تحميل المشرفين: ' + err.message);
  }
}

async function openEditSupervisorModal(supervisor, onUpdated) {
  const content = el('form', { style: 'display:grid;gap:12px;direction:rtl' }, [
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'اسم المشرف: *'),
      el('input', { id: 'esup-name', value: supervisor.name || '', required: true, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
    ]),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'رقم الجوال: *'),
      el('input', { id: 'esup-phone', value: supervisor.phone || '', required: true, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
    ]),
    el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:14px;padding-top:12px;border-top:1px solid var(--border)' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
      el('button', { type: 'submit', class: 'btn btn-primary' }, '💾 حفظ التعديل')
    ])
  ]);

  const m = modal(`✏️ تعديل بيانات المشرف: ${supervisor.name}`, content);

  content.onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api.patch(`/hr/supervisors/${supervisor.id}`, {
        name: document.getElementById('esup-name').value.trim(),
        phone: document.getElementById('esup-phone').value.trim(),
      });
      alert('✅ تم تعديل بيانات المشرف بنجاح.');
      m.remove();
      onUpdated();
    } catch (err) {
      alert('❌ تعذر التعديل: ' + err.message);
    }
  };
}

async function saveRequirement(container) {
  const scopeType = document.getElementById('cap-scope-type')?.value;
  const scopeId = Number(document.getElementById('cap-scope-id')?.value);
  const required = Number(document.getElementById('cap-required')?.value);
  const effectiveFrom = document.getElementById('cap-effective')?.value;
  if (!scopeType || !scopeId || !effectiveFrom || required < 0 || document.getElementById('cap-required').value === '') {
    modal('تنبيه', el('div', {}, [
      el('p', { style: 'color:var(--amber)' }, '⚠️ يرجى اختيار نوع ورقم النطاق وتاريخ السريان والعدد المطلوب.'),
      el('button', { class: 'btn btn-ghost', onclick: () => document.querySelector('.modal-overlay')?.remove() }, 'حسناً')
    ]));
    return;
  }
  try {
    await api.post('/analytics/capacity/requirements', { scope_type: scopeType, scope_id: scopeId, shift_id: null, required_riders: required, effective_from: effectiveFrom, effective_to: null });
    loadCapacity(container);
  } catch (e) {
    modal('خطأ', el('div', {}, [el('p', { style: 'color:var(--red)' }, 'تعذر حفظ الاحتياج: ' + e.message)]));
  }
}

async function renderPlatformSettlements(contentArea, container, isAdmin) {
  contentArea.append(loadingState('جاري تحميل تسويات المشغلين...'));
  try {
    const settlements = await api.get('/analytics/operators/settlements').catch(() => []);
    contentArea.innerHTML = '';
    contentArea.append(el('div', { class: 'card', style: 'margin-top:10px' }, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px' }, [
        el('h3', { text: '💼 تسويات المشغلين المالية (B2B Commercial Settlements)' }),
        el('span', { class: 'badge badge-blue', text: `${settlements?.length || 0} تسوية` })
      ]),
      settlements && settlements.length ? table([
        { key: 'period_month', label: 'الشهر' },
        { key: 'operator_name', label: 'المشغل', render: (v, r) => v || `مشغل #${r.operator_id}` },
        { key: 'eligible_orders', label: 'الطلبات المعتمدة' },
        { key: 'base_amount', label: 'المبلغ الأساسي', render: (v) => `${Number(v).toLocaleString()} ر.س` },
        { key: 'net_amount', label: 'صافي التسوية', render: (v) => el('b', { text: `${Number(v).toLocaleString()} ر.س` }) },
        { key: 'status', label: 'الحالة', render: (v) => badge(v, v === 'APPROVED' ? 'green' : v === 'NEEDS_REVIEW' ? 'amber' : 'gray') },
        { key: 'actions', label: 'إجراء', render: (_, r) => {
          if (r.status !== 'APPROVED' && isAdmin) {
            return el('button', { class: 'btn btn-green btn-small', onclick: () => approveSettlement(r.id, container) }, 'اعتماد التسوية');
          }
          return r.status === 'APPROVED' ? '✅ معتمدة' : '—';
        }},
      ], settlements) : emptyState('لا توجد تسويات مشغلين محسوبة حتى الآن.')
    ]));
  } catch (e) {
    contentArea.innerHTML = '';
    contentArea.append(errorState('تعذر التحميل: ' + e.message));
  }
}

async function approveSettlement(id, container) {
  try {
    await api.post(`/analytics/operators/settlement/${id}/approve`);
    loadCapacity(container);
  } catch (e) {
    modal('خطأ في الاعتماد', el('div', {}, [
      el('p', { style: 'color:var(--red)' }, 'تعذر اعتماد التسوية: ' + e.message),
      el('button', { class: 'btn btn-ghost', onclick: () => document.querySelector('.modal-overlay')?.remove() }, 'إغلاق')
    ]));
  }
}

async function openCalculateSettlementModal(container) {
  try {
    const operators = await api.get('/enterprise/operators');
    if (!operators || !operators.length) {
      modal('حساب تسوية مشغل', el('div', {}, [
        el('p', { style: 'color:var(--amber)' }, '⚠️ لا يوجد مشغلون مسجلون في المنصة.'),
        el('button', { class: 'btn btn-ghost', onclick: () => document.querySelector('.modal-overlay')?.remove() }, 'إغلاق')
      ]));
      return;
    }
    const opSelect = selectField('cs-op', 'اختر المشغل', operators.map(o => ({
      value: o.operator_tenant_id,
      label: o.name || o.operator_name || `مشغل #${o.operator_tenant_id}`
    })));
    const content = el('form', {}, [
      formRow([opSelect]),
      formRow([inputField('cs-month', 'فترة الشهر (YYYY-MM)', { value: new Date().toISOString().slice(0, 7), required: true })]),
      formRow([inputField('cs-adj', 'تسوية يدوية (ريال - اختياري)', { type: 'number', value: '0' })]),
      formRow([inputField('cs-reason', 'سبب التعديل اليدوي', { placeholder: 'مثال: مكافأة حملة خاصة' })]),
      el('div', { id: 'cs-preview', style: 'margin:12px 0' }),
      el('div', { style: 'display:flex;gap:8px' }, [
        el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => calculatePreview() }, 'معاينة الحساب'),
        el('button', { type: 'submit', class: 'btn btn-blue' }, 'حفظ التسوية'),
      ]),
      el('span', { id: 'cs-msg', class: 'msg' })
    ]);
    const m = modal('حساب واعتماد تسوية B2B لمشغل', content);

    async function calculatePreview() {
      const opId = Number(document.getElementById('cs-op')?.value);
      const periodMonth = document.getElementById('cs-month')?.value;
      const previewDiv = document.getElementById('cs-preview');
      previewDiv.innerHTML = 'جاري الحساب...';
      try {
        const calc = await api.post(`/analytics/operators/settlement/calculate?operator_id=${opId}&period_month=${periodMonth}`);
        previewDiv.innerHTML = `
          <div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px">
            <div>الطلبات المؤهلة: <b>${calc.eligible_orders}</b></div>
            <div>المبلغ الأساسي: <b>${calc.base_amount} ${calc.currency}</b></div>
            <div>المكافأة: <b style="color:var(--green)">+${calc.bonus_amount} ${calc.currency}</b></div>
            <div>الخصومات/الغرامات: <b style="color:var(--red)">-${calc.penalty_amount} ${calc.currency}</b></div>
            <div style="margin-top:6px;font-size:15px">صافي التسوية: <b>${calc.net_amount} ${calc.currency}</b></div>
          </div>
        `;
      } catch (err) {
        previewDiv.innerHTML = `<span style="color:var(--red)">❌ ${err.message}</span>`;
      }
    }

    content.addEventListener('submit', async (e) => {
      e.preventDefault();
      const msg = document.getElementById('cs-msg');
      const opId = Number(document.getElementById('cs-op')?.value);
      const periodMonth = document.getElementById('cs-month')?.value;
      const adj = Number(document.getElementById('cs-adj')?.value) || 0;
      const reason = document.getElementById('cs-reason')?.value || null;
      try {
        await api.post(`/analytics/operators/settlement/save?operator_id=${opId}&period_month=${periodMonth}&adjustment=${adj}${reason ? '&adjustment_reason=' + encodeURIComponent(reason) : ''}`);
        msg.style.color = 'var(--green)';
        msg.textContent = '✅ تم حفظ التسوية بنجاح.';
        setTimeout(() => { m.remove(); loadCapacityData(container); }, 800);
      } catch (err) {
        msg.style.color = 'var(--red)';
        msg.textContent = '❌ ' + err.message;
      }
    });
  } catch (e) {
    modal('خطأ', el('div', {}, [el('p', { style: 'color:var(--red)' }, 'تعذر فتح نافذة الحساب: ' + e.message)]));
  }
}
