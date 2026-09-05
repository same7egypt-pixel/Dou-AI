// Super Admin — Restaurant Dedicated Shifts (DOU Flex) Management & Commercial Margins
import { api } from '../../shared/api/client.js';
import { appStore } from '../../shared/state/store.js';
import {
  el, loadingState, emptyState, errorState, table, button, escapeHtml,
  modal, metricCard, badge, confirmModal, showToast, money
} from '../../shared/components/ui.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

export async function loadFlexBookings(container, initialTab = 'contracts') {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';
  let activeTab = initialTab;

  const headerActions = el('div', { id: 'flex-header-actions', style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' });

  const header = el('div', { class: 'header', style: 'margin-bottom:14px' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'إدارة العقود التجارية وهوامش الربح وإقفال التسويات' : 'Commercial Contracts & Monthly Settlements'),
      el('h1', { text: isAr ? 'عقود المطاعم والتسويات (DOU Flex)' : 'Restaurant Flex Contracts & Settlements' }),
    ]),
    headerActions,
  ]);

  const tabsBar = el('div', {
    class: 'tabs',
    style: 'display:flex;gap:8px;border-bottom:1px solid var(--border);margin-bottom:20px;direction:rtl'
  });

  const contentArea = el('div', { id: 'flex-admin-content' });

  container.append(header, tabsBar, contentArea);

  function renderTabs() {
    tabsBar.innerHTML = '';
    const contractsTab = el('button', {
      class: `tab ${activeTab === 'contracts' ? 'active' : ''}`,
      onclick: () => { activeTab = 'contracts'; renderCurrentView(); }
    }, isAr ? '📋 عقود الورديات والمقاعد' : '📋 Shift & Seat Contracts');

    const settlementsTab = el('button', {
      class: `tab ${activeTab === 'settlements' ? 'active' : ''}`,
      onclick: () => { activeTab = 'settlements'; renderCurrentView(); }
    }, isAr ? '🔒 تقفيل التسويات الشهرية (P6)' : '🔒 Monthly Settlements Closing (P6)');

    tabsBar.append(contractsTab, settlementsTab);
  }

  function renderCurrentView() {
    renderTabs();
    headerActions.innerHTML = '';
    if (activeTab === 'contracts') {
      headerActions.append(
        el('button', {
          class: 'btn btn-primary btn-small',
          onclick: () => openNewBookingModal(container)
        }, isAr ? '➕ إضافة عقد وردية / مقاعد' : '➕ New Contract / Seats'),
        el('button', {
          class: 'btn btn-ghost btn-small',
          style: 'border:1px solid var(--border)',
          onclick: () => openNewMerchantModal(container)
        }, isAr ? '🏬 إضافة مطعم / فرع' : '🏬 Add Restaurant / Branch'),
        el('button', {
          class: 'btn btn-ghost btn-small',
          onclick: () => renderCurrentView()
        }, isAr ? '↻ تحديث' : '↻ Refresh')
      );
      renderContractsView(contentArea, container);
    } else {
      headerActions.append(
        el('button', {
          class: 'btn btn-ghost btn-small',
          onclick: () => renderCurrentView()
        }, isAr ? '↻ تحديث' : '↻ Refresh')
      );
      renderMonthlySettlements(contentArea, container);
    }
  }

  renderCurrentView();
}

// ─── TAB 1: CONTRACTS & SEATS VIEW ───────────────────────────────────────────
async function renderContractsView(contentArea, container) {
  const isAr = getLang() === 'ar';
  contentArea.innerHTML = '';
  contentArea.append(loadingState(isAr ? 'جاري تحميل العقود والمؤشرات المالية…' : 'Loading contracts and financial metrics…'));

  try {
    const country = appStore.get().selectedCountry;
    const countryParam = country ? `?country=${encodeURIComponent(country)}` : '';
    const [metrics, bookings] = await Promise.all([
      api.get(`/admin/dedicated/metrics${countryParam}`),
      api.get(`/admin/dedicated/bookings${countryParam}`),
    ]);

    contentArea.innerHTML = '';

    const currencyLabel = country === 'EG' ? (isAr ? 'ج.م' : 'EGP') : (isAr ? 'ر.س' : 'SAR');

    // Render High-Level Commercial KPIs
    if (metrics) {
      const kpis = el('div', { class: 'metrics-grid', style: 'margin-bottom:24px' }, [
        metricCard(
          money(metrics.gross_monthly_revenue || 0, currencyLabel),
          isAr ? 'إجمالي دخل الاشتراكات (من المطاعم)' : 'Gross Monthly Revenue (from Restaurants)',
          'blue'
        ),
        metricCard(
          money(metrics.total_logistics_payouts || 0, currencyLabel),
          isAr ? 'مستحقات شركات التوصيل (اللوجستية)' : 'Total Fleet / Logistics Payouts',
          'purple'
        ),
        metricCard(
          `${money(metrics.dou_net_margin || 0, currencyLabel)} (${metrics.margin_percentage || 0}%)`,
          isAr ? 'صافي هامش ربح DOU للمنصة' : 'DOU Platform Net Margin',
          'green'
        ),
        metricCard(
          `${metrics.active_bookings || 0} ${isAr ? 'عقد' : 'Contracts'}`,
          isAr ? 'الورديات والمقاعد النشطة' : 'Active Shifts & Seats',
          'amber'
        ),
      ]);
      contentArea.append(kpis);
    }

    // Render Contracts Table
    const bookingList = Array.isArray(bookings) ? bookings : [];
    if (!bookingList.length) {
      contentArea.append(emptyState(
        isAr ? 'لا توجد عقود ورديات مخصصة مسجلة حالياً. اضغط على «إضافة عقد وردية / مقاعد» للبدء.' : 'No shift contracts registered yet.'
      ));
      return;
    }

    const columns = [
      {
        key: 'merchant',
        label: isAr ? 'المطعم والفرع' : 'Merchant & Branch',
        render: (_, row) => el('div', {}, [
          el('b', { style: 'display:block;font-size:13px' }, row.merchant_name || '—'),
          el('span', { style: 'font-size:12px;color:var(--muted)' }, `📍 ${row.branch_name || '—'}`),
        ])
      },
      {
        key: 'fleet',
        label: isAr ? 'شركة الأسطول والمندوب' : 'Fleet & Courier',
        render: (_, row) => el('div', {}, [
          el('b', { style: 'display:block;font-size:13px;color:var(--primary)' }, row.tenant_name || '—'),
          row.rider_name
            ? el('span', { style: 'font-size:12px;color:var(--ink2)' }, `🛵 ${row.rider_name}`)
            : badge(isAr ? '🪑 مقعد شاغر' : '🪑 Vacant Seat', 'gray'),
        ])
      },
      {
        key: 'shift_type',
        label: isAr ? 'نوع الوردية' : 'Shift Type',
        render: (val) => val === 'peak_3h'
          ? el('span', { class: 'badge badge-amber', style: 'font-weight:700' }, isAr ? '⚡ ذروة 3 ساعات' : '⚡ Peak 3h')
          : el('span', { class: 'badge badge-blue', style: 'font-weight:700' }, isAr ? '🌟 يومي 8 ساعات' : '🌟 Full Day 8h')
      },
      {
        key: 'financials',
        label: isAr ? `البيانات المالية والتعاقدية (${currencyLabel}/شهر)` : `Financials (${currencyLabel}/mo)`,
        render: (_, row) => el('div', { style: 'font-size:12px;line-height:1.6' }, [
          el('div', {}, [
            el('span', { style: 'color:var(--muted)' }, isAr ? 'اشتراك المطعم لـ DOU: ' : 'Restaurant Fee: '),
            el('b', {}, money(row.monthly_fee_to_merchant, currencyLabel))
          ]),
          el('div', {}, [
            el('span', { style: 'color:var(--muted)' }, isAr ? 'مستحق الشركة اللوجستية: ' : 'Logistics Payout: '),
            el('b', {}, money(row.monthly_payout_to_logistics, currencyLabel))
          ]),
          el('div', { style: 'color:var(--green, #16a34a);font-weight:700' }, [
            el('span', {}, isAr ? 'صافي هامش DOU المحتجز: ' : 'DOU Margin: '),
            el('span', {}, money(row.dou_margin, currencyLabel))
          ]),
        ])
      },
      {
        key: 'today',
        label: isAr ? 'حالة اليوم' : 'Today Status',
        render: (_, row) => el('div', { style: 'font-size:12px' }, [
          row.is_checked_in_today
            ? el('span', { class: 'badge badge-green' }, isAr ? '🟢 حاضر بالـ GPS' : '🟢 Checked In')
            : el('span', { class: 'badge badge-gray' }, isAr ? '⚪ لم يحضر بعد' : '⚪ Not Checked In'),
          el('div', { style: 'margin-top:4px;color:var(--muted)' }, `${row.today_orders_count || 0} ${isAr ? 'طلبات' : 'orders'}`)
        ])
      },
      {
        key: 'status',
        label: isAr ? 'حالة العقد' : 'Status',
        render: (val) => {
          const color = val === 'active' ? 'green' : val === 'paused' ? 'amber' : 'red';
          return badge(val === 'active' ? (isAr ? 'نشط' : 'Active') : val, color);
        }
      },
      {
        key: 'actions',
        label: isAr ? 'إجراء' : 'Actions',
        render: (_, row) => el('div', { style: 'display:flex;gap:4px' }, [
          el('button', {
            class: 'btn btn-ghost btn-small',
            onclick: () => openEditBookingModal(row, container)
          }, isAr ? '✏️ تعديل' : '✏️ Edit'),
        ])
      }
    ];

    const tableEl = table(columns, bookingList);
    const tableContainer = el('div', {
      class: 'card',
      style: 'background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;overflow-x:auto'
    }, [tableEl]);

    contentArea.append(tableContainer);

  } catch (err) {
    contentArea.innerHTML = '';
    contentArea.append(errorState(err.message || (isAr ? 'تعذر تحميل العقود' : 'Failed to load contracts'), () => renderContractsView(contentArea, container)));
  }
}

// ─── TAB 2: MONTHLY SETTLEMENT CLOSING PIPELINE (P6) ──────────────────────────
async function renderMonthlySettlements(contentArea, mainContainer) {
  const isAr = getLang() === 'ar';
  const country = appStore.get().selectedCountry;
  const currencyLabel = country === 'EG' ? (isAr ? 'ج.م' : 'EGP') : (isAr ? 'ر.س' : 'SAR');

  contentArea.innerHTML = '';

  // Pipeline Stepper Banner
  const stepperCard = el('div', {
    class: 'card',
    style: 'padding:16px;margin-bottom:20px;background:var(--card);border:1px solid var(--border);border-radius:12px'
  }, [
    el('div', { style: 'font-weight:700;margin-bottom:8px;font-size:14px;color:var(--text)' },
      isAr ? '🔄 مسار إقفال التسويات الشهرية للشركات اللوجستية (Rule 6)' : 'Monthly Settlement Closing Pipeline (Rule 6)'
    ),
    el('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:center;font-size:13px' }, [
      el('span', { class: 'badge badge-gray', style: 'padding:6px 10px' }, isAr ? '١. مسودة احتساب (Draft)' : '1. Draft Calculation'),
      el('span', {}, '➔'),
      el('span', { class: 'badge badge-blue', style: 'padding:6px 10px' }, isAr ? '٢. مراجعة المطابقة (Review)' : '2. Verification & Review'),
      el('span', {}, '➔'),
      el('span', { class: 'badge badge-amber', style: 'padding:6px 10px' }, isAr ? '٣. إصدار رسمي مقفل 🔒 (Issued)' : '3. Official Lock & Issued'),
      el('span', {}, '➔'),
      el('span', { class: 'badge badge-green', style: 'padding:6px 10px' }, isAr ? '٤. سداد بنكي موثق 💳 (Paid)' : '4. Bank Paid & Reconciled'),
    ]),
    el('div', { style: 'margin-top:8px;font-size:12px;color:var(--muted)' },
      isAr
        ? '💡 بمجرد إصدار التصفية يتم قفل السجل المالي نهائياً ولا يمكن إعادة احتسابه التزاماً بالحوكمة وقواعد الثبات المحاسبي.'
        : 'Once issued, settlement figures are permanently locked and cannot be overwritten.'
    )
  ]);

  // Control Bar (Month Picker + Generate Button)
  const defaultMonth = new Date().toISOString().slice(0, 7);
  const monthInput = el('input', {
    type: 'month',
    value: defaultMonth,
    style: 'padding:6px 10px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:13px'
  });

  const generateBtn = el('button', {
    class: 'btn btn-primary btn-small',
    style: 'display:flex;align-items:center;gap:6px'
  }, isAr ? '⚡ توليد / تحديث مسودات الشهر' : '⚡ Generate / Recalculate Drafts');

  const controlBar = el('div', {
    style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:10px'
  }, [
    el('div', { style: 'display:flex;align-items:center;gap:8px' }, [
      el('label', { style: 'font-weight:700;font-size:13px' }, isAr ? 'الشهر المالي:' : 'Financial Month:'),
      monthInput
    ]),
    generateBtn
  ]);

  const settlementsContent = el('div', {}, [
    loadingState(isAr ? 'جاري تحميل التسويات الشهرية…' : 'Loading monthly settlements…')
  ]);

  contentArea.append(stepperCard, controlBar, settlementsContent);

  async function loadData() {
    settlementsContent.innerHTML = '';
    settlementsContent.append(loadingState(isAr ? 'جاري التحميل…' : 'Loading…'));

    try {
      const q = new URLSearchParams({ month: monthInput.value });
      if (country) q.set('country', country);

      const data = await api.get(`/admin/dedicated/settlements?${q.toString()}`);
      settlementsContent.innerHTML = '';

      // Summary KPIs
      const kpis = el('div', { class: 'metrics-grid', style: 'margin-bottom:20px' }, [
        metricCard(
          money(data.total_gross || 0, currencyLabel),
          isAr ? 'إجمالي دخل الاشتراكات (من المطاعم)' : 'Total Gross Revenue',
          'blue'
        ),
        metricCard(
          money(data.total_payout || 0, currencyLabel),
          isAr ? 'مستحقات الشركات اللوجستية' : 'Total Logistics Payouts',
          'purple'
        ),
        metricCard(
          money(data.total_margin || 0, currencyLabel),
          isAr ? 'صافي هامش منصة DOU' : 'DOU Platform Net Margin',
          'green'
        ),
        metricCard(
          `${data.settlements?.length || 0} ${isAr ? 'تصفية' : 'Settlements'}`,
          isAr ? `مسودة (${data.counts_by_status?.draft || 0}) | مصدر (${data.counts_by_status?.issued || 0}) | مسدد (${data.counts_by_status?.paid || 0})` : 'Settlement Statuses',
          'amber'
        )
      ]);

      if (!data.settlements || !data.settlements.length) {
        settlementsContent.append(kpis, emptyState(
          isAr
            ? `لا توجد تسويات مسجلة لشهر ${monthInput.value}. اضغط على «توليد / تحديث مسودات الشهر» لحساب مستحقات الشركات.`
            : `No settlements found for ${monthInput.value}. Click "Generate / Recalculate Drafts" to build drafts.`
        ));
        return;
      }

      const columns = [
        {
          key: 'tenant',
          label: isAr ? 'الشركة اللوجستية' : 'Logistics Company',
          render: (_, row) => el('b', { style: 'font-size:13px;color:var(--text)' }, row.tenant_name || `Tenant #${row.tenant_id}`)
        },
        {
          key: 'month',
          label: isAr ? 'الشهر المالي' : 'Month',
          render: (val) => el('span', { style: 'font-family:monospace;font-size:13px' }, val)
        },
        {
          key: 'gross',
          label: isAr ? 'دخل المطاعم' : 'Gross',
          render: (_, row) => el('span', { style: 'font-size:12px' }, money(row.gross_amount, row.currency || currencyLabel))
        },
        {
          key: 'payout',
          label: isAr ? 'مستحق الشركة' : 'Payout',
          render: (_, row) => el('b', { style: 'font-size:12px;color:var(--primary)' }, money(row.logistics_payout, row.currency || currencyLabel))
        },
        {
          key: 'margin',
          label: isAr ? 'هامش DOU' : 'Margin',
          render: (_, row) => el('span', { style: 'font-size:12px;color:var(--green);font-weight:700' }, money(row.dou_margin, row.currency || currencyLabel))
        },
        {
          key: 'status',
          label: isAr ? 'حالة التصفية' : 'Status',
          render: (val) => {
            if (val === 'paid') return badge(isAr ? '💳 مسدد' : 'Paid', 'green');
            if (val === 'issued') return badge(isAr ? '🔒 رسمي مقفل' : 'Issued (Locked)', 'amber');
            if (val === 'reviewed') return badge(isAr ? 'مراجعة' : 'Reviewed', 'blue');
            return badge(isAr ? 'مسودة' : 'Draft', 'gray');
          }
        },
        {
          key: 'reference',
          label: isAr ? 'التوثيق والمرجع البنكي' : 'Documentation & Reference',
          render: (_, row) => {
            const lines = [];
            if (row.payment_reference) {
              lines.push(el('div', { style: 'font-size:11px;font-family:monospace' }, `Ref: ${row.payment_reference}`));
            }
            if (row.paid_at) {
              lines.push(el('div', { style: 'font-size:11px;color:var(--muted)' }, `Paid: ${row.paid_at.slice(0, 10)}`));
            } else if (row.issued_at) {
              lines.push(el('div', { style: 'font-size:11px;color:var(--muted)' }, `Issued: ${row.issued_at.slice(0, 10)}`));
            }
            return lines.length ? el('div', {}, lines) : el('span', { style: 'color:var(--muted);font-size:12px' }, '—');
          }
        },
        {
          key: 'actions',
          label: isAr ? 'الإجراءات' : 'Actions',
          render: (_, row) => {
            const actionsDiv = el('div', { style: 'display:flex;gap:6px' });

            if (row.status === 'draft' || row.status === 'reviewed') {
              actionsDiv.append(
                el('button', {
                  class: 'btn btn-primary btn-small',
                  onclick: () => {
                    confirmModal({
                      title: isAr ? 'إصدار التصفية الشهرية رسميًا' : 'Issue Official Settlement',
                      message: isAr
                        ? `هل أنت متأكد من اعتماد وإصدار تصفية شهر ${row.month} لشركة "${row.tenant_name}" بقيمة مستحقة ${money(row.logistics_payout, row.currency)}؟`
                        : `Are you sure you want to issue settlement for ${row.tenant_name} (${row.month})?`,
                      impactText: isAr
                        ? '⚠️ تنبيه حوكمة: بمجرد الإصدار سيتم قفل السجل المحاسبي ولن يمكن إعادة الاحتساب أو التعديل (Rule 6).'
                        : 'Settlement will be permanently locked from recalculation.',
                      confirmLabel: isAr ? '🔒 قفل وإصدار التصفية' : 'Lock & Issue',
                      onConfirm: async () => {
                        try {
                          await api.post(`/admin/dedicated/settlements/${row.id}/issue`);
                          showToast(isAr ? 'تم إصدار التصفية الشهرية وقفل السجل بنجاح 🔒' : 'Settlement issued and locked', 'success');
                          loadData();
                        } catch (err) {
                          showToast(err.message || (isAr ? 'فشل إصدار التصفية' : 'Failed to issue settlement'), 'error');
                        }
                      }
                    });
                  }
                }, isAr ? '🔒 إصدار رسمي' : '🔒 Issue')
              );
            } else if (row.status === 'issued') {
              actionsDiv.append(
                el('button', {
                  class: 'btn btn-ghost btn-small',
                  style: 'border:1px solid var(--green);color:var(--green);font-weight:700',
                  onclick: () => openPaymentRecordModal(row, loadData)
                }, isAr ? '💳 تسجيل سداد' : '💳 Pay')
              );
            } else if (row.status === 'paid') {
              actionsDiv.append(
                el('span', { style: 'font-size:12px;color:var(--green);font-weight:700' }, '✅ منتهي')
              );
            }

            return actionsDiv;
          }
        }
      ];

      const settlementsTable = table(columns, data.settlements);
      const tableWrapper = el('div', {
        class: 'card',
        style: 'background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;overflow-x:auto'
      }, [settlementsTable]);

      settlementsContent.append(kpis, tableWrapper);

    } catch (err) {
      settlementsContent.innerHTML = '';
      settlementsContent.append(errorState(err.message || (isAr ? 'تعذر تحميل التسويات' : 'Failed to load settlements'), loadData));
    }
  }

  monthInput.onchange = () => loadData();

  generateBtn.onclick = async () => {
    generateBtn.disabled = true;
    generateBtn.textContent = isAr ? 'جاري التوليد…' : 'Generating…';
    try {
      const res = await api.post('/admin/dedicated/settlements/generate', {
        month: monthInput.value
      });
      showToast(
        isAr
          ? `تم تحديث التسويات بنجاح! تم توليد ${res.generated_count || 0} مسودة${res.skipped_immutable_count ? ` وتخطي ${res.skipped_immutable_count} مسجلة مسبقاً ومقفلة` : ''}.`
          : `Generated ${res.generated_count} drafts.`,
        'success'
      );
      loadData();
    } catch (err) {
      showToast(err.message || (isAr ? 'فشل توليد التسويات' : 'Failed to generate settlements'), 'error');
    } finally {
      generateBtn.disabled = false;
      generateBtn.textContent = isAr ? '⚡ توليد / تحديث مسودات الشهر' : '⚡ Generate / Recalculate Drafts';
    }
  };

  loadData();
}

// Modal: Record Settlement Bank Payment
function openPaymentRecordModal(settlement, onSuccess) {
  const isAr = getLang() === 'ar';
  const overlay = modal(
    isAr ? `💳 تسجيل سداد التصفية (${settlement.tenant_name})` : `Record Settlement Payment (${settlement.tenant_name})`,
    el('div', {}, [])
  );
  const modalBody = overlay.querySelector('.modal-body');

  const form = el('form', { style: 'display:grid;gap:12px;direction:rtl' });

  const infoNotice = el('div', {
    style: 'padding:10px;border-radius:8px;background:var(--soft);border:1px solid var(--border);font-size:12px;color:var(--text)'
  }, [
    el('div', {}, `${isAr ? 'المبلغ المستحق للتحويل للشركة:' : 'Amount to pay to logistics:'} `),
    el('b', { style: 'font-size:15px;color:var(--primary)' }, money(settlement.logistics_payout, settlement.currency))
  ]);

  const refInput = el('input', {
    type: 'text',
    placeholder: isAr ? 'مثال: TRF-2026-981726' : 'e.g. TRF-2026-981726',
    style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
    required: true
  });

  const notesInput = el('input', {
    type: 'text',
    placeholder: isAr ? 'ملاحظات إضافية أو اسم البنك المحول منه' : 'Notes or bank name',
    style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)'
  });

  const submitBtn = el('button', {
    type: 'submit',
    class: 'btn btn-primary',
    style: 'padding:10px;font-weight:700;margin-top:8px'
  }, isAr ? 'تأكيد وحفظ السداد 💳' : 'Confirm Payment');

  form.onsubmit = async (e) => {
    e.preventDefault();
    if (!refInput.value.trim()) {
      showToast(isAr ? 'يرجى إدخال رقم الحوالة أو المرجع البنكي' : 'Please enter payment reference', 'error');
      return;
    }
    submitBtn.disabled = true;
    submitBtn.textContent = isAr ? 'جاري التسجيل…' : 'Recording…';
    try {
      await api.post(`/admin/dedicated/settlements/${settlement.id}/pay`, {
        payment_reference: refInput.value.trim(),
        payment_notes: notesInput.value.trim() || null
      });
      showToast(isAr ? 'تم تسجيل سداد التصفية بنجاح ✅' : 'Payment recorded successfully', 'success');
      overlay.close();
      if (onSuccess) onSuccess();
    } catch (err) {
      showToast(err.message || (isAr ? 'فشل تسجيل السداد' : 'Payment recording failed'), 'error');
      submitBtn.disabled = false;
      submitBtn.textContent = isAr ? 'تأكيد وحفظ السداد 💳' : 'Confirm Payment';
    }
  };

  form.append(
    infoNotice,
    el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'رقم الحوالة أو المرجع البنكي:' : 'Payment / Transfer Reference:'),
    refInput,
    el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'ملاحظات التحويل:' : 'Transfer Notes:'),
    notesInput,
    submitBtn
  );

  modalBody.append(form);
}

// Modal: Add New Shift Booking with Bulk Seats Support
async function openNewBookingModal(mainContainer) {
  const isAr = getLang() === 'ar';
  const country = appStore.get().selectedCountry;
  const currencyLabel = country === 'EG' ? (isAr ? 'ج.م' : 'EGP') : (isAr ? 'ر.س' : 'SAR');

  const overlay = modal(isAr ? '➕ إنشاء عقد وردية ومقاعد (DOU Flex)' : '➕ New Shift Contract & Seats', el('div', {}, [
    loadingState(isAr ? 'جاري تجهيز بيانات المطاعم والشركات…' : 'Loading merchants and fleet companies…')
  ]));

  try {
    const [merchants, tenantsData] = await Promise.all([
      api.get('/admin/dedicated/merchants'),
      api.get('/admin/tenants'),
    ]);

    const tenantList = tenantsData.tenants || tenantsData || [];
    const modalBody = overlay.querySelector('.modal-body');
    modalBody.innerHTML = '';

    const form = el('form', { style: 'display:grid;gap:14px;direction:rtl' });

    // Merchant & Branch Selectors
    const merchantSelect = el('select', {
      class: 'input-select',
      style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
      required: true
    }, [
      el('option', { value: '' }, isAr ? '-- اختر سلسلة المطاعم --' : '-- Select Restaurant --'),
      ...merchants.map(m => el('option', { value: String(m.id) }, `${m.name} (${m.branches ? m.branches.length : 0} فرع)`))
    ]);

    const branchSelect = el('select', {
      class: 'input-select',
      style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
      required: true
    }, [
      el('option', { value: '' }, isAr ? '-- اختر الفرع أولاً --' : '-- Select Branch --')
    ]);

    merchantSelect.onchange = () => {
      const selectedM = merchants.find(m => String(m.id) === merchantSelect.value);
      branchSelect.innerHTML = '';
      if (!selectedM || !selectedM.branches || !selectedM.branches.length) {
        branchSelect.append(el('option', { value: '' }, isAr ? 'لا توجد فروع مسجلة لهذا المطعم' : 'No branches'));
        return;
      }
      selectedM.branches.forEach(b => {
        branchSelect.append(el('option', { value: String(b.id) }, `${b.name} (${b.address || ''})`));
      });
    };

    // Fleet Company Selector
    const tenantSelect = el('select', {
      class: 'input-select',
      style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
      required: true
    }, [
      el('option', { value: '' }, isAr ? '-- اختر شركة الخدمات اللوجستية الموردة --' : '-- Select Logistics Fleet --'),
      ...tenantList.map(t => el('option', { value: String(t.id) }, t.name))
    ]);

    // Shift Type
    const shiftTypeSelect = el('select', {
      class: 'input-select',
      style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)'
    }, [
      el('option', { value: 'full_day_8h' }, isAr ? '🌟 وردية يومية كاملة (8 ساعات)' : '🌟 Full Day (8 Hours)'),
      el('option', { value: 'peak_3h' }, isAr ? '⚡ وردية ذروة مسائية (3 ساعات)' : '⚡ Peak Shift (3 Hours)'),
    ]);

    // Contracted Seats Count (Bulk Generation)
    const seatsCountInput = el('input', {
      type: 'number',
      min: '1',
      max: '100',
      value: '1',
      style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
      required: true
    });

    const merchantFeeInput = el('input', {
      type: 'number',
      step: '100',
      value: '7000',
      style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
      required: true
    });

    const fleetPayoutInput = el('input', {
      type: 'number',
      step: '100',
      value: '5500',
      style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
      required: true
    });

    const marginDisplay = el('div', {
      style: 'padding:10px;border-radius:8px;background:rgba(37, 99, 235, 0.08);border:1px solid rgba(37, 99, 235, 0.25);font-size:13px;font-weight:700;color:var(--primary)'
    });

    function updateMarginCalculation() {
      const fee = parseFloat(merchantFeeInput.value) || 0;
      const payout = parseFloat(fleetPayoutInput.value) || 0;
      const seats = parseInt(seatsCountInput.value, 10) || 1;
      const marginPerSeat = fee - payout;
      const totalMargin = marginPerSeat * seats;
      const pct = fee > 0 ? (Math.round((marginPerSeat / fee) * 1000) / 10) : 0;
      marginDisplay.textContent = isAr
        ? `🏢 صافي هامش ربح DOU المنصة: ${money(totalMargin, currencyLabel)} (${pct}% | ${seats} مقاعد)`
        : `DOU Platform Net Margin: ${money(totalMargin, currencyLabel)} (${pct}% | ${seats} seats)`;
    }

    merchantFeeInput.oninput = updateMarginCalculation;
    fleetPayoutInput.oninput = updateMarginCalculation;
    seatsCountInput.oninput = updateMarginCalculation;
    updateMarginCalculation();

    shiftTypeSelect.onchange = () => {
      if (shiftTypeSelect.value === 'peak_3h') {
        merchantFeeInput.value = '3500';
        fleetPayoutInput.value = '2500';
      } else {
        merchantFeeInput.value = '7000';
        fleetPayoutInput.value = '5500';
      }
      updateMarginCalculation();
    };

    const submitBtn = el('button', {
      type: 'submit',
      class: 'btn btn-primary',
      style: 'padding:10px;font-weight:700;margin-top:10px'
    }, isAr ? 'حفظ وتفعيل العقد والمقاعد 🚀' : 'Save & Activate Contract');

    form.onsubmit = async (e) => {
      e.preventDefault();
      if (!merchantSelect.value || !branchSelect.value || !tenantSelect.value) {
        showToast(isAr ? 'يرجى اختيار المطعم، الفرع، وشركة التوصيل.' : 'Please select restaurant, branch, and fleet company.', 'error');
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = isAr ? 'جاري الحفظ…' : 'Saving…';

      try {
        await api.post('/admin/dedicated/bookings', {
          merchant_id: parseInt(merchantSelect.value),
          branch_id: parseInt(branchSelect.value),
          tenant_id: parseInt(tenantSelect.value),
          shift_type: shiftTypeSelect.value,
          seats_count: parseInt(seatsCountInput.value, 10) || 1,
          monthly_fee_to_merchant: parseFloat(merchantFeeInput.value),
          monthly_payout_to_logistics: parseFloat(fleetPayoutInput.value),
          start_date: new Date().toISOString().split('T')[0]
        });

        showToast(isAr ? 'تم إنشاء وحفظ العقد والمقاعد بنجاح! 🚀' : 'Contract and seats created successfully!', 'success');
        overlay.close();
        loadFlexBookings(mainContainer);
      } catch (err) {
        showToast(err.message || (isAr ? 'فشل حفظ العقد' : 'Failed to save contract'), 'error');
        submitBtn.disabled = false;
        submitBtn.textContent = isAr ? 'حفظ وتفعيل العقد والمقاعد 🚀' : 'Save & Activate Contract';
      }
    };

    form.append(
      el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'سلسلة المطاعم:' : 'Restaurant:'),
      merchantSelect,
      el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'الفرع المستفيد:' : 'Branch:'),
      branchSelect,
      el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'شركة الخدمات اللوجستية (المشغلة للأسطول):' : 'Logistics Company:'),
      tenantSelect,
      el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'عدد المقاعد التعاقدية (المناديب المطلوبة):' : 'Number of Contracted Seats:'),
      seatsCountInput,
      el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'نوع الوردية:' : 'Shift Type:'),
      shiftTypeSelect,
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
        el('div', {}, [
          el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? `اشتراك المطعم الشهري لكل مقعد لـ DOU (${currencyLabel}):` : `Merchant Fee per seat to DOU (${currencyLabel}):`),
          merchantFeeInput
        ]),
        el('div', {}, [
          el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? `مستحق الشركة اللوجستية لكل مقعد (${currencyLabel}):` : `Logistics Payout per seat (${currencyLabel}):`),
          fleetPayoutInput
        ]),
      ]),
      marginDisplay,
      submitBtn
    );

    modalBody.append(form);
  } catch (err) {
    overlay.querySelector('.modal-body').innerHTML = '';
    overlay.querySelector('.modal-body').append(errorState(err.message));
  }
}

// Modal: Edit Shift Booking
function openEditBookingModal(booking, mainContainer) {
  const isAr = getLang() === 'ar';
  const country = appStore.get().selectedCountry;
  const currencyLabel = country === 'EG' ? (isAr ? 'ج.م' : 'EGP') : (isAr ? 'ر.س' : 'SAR');
  const overlay = modal(isAr ? `تعديل عقد وردية (${booking.branch_name})` : `Edit Contract (${booking.branch_name})`, el('div', {}, []));
  const modalBody = overlay.querySelector('.modal-body');

  const form = el('form', { style: 'display:grid;gap:12px;direction:rtl' });

  const statusSelect = el('select', {
    class: 'input-select',
    style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)'
  }, [
    el('option', { value: 'active', selected: booking.status === 'active' }, isAr ? 'نشط (Active)' : 'Active'),
    el('option', { value: 'paused', selected: booking.status === 'paused' }, isAr ? 'موقوف مؤقتاً (Paused)' : 'Paused'),
    el('option', { value: 'cancelled', selected: booking.status === 'cancelled' }, isAr ? 'ملغي (Cancelled)' : 'Cancelled'),
  ]);

  const merchantFeeInput = el('input', {
    type: 'number',
    step: '100',
    value: String(booking.monthly_fee_to_merchant || 7000),
    style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)'
  });

  const fleetPayoutInput = el('input', {
    type: 'number',
    step: '100',
    value: String(booking.monthly_payout_to_logistics || 5500),
    style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)'
  });

  const editMarginDisplay = el('div', {
    style: 'padding:8px 10px;border-radius:8px;background:rgba(37, 99, 235, 0.08);border:1px solid rgba(37, 99, 235, 0.25);font-size:12px;font-weight:700;color:var(--primary)'
  });

  function updateEditMargin() {
    const fee = parseFloat(merchantFeeInput.value) || 0;
    const payout = parseFloat(fleetPayoutInput.value) || 0;
    const margin = fee - payout;
    const pct = fee > 0 ? (Math.round((margin / fee) * 1000) / 10) : 0;
    editMarginDisplay.textContent = isAr
      ? `🏢 صافي هامش DOU: ${money(margin, currencyLabel)} (${pct}%)`
      : `DOU Net Margin: ${money(margin, currencyLabel)} (${pct}%)`;
  }

  merchantFeeInput.oninput = updateEditMargin;
  fleetPayoutInput.oninput = updateEditMargin;
  updateEditMargin();

  const saveBtn = el('button', {
    type: 'submit',
    class: 'btn btn-primary',
    style: 'padding:10px;font-weight:700;margin-top:8px'
  }, isAr ? 'تحديث العقد' : 'Update Contract');

  form.onsubmit = async (e) => {
    e.preventDefault();
    saveBtn.disabled = true;
    saveBtn.textContent = isAr ? 'جاري التحديث…' : 'Updating…';

    try {
      await api.patch(`/admin/dedicated/bookings/${booking.id}`, {
        status: statusSelect.value,
        monthly_fee_to_merchant: parseFloat(merchantFeeInput.value),
        monthly_payout_to_logistics: parseFloat(fleetPayoutInput.value),
      });
      showToast(isAr ? 'تم تحديث بيانات العقد بنجاح' : 'Contract updated successfully', 'success');
      overlay.close();
      loadFlexBookings(mainContainer);
    } catch (err) {
      showToast(err.message || (isAr ? 'فشل تحديث العقد' : 'Failed to update contract'), 'error');
      saveBtn.disabled = false;
      saveBtn.textContent = isAr ? 'تحديث العقد' : 'Update Contract';
    }
  };

  form.append(
    el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'حالة العقد:' : 'Contract Status:'),
    statusSelect,
    el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? `اشتراك المطعم الشهري لـ DOU (${currencyLabel}):` : `Monthly Restaurant Fee to DOU (${currencyLabel}):`),
    merchantFeeInput,
    el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? `المستحق الشهري للشركة اللوجستية (${currencyLabel}):` : `Monthly Logistics Payout (${currencyLabel}):`),
    fleetPayoutInput,
    editMarginDisplay,
    saveBtn
  );

  modalBody.append(form);
}

// Modal: Onboard Merchant & Branch
function openNewMerchantModal(mainContainer) {
  const isAr = getLang() === 'ar';
  const overlay = modal(isAr ? '🏬 تسجيل مطعم أو فرع جديد' : '🏬 Onboard Merchant or Branch', el('div', {}, []));
  const modalBody = overlay.querySelector('.modal-body');

  let activeTab = 'merchant'; // 'merchant' | 'branch'

  function renderModalTabs() {
    modalBody.innerHTML = '';
    const tabs = el('div', { class: 'tabs', style: 'margin-bottom:14px;direction:rtl' }, [
      el('button', {
        class: `tab ${activeTab === 'merchant' ? 'active' : ''}`,
        onclick: () => { activeTab = 'merchant'; renderModalTabs(); }
      }, isAr ? '1. تسجيل سلسلة مطاعم جديدة' : '1. New Merchant Chain'),
      el('button', {
        class: `tab ${activeTab === 'branch' ? 'active' : ''}`,
        onclick: () => { activeTab = 'branch'; renderModalTabs(); }
      }, isAr ? '2. إضافة فرع لسلسلة قائمة' : '2. Add Branch to Merchant'),
    ]);
    modalBody.append(tabs);

    if (activeTab === 'merchant') {
      renderMerchantForm();
    } else {
      renderBranchForm();
    }
  }

  function renderMerchantForm() {
    const form = el('form', { style: 'display:grid;gap:12px;direction:rtl' });
    const nameInput = el('input', {
      type: 'text',
      placeholder: isAr ? 'مثال: شاورما كلاسيك' : 'e.g. Shawarma Classic',
      style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
      required: true
    });
    const crInput = el('input', {
      type: 'text',
      placeholder: isAr ? 'السجل التجاري (اختياري)' : 'Commercial Registration',
      style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)'
    });
    const phoneInput = el('input', {
      type: 'tel',
      placeholder: '0501234567',
      style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)'
    });
    const emailInput = el('input', {
      type: 'email',
      placeholder: 'operations@restaurant.com',
      style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)'
    });

    const submitBtn = el('button', {
      type: 'submit',
      class: 'btn btn-primary',
      style: 'padding:10px;font-weight:700;margin-top:8px'
    }, isAr ? 'إنشاء حساب المطعم وتوليد مفتاح API' : 'Create Merchant & Generate API Key');

    form.onsubmit = async (e) => {
      e.preventDefault();
      submitBtn.disabled = true;
      submitBtn.textContent = isAr ? 'جاري الإنشاء…' : 'Creating…';

      try {
        const res = await api.post('/admin/dedicated/merchants', {
          name: nameInput.value.trim(),
          commercial_reg: crInput.value.trim() || null,
          contact_phone: phoneInput.value.trim() || null,
          contact_email: emailInput.value.trim() || null,
        });

        modalBody.innerHTML = '';
        const successBox = el('div', { style: 'text-align:center;padding:16px;direction:rtl' }, [
          el('div', { style: 'font-size:36px;margin-bottom:8px' }, '🎉'),
          el('h3', { style: 'margin:0 0 8px;font-size:16px' }, isAr ? 'تم إنشاء حساب المطعم بنجاح!' : 'Merchant created successfully!'),
          el('p', { style: 'font-size:12px;color:var(--muted);margin-bottom:14px' },
            isAr ? 'يرجى نسخ وحفظ مفتاح API أدناه بأمان لمطعمك:' : 'Please securely copy and save the API key below:'),
          el('input', {
            type: 'text',
            value: res.api_key || '—',
            readonly: true,
            style: 'width:100%;padding:10px;font-family:monospace;font-size:13px;text-align:center;border-radius:8px;border:1px solid var(--border);background:var(--soft);color:var(--primary);margin-bottom:14px'
          }),
          el('button', {
            class: 'btn btn-primary',
            style: 'width:100%;padding:10px;font-weight:700',
            onclick: () => {
              if (res.api_key && navigator.clipboard) {
                navigator.clipboard.writeText(res.api_key);
              }
              showToast(isAr ? 'تم نسخ المفتاح للحافظة 📋' : 'API Key copied to clipboard', 'success');
              overlay.close();
              loadFlexBookings(mainContainer);
            }
          }, isAr ? '📋 نسخ المفتاح وإغلاق' : '📋 Copy Key & Close')
        ]);
        modalBody.append(successBox);
      } catch (err) {
        showToast(err.message || (isAr ? 'فشل إنشاء المطعم' : 'Failed to create merchant'), 'error');
        submitBtn.disabled = false;
        submitBtn.textContent = isAr ? 'إنشاء حساب المطعم' : 'Create Merchant';
      }
    };

    form.append(
      el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'اسم المطعم / العلامة التجارية:' : 'Restaurant Name:'),
      nameInput,
      el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'رقم السجل التجاري:' : 'CR Number:'),
      crInput,
      el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'رقم الجوال:' : 'Phone:'),
      phoneInput,
      el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'البريد الإلكتروني:' : 'Email:'),
      emailInput,
      submitBtn
    );
    modalBody.append(form);
  }

  async function renderBranchForm() {
    const loadingEl = loadingState(isAr ? 'جاري تحميل قائمة المطاعم…' : 'Loading merchants…');
    modalBody.append(loadingEl);

    try {
      const merchants = await api.get('/admin/dedicated/merchants');
      loadingEl.remove();

      const form = el('form', { style: 'display:grid;gap:12px;direction:rtl' });

      const merchantSelect = el('select', {
        class: 'input-select',
        style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
        required: true
      }, [
        el('option', { value: '' }, isAr ? '-- اختر المطعم --' : '-- Select Merchant --'),
        ...merchants.map(m => el('option', { value: String(m.id) }, m.name))
      ]);

      const branchNameInput = el('input', {
        type: 'text',
        placeholder: isAr ? 'مثال: فرع السليمانية - الرياض' : 'e.g. As Sulimaniyah Branch',
        style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
        required: true
      });

      const latInput = el('input', {
        type: 'number',
        step: '0.000001',
        placeholder: '24.7085',
        value: '24.7085',
        style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
        required: true
      });

      const lngInput = el('input', {
        type: 'number',
        step: '0.000001',
        placeholder: '46.6970',
        value: '46.6970',
        style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
        required: true
      });

      const radiusInput = el('input', {
        type: 'number',
        value: '150',
        style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
        required: true
      });

      const pinInput = el('input', {
        type: 'password',
        maxLength: '6',
        placeholder: '2026',
        value: '2026',
        style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
        required: true
      });

      const submitBtn = el('button', {
        type: 'submit',
        class: 'btn btn-primary',
        style: 'padding:10px;font-weight:700;margin-top:8px'
      }, isAr ? 'حفظ الفرع وتفعيل سياج الحضور الجغرافي 📍' : 'Save Branch & Enable Geofence');

      form.onsubmit = async (e) => {
        e.preventDefault();
        if (!merchantSelect.value) {
          showToast(isAr ? 'يرجى اختيار المطعم.' : 'Please select merchant.', 'error');
          return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = isAr ? 'جاري الحفظ…' : 'Saving…';

        try {
          await api.post(`/admin/dedicated/merchants/${merchantSelect.value}/branches`, {
            name: branchNameInput.value.trim(),
            latitude: parseFloat(latInput.value),
            longitude: parseFloat(lngInput.value),
            geofence_radius_meters: parseInt(radiusInput.value) || 150,
            cashier_pin: pinInput.value.trim()
          });

          showToast(isAr ? 'تم إنشاء الفرع وضبط إحداثيات الحضور بنجاح!' : 'Branch created successfully!', 'success');
          overlay.close();
          loadFlexBookings(mainContainer);
        } catch (err) {
          showToast(err.message || (isAr ? 'فشل حفظ الفرع' : 'Failed to save branch'), 'error');
          submitBtn.disabled = false;
          submitBtn.textContent = isAr ? 'حفظ الفرع' : 'Save Branch';
        }
      };

      form.append(
        el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'المطعم التابع له:' : 'Parent Restaurant:'),
        merchantSelect,
        el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'اسم الفرع:' : 'Branch Name:'),
        branchNameInput,
        el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
          el('div', {}, [
            el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'خط العرض (Latitude):' : 'Latitude:'),
            latInput,
          ]),
          el('div', {}, [
            el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'خط الطول (Longitude):' : 'Longitude:'),
            lngInput,
          ]),
        ]),
        el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'نطاق السياج الجغرافي للحضور (متر):' : 'Geofence Radius (Meters):'),
        radiusInput,
        el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'رمز مرور الكاشير (PIN):' : 'Cashier PIN:'),
        pinInput,
        submitBtn
      );
      modalBody.append(form);
    } catch (err) {
      loadingEl.remove();
      modalBody.append(errorState(err.message));
    }
  }

  renderModalTabs();
}
