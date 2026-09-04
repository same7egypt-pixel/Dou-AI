// Super Admin — Restaurant Dedicated Shifts (DOU Flex) Management & Commercial Margins
import { api } from '../../shared/api/client.js';
import {
  el, loadingState, emptyState, errorState, table, button, escapeHtml,
  modal, metricCard, badge
} from '../../shared/components/ui.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

export async function loadFlexBookings(container) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';

  const headerActions = el('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, [
    el('button', {
      class: 'btn btn-primary btn-small',
      onclick: () => openNewBookingModal(container)
    }, isAr ? '➕ إضافة عقد وردية جديد' : '➕ New Shift Contract'),
    el('button', {
      class: 'btn btn-ghost btn-small',
      style: 'border:1px solid var(--border)',
      onclick: () => openNewMerchantModal(container)
    }, isAr ? '🏬 إضافة مطعم / فرع' : '🏬 Add Restaurant / Branch'),
    el('button', {
      class: 'btn btn-ghost btn-small',
      onclick: () => loadFlexBookings(container)
    }, isAr ? '↻ تحديث' : '↻ Refresh'),
  ]);

  const header = el('div', { class: 'header', style: 'margin-bottom:20px' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'إدارة العقود التجارية وهوامش الربح' : 'Commercial Contracts & Platform Margins'),
      el('h1', { text: isAr ? 'عقود المطاعم (DOU Flex)' : 'Restaurant Flex Contracts' }),
    ]),
    headerActions,
  ]);

  const contentArea = el('div', { id: 'flex-admin-content' }, [
    loadingState(isAr ? 'جاري تحميل العقود والمؤشرات المالية…' : 'Loading contracts and financial metrics…')
  ]);

  container.append(header, contentArea);

  try {
    const [metrics, bookings] = await Promise.all([
      api.get('/admin/dedicated/metrics').catch(() => null),
      api.get('/admin/dedicated/bookings').catch(() => []),
    ]);

    contentArea.innerHTML = '';

    // Render High-Level Commercial KPIs
    if (metrics) {
      const marginColor = metrics.total_monthly_dou_margin > 0 ? 'green' : 'amber';
      const kpis = el('div', { class: 'metrics-grid', style: 'margin-bottom:24px' }, [
        metricCard(
          `${Number(metrics.total_monthly_revenue || 0).toLocaleString()} ${isAr ? 'ر.س' : 'SAR'}`,
          isAr ? 'إجمالي دخل الاشتراكات (من المطاعم)' : 'Gross Revenue (From Merchants)',
          'blue'
        ),
        metricCard(
          `${Number(metrics.total_monthly_payout || 0).toLocaleString()} ${isAr ? 'ر.س' : 'SAR'}`,
          isAr ? 'مستحقات شركات التوصيل (اللوجستية)' : 'Logistics Fleet Payouts',
          'amber'
        ),
        metricCard(
          `${Number(metrics.total_monthly_dou_margin || 0).toLocaleString()} ${isAr ? 'ر.س' : 'SAR'} (${metrics.margin_percentage || 0}%)`,
          isAr ? 'صافي هامش ربح DOU المنصة' : 'DOU Net Margin',
          marginColor
        ),
        metricCard(
          `${metrics.active_bookings || 0} ${isAr ? 'عقد' : 'Contracts'} / ${metrics.active_couriers || 0} ${isAr ? 'مندوب' : 'Riders'}`,
          isAr ? 'الورديات والمناديب المخصصين' : 'Active Shifts & Dedicated Riders',
          'purple'
        ),
      ]);
      contentArea.append(kpis);
    }

    // Render Contracts Table
    const bookingList = Array.isArray(bookings) ? bookings : [];
    if (!bookingList.length) {
      contentArea.append(emptyState(
        isAr ? 'لا توجد عقود ورديات مخصصة مسجلة حالياً. اضغط على «إضافة عقد وردية جديد» للبدء.' : 'No shift contracts registered yet.'
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
          el('span', { style: 'font-size:12px;color:var(--ink2)' }, row.rider_name ? `🛵 ${row.rider_name}` : (isAr ? '⏳ بانتظار التسكين' : '⏳ Pending Rider')),
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
        label: isAr ? 'البيانات المالية (ر.س/شهر)' : 'Financials (SAR/mo)',
        render: (_, row) => el('div', { style: 'font-size:12px;line-height:1.6' }, [
          el('div', {}, [
            el('span', { style: 'color:var(--muted)' }, isAr ? 'اشتراك المطعم: ' : 'Merchant: '),
            el('b', {}, `${Number(row.monthly_fee_to_merchant || 0).toLocaleString()}`)
          ]),
          el('div', {}, [
            el('span', { style: 'color:var(--muted)' }, isAr ? 'مستحق الشركة: ' : 'Fleet: '),
            el('b', {}, `${Number(row.monthly_payout_to_logistics || 0).toLocaleString()}`)
          ]),
          el('div', { style: 'color:var(--green, #16a34a);font-weight:700' }, [
            el('span', {}, isAr ? 'هامش DOU: ' : 'DOU Margin: '),
            el('span', {}, `+${Number(row.dou_margin || 0).toLocaleString()}`)
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
    contentArea.append(errorState(err.message || (isAr ? 'تعذر تحميل العقود' : 'Failed to load contracts'), () => loadFlexBookings(container)));
  }
}

// Modal: Add New Shift Booking
async function openNewBookingModal(mainContainer) {
  const isAr = getLang() === 'ar';
  const overlay = modal(isAr ? '➕ إنشاء عقد وردية مخصصة (DOU Flex)' : '➕ New Shift Contract (DOU Flex)', el('div', {}, [
    loadingState(isAr ? 'جاري تجهيز بيانات المطاعم والشركات…' : 'Loading merchants and fleet companies…')
  ]));

  try {
    const [merchants, tenantsData] = await Promise.all([
      api.get('/admin/dedicated/merchants').catch(() => []),
      api.get('/admin/tenants').catch(() => []),
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

    // Shift Type & Pricing
    const shiftTypeSelect = el('select', {
      class: 'input-select',
      style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)'
    }, [
      el('option', { value: 'full_day_8h' }, isAr ? '🌟 وردية يومية كاملة (8 ساعات)' : '🌟 Full Day (8 Hours)'),
      el('option', { value: 'peak_3h' }, isAr ? '⚡ وردية ذروة مسائية (3 ساعات)' : '⚡ Peak Shift (3 Hours)'),
    ]);

    const feeInput = el('input', {
      type: 'number',
      step: '100',
      value: '7000',
      style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
      required: true
    });

    const payoutInput = el('input', {
      type: 'number',
      step: '100',
      value: '5500',
      style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
      required: true
    });

    const marginDisplay = el('div', {
      style: 'padding:10px;border-radius:8px;background:rgba(22, 163, 74, 0.1);border:1px solid rgba(22, 163, 74, 0.3);font-size:13px;font-weight:700;color:var(--green, #16a34a)'
    }, isAr ? '💰 صافي هامش ربح DOU المتوقع: 1,500 ر.س / شهرياً (21.4%)' : 'Expected DOU Margin: 1,500 SAR / mo');

    function updateMarginCalculation() {
      const fee = parseFloat(feeInput.value) || 0;
      const payout = parseFloat(payoutInput.value) || 0;
      const margin = fee - payout;
      const pct = fee > 0 ? ((margin / fee) * 100).toFixed(1) : '0';
      marginDisplay.textContent = isAr
        ? `💰 صافي هامش ربح DOU المتوقع: ${margin.toLocaleString()} ر.س / شهرياً (${pct}%)`
        : `Expected DOU Margin: ${margin.toLocaleString()} SAR / mo (${pct}%)`;
    }

    feeInput.oninput = updateMarginCalculation;
    payoutInput.oninput = updateMarginCalculation;

    shiftTypeSelect.onchange = () => {
      if (shiftTypeSelect.value === 'peak_3h') {
        feeInput.value = '3500';
        payoutInput.value = '2500';
      } else {
        feeInput.value = '7000';
        payoutInput.value = '5500';
      }
      updateMarginCalculation();
    };

    const submitBtn = el('button', {
      type: 'submit',
      class: 'btn btn-primary',
      style: 'padding:10px;font-weight:700;margin-top:10px'
    }, isAr ? 'حفظ وتفعيل العقد 🚀' : 'Save & Activate Contract');

    form.onsubmit = async (e) => {
      e.preventDefault();
      if (!merchantSelect.value || !branchSelect.value || !tenantSelect.value) {
        alert(isAr ? 'يرجى اختيار المطعم، الفرع، وشركة التوصيل.' : 'Please select restaurant, branch, and fleet company.');
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
          monthly_fee_to_merchant: parseFloat(feeInput.value),
          monthly_payout_to_logistics: parseFloat(payoutInput.value),
          start_date: new Date().toISOString().split('T')[0]
        });

        overlay.close();
        loadFlexBookings(mainContainer);
      } catch (err) {
        alert(err.message || (isAr ? 'فشل حفظ العقد' : 'Failed to save contract'));
        submitBtn.disabled = false;
        submitBtn.textContent = isAr ? 'حفظ وتفعيل العقد 🚀' : 'Save & Activate Contract';
      }
    };

    form.append(
      el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'سلسلة المطاعم:' : 'Restaurant:'),
      merchantSelect,
      el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'الفرع المستفيد:' : 'Branch:'),
      branchSelect,
      el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'شركة الخدمات اللوجستية (المشغلة للأسطول):' : 'Logistics Company:'),
      tenantSelect,
      el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'نوع الوردية:' : 'Shift Type:'),
      shiftTypeSelect,
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
        el('div', {}, [
          el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'قيمة الاشتراك على المطعم (ر.س):' : 'Fee from Merchant:'),
          feeInput,
        ]),
        el('div', {}, [
          el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'مستحق شركة التوصيل (ر.س):' : 'Payout to Fleet:'),
          payoutInput,
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

// Modal: Edit Contract
function openEditBookingModal(booking, mainContainer) {
  const isAr = getLang() === 'ar';
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

  const feeInput = el('input', {
    type: 'number',
    step: '100',
    value: String(booking.monthly_fee_to_merchant || 7000),
    style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)'
  });

  const payoutInput = el('input', {
    type: 'number',
    step: '100',
    value: String(booking.monthly_payout_to_logistics || 5500),
    style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)'
  });

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
        monthly_fee_to_merchant: parseFloat(feeInput.value),
        monthly_payout_to_logistics: parseFloat(payoutInput.value),
      });
      overlay.close();
      loadFlexBookings(mainContainer);
    } catch (err) {
      alert(err.message || (isAr ? 'فشل تحديث العقد' : 'Failed to update contract'));
      saveBtn.disabled = false;
      saveBtn.textContent = isAr ? 'تحديث العقد' : 'Update Contract';
    }
  };

  form.append(
    el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'حالة العقد:' : 'Contract Status:'),
    statusSelect,
    el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'اشتراك المطعم الشهري (ر.س):' : 'Monthly Fee from Merchant:'),
    feeInput,
    el('label', { style: 'font-size:12px;font-weight:700' }, isAr ? 'مستحق شركة التوصيل (ر.س):' : 'Monthly Payout to Fleet:'),
    payoutInput,
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

        alert(isAr
          ? `تم إنشاء المطعم بنجاح!\nمفتاح API الخاص به:\n${res.api_key}`
          : `Merchant created successfully!\nAPI Key:\n${res.api_key}`);

        overlay.close();
        loadFlexBookings(mainContainer);
      } catch (err) {
        alert(err.message || (isAr ? 'فشل إنشاء المطعم' : 'Failed to create merchant'));
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
          alert(isAr ? 'يرجى اختيار المطعم.' : 'Please select merchant.');
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

          alert(isAr ? 'تم إنشاء الفرع وضبط إحداثيات الحضور بنجاح!' : 'Branch created successfully!');
          overlay.close();
          loadFlexBookings(mainContainer);
        } catch (err) {
          alert(err.message || (isAr ? 'فشل حفظ الفرع' : 'Failed to save branch'));
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
