// Super Admin — Platform Operations & SaaS Management
import { api } from '../../shared/api/client.js';
import { appStore } from '../../shared/state/store.js';
import { el, loadingState, emptyState, errorState, metricCard, table, badge, modal, confirmModal, money, showToast } from '../../shared/components/ui.js';
import { openTenantManagementModal } from './tenants.js';

// ============================================================
// 1. REVENUE & BILLING (التحصيل والإيرادات)
// ============================================================

export async function loadRevenue(container) {
  container.innerHTML = '';
  const now = new Date();
  const currentMonthStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  let selectedMonth = currentMonthStr;

  const header = el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, 'المالية والاشتراكات'),
      el('h1', { text: 'التحصيل والإيرادات' }),
      el('p', { style: 'color:var(--muted);font-size:12px;margin:2px 0 0' }, 'متابعة الاشتراكات الشهرية، نسب التحصيل الفعلي، وتسجيل الدفعات وإصدار الإيصالات'),
    ]),
    el('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, [
      el('input', {
        type: 'month',
        value: selectedMonth,
        class: 'input',
        style: 'padding:6px 10px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:12px',
        onchange: (e) => {
          selectedMonth = e.target.value || currentMonthStr;
          fetchAndRender();
        },
      }),
      el('button', { class: 'btn btn-ghost btn-small', id: 'btnExportRevenue' }, '📥 تصدير CSV'),
      el('button', { class: 'btn btn-ghost btn-small', onclick: () => fetchAndRender() }, '↻ تحديث'),
    ]),
  ]);
  container.append(header);

  const body = el('div', {}, [loadingState('جاري تحميل بيانات التحصيل والإيرادات...')]);
  container.append(body);

  async function fetchAndRender() {
    body.innerHTML = '';
    body.append(loadingState('جاري التحميل...'));
    try {
      const country = appStore.get().selectedCountry;
      let url = `/admin/finance/summary?month=${encodeURIComponent(selectedMonth)}`;
      if (country) url += `&country=${encodeURIComponent(country)}`;
      const data = await api.get(url);

      body.innerHTML = '';

      // Export CSV button handler
      const exportBtn = header.querySelector('#btnExportRevenue');
      if (exportBtn) {
        exportBtn.onclick = () => exportRevenueCsv(data, selectedMonth);
      }

      // Summary KPI Cards (Defensive: totals_by_currency, fallback to actual/expected/outstanding)
      const totals = data.totals_by_currency || {};
      let currencies = Object.keys(totals);
      if (!currencies.length && (data.expected_revenue || data.actual_revenue || data.outstanding)) {
        const setC = new Set([
          ...Object.keys(data.expected_revenue || {}),
          ...Object.keys(data.actual_revenue || {}),
          ...Object.keys(data.outstanding || {}),
        ]);
        currencies = Array.from(setC);
        currencies.forEach((c) => {
          totals[c] = {
            collected: data.actual_revenue?.[c] || 0,
            expected: data.expected_revenue?.[c] || 0,
            overdue: data.outstanding?.[c] || 0,
          };
        });
      }
      if (!currencies.length) currencies = ['SAR'];

      let collectedStr = currencies.map((c) => money(totals[c]?.collected || 0, c)).join(' | ');
      let expectedStr = currencies.map((c) => money(totals[c]?.expected || 0, c)).join(' | ');
      let overdueStr = currencies.map((c) => money(totals[c]?.overdue || 0, c)).join(' | ');

      const cards = el('div', { class: 'cards', style: 'margin-bottom:16px' }, [
        metricCard(collectedStr, 'إجمالي الإيراد الفعلي المحصل', 'green'),
        metricCard(expectedStr, 'إجمالي الإيراد المتوقع للشهر', 'blue'),
        metricCard(overdueStr, 'المتأخرات غير المحصلة', 'red'),
      ]);
      body.append(cards);

      // Requirement 4: Unconfigured Company Billing Alert Banner
      const rows = data.rows || [];
      const unconfRows = rows.filter((r) => r.collection_status === 'UNCONFIGURED');
      if (unconfRows.length > 0 || (data.unconfigured_companies || 0) > 0) {
        const unconfCount = unconfRows.length || data.unconfigured_companies;
        const banner = el('div', {
          class: 'card',
          style: 'padding:14px 18px;margin-bottom:18px;background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.3);border-radius:10px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;direction:rtl'
        }, [
          el('div', { style: 'display:flex;align-items:center;gap:12px' }, [
            el('span', { style: 'font-size:24px' }, '🚨'),
            el('div', {}, [
              el('b', { style: 'color:var(--red);font-size:13.5px;display:block;margin-bottom:2px' }, `تنبيه التحصيل: توجد ${unconfCount} شركة بدون تاريخ استحقاق محدد (غير مهيأة للفوترة)`),
              el('span', { style: 'color:var(--ink2);font-size:12px' }, `الشركات: ${unconfRows.map((r) => r.company).slice(0, 3).join('، ')}${unconfRows.length > 3 ? ' وغيرها...' : ''}. هذه الشركات لا تظهر في عدادات المتأخرات حتى يتم ضبط يوم الفوترة.`),
            ])
          ]),
          el('div', { style: 'display:flex;gap:8px' }, [
            unconfRows[0] ? el('button', {
              class: 'btn btn-primary btn-small',
              style: 'font-size:11.5px',
              onclick: () => openTenantManagementModal(unconfRows[0].tenant_id, 'edit', () => fetchAndRender())
            }, `⚙️ ضبط دورة فوترة «${unconfRows[0].company}»`) : null,
          ])
        ]);
        body.append(banner);
      }

      // Subscriptions Breakdown Table
      const sectionHead = el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin:18px 0 8px;direction:rtl' }, [
        el('h3', { style: 'margin:0;font-size:14px', text: `سجل اشتراكات الشركات لشهر ${selectedMonth} (${rows.length})` }),
      ]);
      body.append(sectionHead);

      if (!rows.length) {
        body.append(emptyState('لا توجد اشتراكات مسجلة لهذا الشهر.'));
      } else {
        const rowsTable = table([
          { key: 'company', label: 'الشركة', render: (v) => el('b', { text: v || '—' }) },
          { key: 'plan', label: 'الباقة', render: (v) => badge(v || '—', 'blue') },
          { key: 'monthly_fee', label: 'الرسوم الشهرية', render: (v, row) => el('b', { text: money(v, row.currency) }) },
          { key: 'paid_this_month', label: 'دفع هذا الشهر؟', render: (v) => badge(v ? 'نعم (مدفوع)' : 'لا (غير مدفوع)', v ? 'green' : 'amber') },
          { key: 'paid_amount', label: 'المبلغ المحصل', render: (v, row) => el('b', { style: 'color:var(--green)', text: money(v, row.currency) }) },
          { key: 'outstanding_amount', label: 'المتأخرات', render: (v, row) => v > 0 ? el('b', { style: 'color:var(--red)', text: money(v, row.currency) }) : '0' },
          { key: 'due_date', label: 'تاريخ الاستحقاق', render: (v) => v ? new Date(v).toISOString().slice(0, 10) : el('span', { style: 'color:var(--red);font-weight:700' }, '⚠️ غير محدد') },
          { key: 'collection_status', label: 'حالة التحصيل', render: (v) => {
            const map = {
              PAID_THIS_MONTH: { text: 'مدفوع هذا الشهر', color: 'green' },
              COVERED: { text: 'مغطى مسبقاً', color: 'blue' },
              OVERDUE: { text: 'متأخر عن السداد', color: 'red' },
              UNCONFIGURED: { text: 'غير مهيأ', color: 'red' },
            };
            const c = map[v] || { text: v || '—', color: 'gray' };
            return badge(c.text, c.color);
          } },
          { key: 'actions', label: 'إجراء فوري', render: (_, row) => el('button', {
            class: 'btn btn-primary btn-small',
            style: 'padding:4px 8px;font-size:11px',
            onclick: () => openTenantManagementModal(row.tenant_id, 'payment', () => fetchAndRender()),
          }, '💵 تسجيل دفعة') },
        ], rows);
        body.append(rowsTable);
      }

      // Requirement 7: 6-Month Historical Revenue Trend
      const history = data.history || [];
      if (history.length) {
        const trendHead = el('div', { style: 'margin:28px 0 10px;direction:rtl' }, [
          el('h3', { style: 'margin:0;font-size:14px;color:var(--text)' }, '📈 الأفق الزمني للإيرادات (مسار التحصيل للشهور الـ 6 الأخيرة)'),
          el('p', { style: 'margin:2px 0 0;font-size:11.5px;color:var(--muted)' }, 'مقارنة الإيراد المحصل فعلياً مقابل الإيراد المتوقع شهرياً لمتابعة مسار النمو المالي'),
        ]);
        body.append(trendHead);

        const historyCards = el('div', {
          style: 'display:grid;grid-template-columns:repeat(auto-fit, minmax(170px, 1fr));gap:12px;margin-bottom:20px;direction:rtl'
        }, history.map((h) => {
          const isSelected = h.month === selectedMonth;
          const col = Number(h.collected || 0);
          const exp = Number(h.expected || 0);
          const pct = exp > 0 ? Math.min(100, Math.round((col / exp) * 100)) : 0;
          return el('div', {
            class: 'card',
            style: `padding:12px;border-radius:10px;background:var(--card);border:${isSelected ? '2px solid var(--primary)' : '1px solid var(--border)'}`
          }, [
            el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:6px' }, [
              el('b', { style: `font-size:13px;font-family:monospace;color:${isSelected ? 'var(--primary)' : 'var(--text)'}` }, h.month),
              badge(`${pct}% محصل`, pct >= 90 ? 'green' : pct >= 50 ? 'blue' : 'amber'),
            ]),
            el('div', { style: 'font-size:12px;color:var(--ink2);margin-bottom:2px' }, [
              el('span', { style: 'color:var(--muted)' }, 'المحصل: '),
              el('b', { style: 'color:var(--green)' }, money(col, 'SAR', 0)),
            ]),
            el('div', { style: 'font-size:12px;color:var(--ink2);margin-bottom:8px' }, [
              el('span', { style: 'color:var(--muted)' }, 'المتوقع: '),
              el('b', {}, money(exp, 'SAR', 0)),
            ]),
            el('div', { style: 'height:6px;background:var(--soft);border-radius:3px;overflow:hidden' }, [
              el('div', { style: `height:100%;width:${pct}%;background:${pct >= 90 ? 'var(--green)' : 'var(--primary)'}` })
            ])
          ]);
        }));
        body.append(historyCards);
      }

      // Recent payments
      const recent = data.recent_payments || [];
      if (recent.length) {
        body.append(el('h3', { style: 'margin:24px 0 8px;font-size:14px;direction:rtl', text: `آخر الإيصالات المسجلة مؤخراً (${recent.length})` }));
        const recentTable = table([
          { key: 'receipt_number', label: 'رقم الإيصال', render: (v) => el('b', { style: 'font-family:monospace;color:var(--primary)', text: v || '—' }) },
          { key: 'company', label: 'الشركة', render: (v) => v || '—' },
          { key: 'amount', label: 'المبلغ', render: (v, row) => el('b', { text: money(v, row.currency) }) },
          { key: 'paid_at', label: 'التاريخ', render: (v) => v ? new Date(v).toISOString().slice(0, 10) : '—' },
          { key: 'payment_method', label: 'الطريقة', render: (v) => ({ CASH: 'كاش', BANK_TRANSFER: 'تحويل بنكي', CARD: 'بطاقة', OTHER: 'أخرى' }[v] || v || '—') },
        ], recent);
        body.append(recentTable);
      }
    } catch (e) {
      body.innerHTML = '';
      body.append(errorState('تعذر تحميل بيانات الإيرادات: ' + e.message, () => fetchAndRender()));
    }
  }

  fetchAndRender();
}

function exportRevenueCsv(data, monthStr) {
  const rows = data.rows || [];
  if (!rows.length) {
    showToast('لا توجد بيانات للتصدير', 'warn');
    return;
  }
  const headers = ['الشركة', 'الباقة', 'العملة', 'الرسوم الشهرية', 'مدفوع للشهر', 'المبلغ المحصل', 'المتأخرات', 'تاريخ الاستحقاق', 'حالة التحصيل'];
  const csvRows = rows.map((r) => [
    r.company || '',
    r.plan || '',
    r.currency || '',
    r.monthly_fee ?? 0,
    r.paid_this_month ? 'نعم' : 'لا',
    r.paid_amount ?? 0,
    r.outstanding_amount ?? 0,
    r.due_date ? r.due_date.slice(0, 10) : '',
    r.collection_status || '',
  ]);
  const csv = '\ufeff' + [headers, ...csvRows].map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `DOU-revenue-${monthStr}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ============================================================
// 2. PLANS & PRICING (الباقات والأسعار)
// ============================================================

export async function loadPlans(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, 'إدارة المنصة'),
      el('h1', { text: 'الباقات والأسعار' }),
      el('p', { style: 'color:var(--muted);font-size:12px;margin:2px 0 0' }, 'إدارة خطط اشتراك الشركات اللوجستية، تحديد أسعار الاشتراك الشهري وحدود المناديب والمميزات'),
    ]),
    el('div', { style: 'display:flex;gap:8px;align-items:center' }, [
      el('button', { class: 'btn btn-primary btn-small', onclick: () => openPlanModal(null, () => loadPlans(container)) }, '➕ إضافة باقة جديدة'),
      el('button', { class: 'btn btn-ghost btn-small', onclick: () => loadPlans(container) }, '↻ تحديث'),
    ]),
  ]));

  const body = el('div', {}, [loadingState('جاري تحميل الباقات...')]);
  container.append(body);

  try {
    const plans = await api.get('/admin/plans');
    body.innerHTML = '';

    if (!plans || !plans.length) {
      body.append(emptyState('لا توجد باقات معرفة حالياً.'));
      return;
    }

    const cardsGrid = el('div', { style: 'display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;direction:rtl' });

    plans.forEach((p) => {
      const card = el('div', { class: 'card', style: 'padding:16px;display:flex;flex-direction:column;gap:10px;position:relative' }, [
        el('div', { style: 'display:flex;justify-content:space-between;align-items:flex-start' }, [
          el('div', {}, [
            el('h3', { style: 'margin:0;font-size:16px', text: p.name }),
            p.name_en ? el('small', { style: 'color:var(--muted);font-size:11px', text: p.name_en }) : null,
          ]),
          badge(p.is_active ? 'نشطة' : 'موقوفة', p.is_active ? 'green' : 'red'),
        ]),
        el('div', { style: 'display:flex;align-items:baseline;gap:6px;margin:6px 0' }, [
          el('b', { style: 'font-size:22px;color:var(--primary)', text: `${p.monthly_price} ر.س` }),
          el('span', { style: 'font-size:12px;color:var(--muted)', text: `/ شهرياً ($${p.monthly_price_usd || 0})` }),
        ]),
        el('div', { class: 'card', style: 'background:var(--soft);padding:8px 10px;font-size:12px;display:flex;justify-content:space-between' }, [
          el('span', { style: 'color:var(--muted)' }, 'الحد الأقصى للمناديب:'),
          el('b', { text: p.max_couriers > 0 ? `${p.max_couriers} مندوب` : 'غير محدود' }),
        ]),
        p.features_ar ? el('div', { style: 'font-size:11.5px;color:var(--text);white-space:pre-line;line-height:1.5;background:var(--card);padding:8px;border-radius:6px;border:1px solid var(--border)' }, p.features_ar) : null,
        el('div', { style: 'margin-top:auto;display:flex;justify-content:flex-end;padding-top:8px' }, [
          el('button', {
            class: 'btn btn-ghost btn-small',
            onclick: () => openPlanModal(p, () => loadPlans(container)),
          }, '✏️ تعديل الباقة والحدود'),
        ]),
      ]);
      cardsGrid.append(card);
    });

    body.append(cardsGrid);
  } catch (e) {
    body.innerHTML = '';
    body.append(errorState('تعذر تحميل الباقات: ' + e.message, () => loadPlans(container)));
  }
}

function openPlanModal(plan = null, onSaved = null) {
  const isEdit = !!plan;
  const overlay = modal(isEdit ? `✏️ تعديل باقة ${plan.name}` : '➕ إضافة باقة جديدة', el('div', {}, []));
  const modalBody = overlay.querySelector('.modal-body');

  const form = el('form', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:12px;direction:rtl' });

  const codeInput = el('input', {
    type: 'text',
    placeholder: 'رمز الباقة بالإنجليزية (مثل: SCALE)',
    value: plan?.code || '',
    style: inputFieldStyle(),
    required: true,
    ...(isEdit ? { disabled: 'disabled' } : {}),
  });

  const nameInput = el('input', {
    type: 'text',
    placeholder: 'اسم الباقة بالعربية (مثل: باقة التوسع)',
    value: plan?.name || '',
    style: inputFieldStyle(),
    required: true,
  });

  const nameEnInput = el('input', {
    type: 'text',
    placeholder: 'اسم الباقة بالإنجليزية (مثل: Scale Plan)',
    value: plan?.name_en || '',
    style: inputFieldStyle(),
  });

  const priceInput = el('input', {
    type: 'number',
    placeholder: 'السعر الشهري (ر.س)',
    value: plan?.monthly_price ?? 999,
    style: inputFieldStyle(),
    required: true,
  });

  const priceUsdInput = el('input', {
    type: 'number',
    placeholder: 'السعر بالدولار ($)',
    value: plan?.monthly_price_usd ?? 269,
    style: inputFieldStyle(),
  });

  const maxCouriersInput = el('input', {
    type: 'number',
    placeholder: 'حد المناديب (0 = غير محدود)',
    value: plan?.max_couriers ?? 50,
    style: inputFieldStyle(),
    required: true,
  });

  const activeSelect = el('select', { style: inputFieldStyle() }, [
    el('option', { value: 'true', ...(plan?.is_active !== false ? { selected: 'selected' } : {}) }, 'نشطة ومتاحة للاشتراك'),
    el('option', { value: 'false', ...(plan?.is_active === false ? { selected: 'selected' } : {}) }, 'موقوفة مؤقتاً'),
  ]);

  const featuresArArea = el('textarea', {
    rows: '4',
    placeholder: 'مميزات الباقة بالعربية (كل ميزة في سطر)...',
    value: plan?.features_ar || '',
    style: `${inputFieldStyle()};grid-column:span 2;resize:vertical`,
  });

  const submitBtn = el('button', {
    type: 'submit',
    class: 'btn btn-primary',
    style: 'grid-column:span 2;padding:10px;font-weight:700;margin-top:6px',
  }, isEdit ? 'حفظ تعديلات الباقة' : 'إنشاء الباقة');

  form.append(
    wrapFieldGroup('رمز الباقة (Code):', codeInput),
    wrapFieldGroup('اسم الباقة (عربي):', nameInput),
    wrapFieldGroup('اسم الباقة (إنجليزي):', nameEnInput),
    wrapFieldGroup('حالة الباقة:', activeSelect),
    wrapFieldGroup('السعر الشهري (SAR):', priceInput),
    wrapFieldGroup('السعر الشهري ($ USD):', priceUsdInput),
    wrapFieldGroup('الحد الأقصى للمناديب:', maxCouriersInput),
    wrapFieldGroup('قائمة المميزات بالعربية:', featuresArArea),
    submitBtn
  );

  form.onsubmit = async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    submitBtn.textContent = 'جاري الحفظ…';
    try {
      await api.post('/admin/plans', {
        code: codeInput.value.trim().toUpperCase(),
        name: nameInput.value.trim(),
        name_en: nameEnInput.value.trim(),
        monthly_price: parseFloat(priceInput.value) || 0,
        monthly_price_usd: parseFloat(priceUsdInput.value) || 0,
        max_couriers: parseInt(maxCouriersInput.value, 10) || 0,
        features_ar: featuresArArea.value.trim(),
        is_active: activeSelect.value === 'true',
      });
      showToast('✅ تم حفظ الباقة بنجاح وتحديث خطط الاشتراك', 'success');
      overlay.close();
      if (onSaved) onSaved();
    } catch (err) {
      showToast('❌ فشل حفظ الباقة: ' + err.message, 'error');
      submitBtn.disabled = false;
      submitBtn.textContent = isEdit ? 'حفظ تعديلات الباقة' : 'إنشاء الباقة';
    }
  };

  modalBody.append(form);
}

// ============================================================
// 3. INTEGRATIONS & CHANNELS (التكاملات وقنوات التوصيل)
// ============================================================

export async function loadIntegrations(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, 'إدارة الربط والتكاملات'),
      el('h1', { text: 'التكاملات وقنوات التوصيل' }),
      el('p', { style: 'color:var(--muted);font-size:12px;margin:2px 0 0' }, 'إدارة منصات التوصيل وتطبيقات الطلبات المعتمدة (جاهز، هنقرستيشن، تويو) والويبهوكات التشغيلية'),
    ]),
    el('div', { style: 'display:flex;gap:8px;align-items:center' }, [
      el('button', { class: 'btn btn-primary btn-small', onclick: () => openChannelModal(null, () => loadIntegrations(container)) }, '➕ إضافة قناة توصيل جديدة'),
      el('button', { class: 'btn btn-ghost btn-small', onclick: () => loadIntegrations(container) }, '↻ تحديث'),
    ]),
  ]));

  const body = el('div', {}, [loadingState('جاري تحميل التكاملات والقنوات...')]);
  container.append(body);

  try {
    const [channels, webhooks] = await Promise.all([
      api.get('/admin/channels'),
      api.get('/admin/integrations'),
    ]);

    body.innerHTML = '';

    // Section 1: Channels & Platforms
    body.append(el('h3', { style: 'margin:0 0 10px;font-size:15px;direction:rtl', text: `منصات وتطبيقات التوصيل المعتمدة (${channels.length})` }));

    if (!channels.length) {
      body.append(emptyState('لا توجد قنوات مسجلة بعد.'));
    } else {
      const channelGrid = el('div', { style: 'display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;margin-bottom:24px;direction:rtl' });
      channels.forEach((c) => {
        const item = el('div', { class: 'card', style: 'padding:14px;display:flex;flex-direction:column;gap:8px' }, [
          el('div', { style: 'display:flex;justify-content:space-between;align-items:center' }, [
            el('div', { style: 'display:flex;align-items:center;gap:8px' }, [
              el('span', { style: 'font-size:20px', text: c.icon || '📦' }),
              el('b', { style: 'font-size:14px', text: c.name }),
            ]),
            badge(c.is_active ? 'نشط' : 'معطّل', c.is_active ? 'green' : 'red'),
          ]),
          el('div', { style: 'display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-top:4px' }, [
            el('span', {}, 'نسبة عمولة المنصة:'),
            el('b', { style: 'color:var(--text)', text: `${c.commission || 0}%` }),
          ]),
          el('div', { style: 'display:flex;justify-content:space-between;font-size:12px;color:var(--muted)' }, [
            el('span', {}, 'حصة الطلبات:'),
            el('span', { text: `${c.orders_share || 0}%` }),
          ]),
          el('div', { style: 'display:flex;justify-content:flex-end;gap:6px;margin-top:6px' }, [
            el('button', {
              class: 'btn btn-ghost btn-small',
              onclick: () => editChannelCommission(c, () => loadIntegrations(container)),
            }, '✏️ تعديل العمولة'),
          ]),
        ]);
        channelGrid.append(item);
      });
      body.append(channelGrid);
    }

    // Section 2: Active Webhooks & Integrations
    body.append(el('h3', { style: 'margin:20px 0 10px;font-size:15px;direction:rtl', text: `سجل الويبهوكات وتكاملات الشركات (${webhooks.length})` }));
    if (!webhooks.length) {
      body.append(emptyState('لا توجد ويبهوكات أو تكاملات نشطة مسجلة حالياً.'));
    } else {
      const webhookTable = table([
        { key: 'tenant_name', label: 'الشركة المستفيدة', render: (v) => el('b', { text: v || '—' }) },
        { key: 'event_type', label: 'نوع الحدث', render: (v) => badge(v, 'blue') },
        { key: 'url', label: 'رابط الاستقبال (Endpoint)', render: (v) => el('span', { style: 'direction:ltr;font-family:monospace;font-size:11px', text: v || '—' }) },
        { key: 'is_inbound', label: 'الاتجاه', render: (v) => badge(v ? 'وارد' : 'صادر', v ? 'green' : 'amber') },
        { key: 'is_active', label: 'الحالة', render: (v) => badge(v ? 'نشط' : 'معطّل', v ? 'green' : 'red') },
      ], webhooks);
      body.append(webhookTable);
    }
  } catch (e) {
    body.innerHTML = '';
    body.append(errorState('تعذر تحميل التكاملات: ' + e.message, () => loadIntegrations(container)));
  }
}

async function editChannelCommission(channel, onUpdated) {
  const current = channel.commission ?? 0;
  const nextVal = prompt(`أدخل نسبة عمولة منصة "${channel.name}" الجديدة (%):`, current);
  if (nextVal === null) return;
  const num = parseFloat(nextVal);
  if (isNaN(num) || num < 0 || num > 100) {
    showToast('النسبة يجب أن تكون رقماً بين 0 و 100', 'warn');
    return;
  }
  try {
    await api.patch(`/admin/channels/${channel.id}`, { commission: num });
    showToast('✅ تم تحديث نسبة العمولة بنجاح', 'success');
    if (onUpdated) onUpdated();
  } catch (err) {
    showToast('❌ فشل تعديل العمولة: ' + err.message, 'error');
  }
}

function openChannelModal(channel = null, onSaved = null) {
  const overlay = modal('➕ إضافة منصة توصيل جديدة', el('div', {}, []));
  const modalBody = overlay.querySelector('.modal-body');

  const form = el('form', { style: 'display:grid;gap:10px;font-size:12px;direction:rtl' });

  const nameInput = el('input', { type: 'text', placeholder: 'اسم المنصة (مثال: جاهز، هنقرستيشن)', style: inputFieldStyle(), required: true });
  const iconInput = el('input', { type: 'text', placeholder: 'الأيقونة (مثال: 🍔 أو 🛵)', value: '🛵', style: inputFieldStyle() });
  const typeInput = el('input', { type: 'text', placeholder: 'نوع القناة (مثال: aggregator أو custom)', value: 'aggregator', style: inputFieldStyle() });
  const commissionInput = el('input', { type: 'number', placeholder: 'نسبة العمولة الافتراضية (%)', value: '12', style: inputFieldStyle() });

  const submitBtn = el('button', { type: 'submit', class: 'btn btn-primary', style: 'padding:10px;font-weight:700;margin-top:6px' }, 'إضافة المنصة');

  form.append(
    wrapFieldGroup('اسم منصة التوصيل:', nameInput),
    wrapFieldGroup('الأيقونة التعبيرية:', iconInput),
    wrapFieldGroup('النوع / التصنيف:', typeInput),
    wrapFieldGroup('نسبة العمولة (%):', commissionInput),
    submitBtn
  );

  form.onsubmit = async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    try {
      await api.post('/admin/channels', {
        name: nameInput.value.trim(),
        icon: iconInput.value.trim(),
        type: typeInput.value.trim(),
        commission: parseFloat(commissionInput.value) || 0,
      });
      showToast('✅ تم تسجيل قناة التوصيل بنجاح', 'success');
      overlay.close();
      if (onSaved) onSaved();
    } catch (err) {
      showToast('❌ فشل إضافة القناة: ' + err.message, 'error');
      submitBtn.disabled = false;
    }
  };

  modalBody.append(form);
}

// ============================================================
// 4. USAGE & LIMITS (الاستخدام والحدود)
// ============================================================

export async function loadUsage(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, 'الاستهلاك والتراخيص'),
      el('h1', { text: 'الاستخدام والحدود' }),
      el('p', { style: 'color:var(--muted);font-size:12px;margin:2px 0 0' }, 'متابعة استهلاك الشركات اللوجستية لحدود المناديب وتجاوزات الحصص المعتمدة'),
    ]),
    el('button', { class: 'btn btn-ghost btn-small', onclick: () => loadUsage(container) }, '↻ تحديث'),
  ]));

  const body = el('div', {}, [loadingState('جاري تحميل إحصاءات الاستخدام...')]);
  container.append(body);

  try {
    const usage = await api.get('/admin/usage/summary');
    body.innerHTML = '';

    // KPIs
    const kpis = el('div', { class: 'cards', style: 'margin-bottom:16px' }, [
      metricCard(usage.active_tenants, 'الشركات النشطة', 'green', null, `من أصل ${usage.total_tenants || 0} شركة`),
      metricCard(usage.total_couriers, 'إجمالي المناديب المشغلين', 'blue'),
      metricCard(usage.total_users, 'مستخدمو الإدارة والعمليات', 'gray'),
      metricCard(usage.suspended_tenants, 'الشركات الموقوفة', usage.suspended_tenants > 0 ? 'alert' : 'gray'),
      metricCard(usage.overdue_tenants, 'الشركات المتأخرة بالسداد', usage.overdue_tenants > 0 ? 'alert' : 'gray'),
    ]);
    body.append(kpis);

    // Near Limit Alerts
    const nearLimit = usage.tenants_near_limit || [];
    body.append(el('h3', { style: 'margin:20px 0 10px;font-size:15px;direction:rtl', text: `⚠️ شركات تقترب من الحد الأقصى للمناديب (${nearLimit.length})` }));

    if (!nearLimit.length) {
      body.append(el('div', { class: 'state-success', style: 'padding:16px;background:var(--card);border-radius:10px;border:1px solid var(--border);direction:rtl' }, [
        el('b', { style: 'color:var(--green)' }, '✅ ممتاز! جميع الشركات اللوجستية تعمل ضمن السعات والحدود المعتمدة لباقاتها.'),
      ]));
    } else {
      const limitTable = table([
        { key: 'name', label: 'الشركة', render: (v) => el('b', { text: v || '—' }) },
        { key: 'count', label: 'المناديب الحاليين', render: (v, row) => `${v} / ${row.max}` },
        { key: 'usage_pct', label: 'نسبة الاستهلاك', render: (v) => {
          const isCritical = v >= 90;
          return el('div', { style: 'display:flex;align-items:center;gap:8px;min-width:140px' }, [
            el('div', { style: 'flex:1;height:8px;background:var(--soft);border-radius:4px;overflow:hidden' }, [
              el('div', { style: `height:100%;width:${Math.min(100, v)}%;background:${isCritical ? 'var(--red)' : 'var(--amber)'}` }),
            ]),
            el('b', { style: `font-size:11px;color:${isCritical ? 'var(--red)' : 'var(--amber)'}`, text: `${v}%` }),
          ]);
        } },
        { key: 'status', label: 'مستوى الخطر', render: (_, row) => badge(row.usage_pct >= 90 ? 'حرج (>90%)' : 'قريب من الحد (>80%)', row.usage_pct >= 90 ? 'red' : 'amber') },
        { key: 'actions', label: 'إجراء', render: (_, row) => el('button', {
          class: 'btn btn-ghost btn-small',
          onclick: () => openTenantManagementModal(row.tenant_id, 'overview'),
        }, 'فتح الشركة') },
      ], nearLimit);
      body.append(limitTable);
    }
  } catch (e) {
    body.innerHTML = '';
    body.append(errorState('تعذر تحميل إحصاءات الاستخدام: ' + e.message, () => loadUsage(container)));
  }
}

// ============================================================
// 5. PLATFORM HEALTH (صحة المنصة)
// ============================================================

export async function loadHealth(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, 'المراقبة والصيانة'),
      el('h1', { text: 'صحة المنصة' }),
      el('p', { style: 'color:var(--muted);font-size:12px;margin:2px 0 0' }, 'مراقبة حالة الخوادم، الاتصال بقواعد البيانات، وسجلات المزامنة التشغيلية'),
    ]),
    el('button', { class: 'btn btn-ghost btn-small', onclick: () => loadHealth(container) }, '↻ فحص الآن'),
  ]));

  const body = el('div', {}, [loadingState('جاري فحص صحة الخوادم والخدمات...')]);
  container.append(body);

  try {
    const [health, sysStatus] = await Promise.all([
      api.get('/admin/health/detailed'),
      api.get('/admin/system-status'),
    ]);

    body.innerHTML = '';

    // The API is up because this response arrived, not because a field said so.
    // The endpoint used to return a hardcoded "api": "ONLINE" that stayed green
    // through any failure the card was supposed to report.
    const isApiOk = !!health;
    const isDbOk = health?.database === 'ONLINE';

    const cards = el('div', { class: 'cards', style: 'margin-bottom:16px' }, [
      metricCard(isApiOk ? 'متصل (ONLINE)' : 'معطّل', 'واجهة برمجة التطبيقات (API)', isApiOk ? 'green' : 'red'),
      metricCard(isDbOk ? 'متصل (ONLINE)' : 'خطأ اتصال', 'قاعدة البيانات (Database)', isDbOk ? 'green' : 'red'),
      metricCard(health?.recent_import_failures_24h ?? 0, 'فشل الاستيراد التشغيلي (24 ساعة)', (health?.recent_import_failures_24h || 0) > 0 ? 'alert' : 'blue'),
      metricCard(health?.pending_attendance_corrections ?? 0, 'تصحيحات الحضور المعلقة', (health?.pending_attendance_corrections || 0) > 0 ? 'amber' : 'gray'),
    ]);
    body.append(cards);

    // Requirement 1 & P7: Real Measured Backup Health Card
    const backupInfo = health?.backup_details || sysStatus?.backup_details || {
      status: sysStatus?.backup_status || 'UNKNOWN',
      has_backups: false,
      storage_destination: 'UNKNOWN',
      message: 'لم يتم قياس حالة النسخ الاحتياطي',
    };

    const isBackupHealthy = backupInfo.status === 'HEALTHY';
    const isLocalOnly = backupInfo.status === 'LOCAL_ONLY_WARNING';

    const backupBadge = isBackupHealthy
      ? badge('سليم ومحدث سحابياً', 'green')
      : isLocalOnly
      ? badge('محلي فقط (بدون S3)', 'amber')
      : badge('لا توجد نسخ احتياطية!', 'red');

    const backupCard = el('div', {
      class: 'card',
      style: `padding:16px 20px;margin-bottom:18px;direction:rtl;border-radius:12px;border:1px solid ${isBackupHealthy ? 'rgba(16,185,129,0.3)' : (isLocalOnly ? 'rgba(245,158,11,0.4)' : 'rgba(239,68,68,0.5)')};background:var(--card)`
    }, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px' }, [
        el('div', { style: 'display:flex;align-items:center;gap:10px' }, [
          el('span', { style: 'font-size:22px' }, isBackupHealthy ? '🛡️' : (isLocalOnly ? '⚠️' : '🚨')),
          el('div', {}, [
            el('h4', { style: 'margin:0;font-size:14px;color:var(--text)' }, 'حالة النسخ الاحتياطي المقاسة (Database Backups Reality)'),
            el('p', { style: 'margin:2px 0 0;font-size:12px;color:var(--muted)' }, backupInfo.message || 'فحص النسخ الاحتياطي الحقيقي من القرص والتخزين السحابي'),
          ])
        ]),
        backupBadge,
      ]),
      el('div', { style: 'display:grid;grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));gap:12px;background:var(--soft);padding:12px;border-radius:8px;font-size:12.5px' }, [
        el('div', {}, [el('span', { style: 'color:var(--muted);display:block' }, 'تاريخ آخر نسخة:'), el('b', { style: 'font-family:monospace' }, backupInfo.last_backup_at ? new Date(backupInfo.last_backup_at).toISOString().replace('T', ' ').slice(0, 19) + ' UTC' : 'لا يوجد')]),
        el('div', {}, [el('span', { style: 'color:var(--muted);display:block' }, 'حجم ملف النسخة:'), el('b', {}, backupInfo.size_formatted || '0 B')]),
        el('div', {}, [el('span', { style: 'color:var(--muted);display:block' }, 'وجهة التخزين:'), el('b', {}, backupInfo.storage_destination || 'غير محدد')]),
        el('div', {}, [el('span', { style: 'color:var(--muted);display:block' }, 'اسم الملف:'), el('b', { style: 'font-family:monospace;font-size:11px' }, backupInfo.last_backup_file || '—')]),
      ])
    ]);
    body.append(backupCard);

    // Feature Flags summary
    const flagsBox = el('div', { class: 'card', style: 'padding:14px;margin-bottom:18px;direction:rtl' }, [
      el('h4', { style: 'margin:0 0 10px;font-size:13.5px', text: 'أعلام وميزات النظام (System Feature Flags)' }),
      el('div', { style: 'display:flex;gap:16px;flex-wrap:wrap;font-size:12px' }, [
        el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'التسجيل العام المفتوح للشركات: '), badge(health?.public_company_signup ? 'مفعّل' : 'معطّل', health?.public_company_signup ? 'green' : 'gray')]),
        el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'وحدات التوصيل القديمة (Legacy Modules): '), badge(health?.legacy_delivery_modules ? 'مفعّل' : 'معطّل', health?.legacy_delivery_modules ? 'blue' : 'gray')]),
      ]),
    ]);
    body.append(flagsBox);

    // Data Sync health table
    const dataHealth = health?.data_health || [];
    body.append(el('h3', { style: 'margin:18px 0 10px;font-size:15px;direction:rtl', text: `حالة مزامنة مصادر البيانات (${dataHealth.length})` }));
    if (!dataHealth.length) {
      body.append(emptyState('لا توجد لقطات صحة بيانات مسجلة.'));
    } else {
      const syncTable = table([
        { key: 'source', label: 'مصدر البيانات', render: (v) => el('b', { text: v || '—' }) },
        { key: 'last_sync_status', label: 'حالة آخر مزامنة', render: (v) => badge(v || '—', v === 'SUCCESS' ? 'green' : 'red') },
        { key: 'last_successful_sync', label: 'آخر مزامنة ناجحة', render: (v) => v ? new Date(v).toLocaleString('en-US') : '—' },
        { key: 'rows_processed', label: 'السجلات المعالجة', render: (v) => el('span', { text: String(v ?? 0) }) },
      ], dataHealth);
      body.append(syncTable);
    }

    // Raw system status inspector (collapsible)
    if (sysStatus) {
      const details = el('details', { style: 'margin-top:20px;direction:rtl' }, [
        el('summary', { style: 'font-size:12px;font-weight:700;color:var(--muted);cursor:pointer;padding:6px 0' }, 'عرض تفاصيل حالة الخدمات الفنية الخام (/admin/system-status)'),
        el('pre', { style: 'direction:ltr;text-align:left;background:var(--soft);padding:14px;border-radius:8px;font-size:11.5px;overflow:auto;margin-top:8px' }, JSON.stringify(sysStatus, null, 2)),
      ]);
      body.append(details);
    }
  } catch (e) {
    body.innerHTML = '';
    body.append(errorState('تعذر فحص صحة المنصة: ' + e.message, () => loadHealth(container)));
  }
}

// ============================================================
// 6. AUDIT LOGS (سجل الإدارة)
// ============================================================

export async function loadAudit(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, 'الحوكمة والأمان'),
      el('h1', { text: 'سجل إدارة DOU' }),
      el('p', { style: 'color:var(--muted);font-size:12px;margin:2px 0 0' }, 'سجل العمليات الحساسة، تعديل الاشتراكات، وجلسات الدخول الفني الآمن'),
    ]),
    el('button', { class: 'btn btn-ghost btn-small', onclick: () => loadAudit(container) }, '↻ تحديث'),
  ]));

  const body = el('div', {}, [loadingState('جاري تحميل سجل العمليات...')]);
  container.append(body);

  try {
    // Try both /admin/audit-logs and fallback /admin/audit-log
    let rows = [];
    try {
      const res = await api.get('/admin/audit-logs');
      rows = Array.isArray(res) ? res : (res.logs || res.rows || []);
    } catch {
      const res2 = await api.get('/admin/audit-log?limit=100');
      rows = Array.isArray(res2) ? res2 : (res2.logs || res2.rows || []);
    }

    body.innerHTML = '';
    if (!rows.length) {
      body.append(emptyState('لا توجد سجلات بعد في سجل الحوكمة.'));
      return;
    }

    const auditTable = table([
      { key: 'created_at', label: 'التاريخ والوقت', render: (v) => v ? new Date(v).toLocaleString('en-US') : '—' },
      { key: 'actor', label: 'المنفّذ', render: (v, row) => el('b', { text: row.actor_name || v || 'مدير المنصة' }) },
      { key: 'tenant', label: 'الشركة المستهدفة', render: (v, row) => row.tenant_name || v || '—' },
      { key: 'action', label: 'العملية المسجلة', render: (v) => el('span', { style: 'font-size:12px', text: v || '—' }) },
    ], rows);

    body.append(auditTable);
  } catch (e) {
    body.innerHTML = '';
    body.append(errorState('تعذر تحميل سجل الحوكمة: ' + e.message, () => loadAudit(container)));
  }
}

// ============================================================
// 7. SETTINGS & SYSTEM CONTROLS (إعدادات النظام)
// ============================================================

export async function loadSettings(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, 'التكوين والسياسات'),
      el('h1', { text: 'إعدادات النظام' }),
      el('p', { style: 'color:var(--muted);font-size:12px;margin:2px 0 0' }, 'معلومات بيئة التشغيل، العملات المعتمدة، وإجراءات الأمان الصارمة'),
    ]),
    el('button', { class: 'btn btn-ghost btn-small', onclick: () => loadSettings(container) }, '↻ تحديث'),
  ]));

  const content = el('div', { style: 'display:grid;gap:16px;direction:rtl' });

  // System Specs
  const specsCard = el('div', { class: 'card', style: 'padding:16px' }, [
    el('h3', { style: 'margin:0 0 12px;font-size:15px', text: '⚙️ بيئة التشغيل ومواصفات المنصة' }),
    el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:12.5px' }, [
      el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'المنصة: '), el('b', { text: 'DOU Fleet OS 2.0 (Canonical Engine)' })]),
      el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'لوحة الإدارة: '), el('b', { text: 'لوحة إدارة واحدة موحدة (/admin)' })]),
      el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'الأسواق التشغيلية: '), el('b', { text: '🇸🇦 المملكة العربية السعودية · 🇪🇬 جمهورية مصر العربية' })]),
      el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'العملات المخزنة: '), el('b', { text: 'SAR (ريال سعودي) · EGP (جنيه مصري)' })]),
      el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'تطبيق السائقين: '), el('b', { text: 'DOU Driver Flutter App + Unified Driver API' })]),
      el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'سلطة تحديد السوق: '), el('b', { text: 'الخادم (Backend Authority via /fleet/me)' })]),
    ]),
  ]);

  // Security and Emergency Operations
  const securityCard = el('div', { class: 'card', style: 'padding:16px;border:1px solid var(--border)' }, [
    el('h3', { style: 'margin:0 0 8px;font-size:15px;color:var(--red)', text: '🔒 إجراءات الأمان والتحكم العاجل' }),
    el('p', { style: 'color:var(--muted);font-size:12px;margin:0 0 14px', text: 'إبطال كافة الجلسات النشطة لجميع المستخدمين في النظام فوراً يجبر الجميع على إعادة الدخول لمنع أي وصول غير مصرح به.' }),
    el('div', { style: 'display:flex;gap:10px' }, [
      el('button', {
        class: 'btn btn-red',
        onclick: async () => {
          confirmModal({
            title: '⚠️ تحذير أمني عاجل',
            message: 'هل أنت متأكد من رغبتك في إبطال كافة الجلسات النشطة لجميع المستخدمين والشركات والسائقين فوراً؟',
            impactText: 'سيتم طرد جميع الجلسات المفتوحة وإلزام الجميع بتسجيل الدخول بكلمة المرور من جديد.',
            confirmLabel: 'تأكيد إبطال كافة الجلسات الآن',
            isDestructive: true,
            onConfirm: async () => {
              try {
                await api.post('/auth/logout-all');
                showToast('🔒 تم إرسال أمر إبطال كافة الجلسات النشطة بنجاح.', 'success');
              } catch (err) {
                showToast('❌ فشل إبطال الجلسات: ' + err.message, 'error');
              }
            },
          });
        },
      }, '⚠️ إبطال كافة الجلسات النشطة لجميع المستخدمين'),
    ]),
  ]);

  content.append(specsCard, securityCard);
  container.append(content);
}

// Helpers
function inputFieldStyle() {
  return 'width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text);font-family:inherit;font-size:12.5px;box-sizing:border-box';
}

function wrapFieldGroup(labelText, inputNode) {
  return el('div', { style: 'display:flex;flex-direction:column;gap:4px' }, [
    el('label', { style: 'font-weight:700;font-size:12px' }, labelText),
    inputNode,
  ]);
}

