// Super Admin — Tenants Management
import { api } from '../../shared/api/client.js';
import { appStore } from '../../shared/state/store.js';
import { el, loadingState, emptyState, errorState, table, button, escapeHtml, modal, badge, confirmModal, showToast, money } from '../../shared/components/ui.js';

export async function supportLogin(tenantId, tenantName) {
  confirmModal({
    title: 'دخول دعم آمن',
    message: `فتح جلسة دعم آمنة للشركة "${tenantName || tenantId}"؟`,
    impactText: 'سيتم تسجيل العملية في سجل الحوكمة والأمان ومطابقة الصلاحيات.',
    confirmLabel: 'متابعة الدخول',
    onConfirm: async () => {
      try {
        const res = await api.post(`/admin/tenants/${tenantId}/support-login`);
        localStorage.setItem('dou_token_v2', res.access_token);
        localStorage.setItem('dou_token_fleet', res.access_token);
        localStorage.setItem('dou_role', res.role);
        localStorage.setItem('dou_role_v2', res.role);
        window.open('/app', '_blank');
      } catch (e) {
        showToast('❌ تعذر تسجيل الدخول كدعم: ' + (e.message || e), 'error');
      }
    }
  });
}

export function exportTenantPaymentsCsv(tenantName, payments = []) {
  if (!payments || !payments.length) {
    showToast('لا توجد دفعات مسجلة لتصديرها', 'warning');
    return;
  }
  const headers = ['رقم الإيصال', 'التاريخ', 'المبلغ', 'العملة', 'طريقة الدفع', 'عدد الشهور', 'المرجع', 'سجله', 'ملاحظات'];
  const methodMap = { CASH: 'كاش', BANK_TRANSFER: 'تحويل بنكي', CARD: 'بطاقة', OTHER: 'أخرى' };
  const rows = payments.map((p) => [
    p.receipt_number || '',
    p.paid_at ? p.paid_at.slice(0, 10) : '',
    p.amount ?? '',
    p.currency || '',
    methodMap[p.payment_method] || p.payment_method || '',
    p.period_months ?? 1,
    p.reference || '',
    p.recorded_by || '',
    p.notes || '',
  ]);
  const csv = '\ufeff' + [headers, ...rows].map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `DOU-${tenantName || 'tenant'}-payments.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export async function openTenantManagementModal(tenantId, initialTab = 'overview', onUpdated = null) {
  const overlay = modal('🏢 إدارة الشركة والاشتراك', el('div', {}, [loadingState('جاري تحميل بيانات الشركة...')]));
  const modalBody = overlay.querySelector('.modal-body');

  try {
    const [tenant, plans] = await Promise.all([
      api.get(`/admin/tenants/${tenantId}`),
      api.get('/admin/plans'),
    ]);

    function renderModalContent(activeTab) {
      modalBody.innerHTML = '';
      const isSuspended = tenant.subscription_status === 'SUSPENDED';

      // Header summary & quick actions
      const headerBox = el('div', { style: 'background:var(--soft);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;direction:rtl' }, [
        el('div', {}, [
          el('div', { style: 'display:flex;align-items:center;gap:8px' }, [
            el('h3', { style: 'margin:0;font-size:16px', text: tenant.name }),
            badge(tenant.subscription_status || 'ACTIVE', tenant.subscription_status === 'ACTIVE' ? 'green' : (tenant.subscription_status === 'OVERDUE' ? 'amber' : 'red')),
            badge(tenant.country === 'EG' ? '🇪🇬 مصر' : '🇸🇦 السعودية', 'blue'),
          ]),
          el('div', { style: 'font-size:12px;color:var(--muted);margin-top:4px' }, [
            el('span', { text: `الباقة: ${tenant.plan || '—'} · ` }),
            el('span', { text: `الرسوم: ${tenant.monthly_fee || 0} ${tenant.currency || 'SAR'} · ` }),
            el('span', { text: `المناديب: ${tenant.couriers_count || 0}` }),
          ]),
        ]),
        el('div', { style: 'display:flex;gap:8px;align-items:center' }, [
          el('button', {
            class: 'btn btn-primary btn-small',
            title: 'فتح جلسة تشغيلية باسم الشركة',
            onclick: () => supportLogin(tenant.id, tenant.name),
          }, '🔑 دخول دعم آمن'),
          el('button', {
            class: `btn btn-small ${isSuspended ? 'btn-blue' : 'btn-ghost'}`,
            onclick: () => {
              const newStatus = isSuspended ? 'ACTIVE' : 'SUSPENDED';
              const actionLabel = isSuspended ? 'تفعيل' : 'تجميد';
              confirmModal({
                title: `${actionLabel} حساب الشركة`,
                message: `هل تريد ${actionLabel} حساب شركة "${tenant.name}"؟`,
                impactText: isSuspended ? 'سيتم إعادة تفعيل صلاحيات الدخول والعمليات لجميع مستخدمي الشركة.' : 'سيتم تعليق وصول مناديب ومشرفي الشركة مؤقتاً لحين فك التجميد.',
                confirmLabel: `تأكيد ${actionLabel}`,
                isDestructive: !isSuspended,
                onConfirm: async () => {
                  try {
                    await api.patch(`/admin/tenants/${tenant.id}`, { subscription_status: newStatus });
                    tenant.subscription_status = newStatus;
                    showToast(`تم ${actionLabel} شركة "${tenant.name}" بنجاح`, 'success');
                    if (onUpdated) onUpdated();
                    renderModalContent(activeTab);
                  } catch (err) {
                    showToast('فشل تغيير الحالة: ' + err.message, 'error');
                  }
                }
              });
            },
          }, isSuspended ? 'تنشيط الشركة' : 'تجميد الشركة'),
        ]),
      ]);

      // Tabs switcher
      const tabsBar = el('div', { style: 'display:flex;gap:6px;border-bottom:1px solid var(--border);margin-bottom:14px;direction:rtl' }, [
        createTabBtn('overview', '📋 بيانات الشركة والاشتراك', activeTab),
        createTabBtn('payment', '💵 تسجيل دفعة وإيصال', activeTab),
        createTabBtn('history', `📜 سجل الإيصالات (${tenant.payments?.length || 0})`, activeTab),
        createTabBtn('users', `👥 مستخدمو الإدارة (${tenant.users?.length || 0})`, activeTab),
      ]);

      function createTabBtn(id, label, current) {
        const isActive = id === current;
        return el('button', {
          class: `btn btn-small ${isActive ? 'btn-primary' : 'btn-ghost'}`,
          style: 'border-radius:6px 6px 0 0;margin-bottom:-1px',
          onclick: () => renderModalContent(id),
        }, label);
      }

      // Tab Content Area
      let tabContainer = el('div', { style: 'direction:rtl' });

      if (activeTab === 'overview') {
        // Edit company details form
        const form = el('form', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:12.5px' });

        const nameInput = createInput('اسم الشركة', tenant.name);
        const phoneInput = createInput('جوال التواصل', tenant.contact_phone || '');
        const emailInput = createInput('البريد الإلكتروني', tenant.contact_email || '', 'email');
        const feeInput = createInput('الرسوم الشهرية المتفق عليها', tenant.monthly_fee || 0, 'number');
        const billingDayInput = createInput('يوم الفوترة (1-28)', tenant.billing_day || 1, 'number');
        const dueDateInput = createInput('تاريخ الاستحقاق القادم', tenant.due_date ? tenant.due_date.slice(0, 10) : '', 'date');

        const planSelect = el('select', { style: inputStyle() }, plans.map((p) => el('option', { value: p.code, ...(p.code === tenant.plan ? { selected: 'selected' } : {}) }, `${p.name} (${p.code}) — ${p.monthly_price} SAR`)));
        const statusSelect = el('select', { style: inputStyle() }, [
          el('option', { value: 'ACTIVE', ...(tenant.subscription_status === 'ACTIVE' ? { selected: 'selected' } : {}) }, 'نشط (ACTIVE)'),
          el('option', { value: 'OVERDUE', ...(tenant.subscription_status === 'OVERDUE' ? { selected: 'selected' } : {}) }, 'متأخر (OVERDUE)'),
          el('option', { value: 'SUSPENDED', ...(tenant.subscription_status === 'SUSPENDED' ? { selected: 'selected' } : {}) }, 'موقوف (SUSPENDED)'),
        ]);
        const typeSelect = el('select', { style: inputStyle() }, [
          el('option', { value: 'LOGISTICS_OPERATOR', ...(tenant.customer_type === 'LOGISTICS_OPERATOR' ? { selected: 'selected' } : {}) }, 'شركة لوجستية (مشغل أسطول)'),
          el('option', { value: 'DELIVERY_PLATFORM', ...(tenant.customer_type === 'DELIVERY_PLATFORM' ? { selected: 'selected' } : {}) }, 'منصة توصيل (Delivery Platform)'),
        ]);
        const currencySelect = el('select', { style: inputStyle() }, [
          el('option', { value: 'SAR', ...(tenant.currency === 'SAR' ? { selected: 'selected' } : {}) }, 'ريال سعودي (SAR)'),
          el('option', { value: 'EGP', ...(tenant.currency === 'EGP' ? { selected: 'selected' } : {}) }, 'جنيه مصري (EGP)'),
          el('option', { value: 'USD', ...(tenant.currency === 'USD' ? { selected: 'selected' } : {}) }, 'دولار أمريكي (USD)'),
        ]);

        form.append(
          wrapField('اسم الشركة:', nameInput),
          wrapField('نوع الحساب:', typeSelect),
          wrapField('جوال التواصل:', phoneInput),
          wrapField('البريد الإلكتروني:', emailInput),
          wrapField('باقة الاشتراك:', planSelect),
          wrapField('العملة:', currencySelect),
          wrapField('الرسوم الشهرية:', feeInput),
          wrapField('يوم الفوترة الشهري:', billingDayInput),
          wrapField('تاريخ الاستحقاق القادم:', dueDateInput),
          wrapField('حالة الاشتراك:', statusSelect)
        );

        const saveBtn = el('button', { type: 'submit', class: 'btn btn-primary', style: 'grid-column:span 2;padding:10px;margin-top:6px;font-weight:700' }, '💾 حفظ التعديلات');
        form.append(saveBtn);

        form.onsubmit = async (e) => {
          e.preventDefault();
          saveBtn.disabled = true;
          saveBtn.textContent = 'جاري الحفظ…';
          try {
            const patchData = {
              name: nameInput.value.trim(),
              contact_phone: phoneInput.value.trim(),
              contact_email: emailInput.value.trim(),
              plan: planSelect.value,
              currency: currencySelect.value,
              monthly_fee: parseFloat(feeInput.value) || 0,
              billing_day: parseInt(billingDayInput.value, 10) || 1,
              due_date: dueDateInput.value || null,
              subscription_status: statusSelect.value,
            };
            patchData['customer_type'] = typeSelect.value;
            await api.patch(`/admin/tenants/${tenant.id}`, patchData);
            showToast('✅ تم حفظ بيانات الشركة والاشتراك بنجاح', 'success');
            tenant.name = nameInput.value.trim();
            tenant.plan = planSelect.value;
            tenant.customer_type = typeSelect.value;
            tenant.currency = currencySelect.value;
            tenant.monthly_fee = parseFloat(feeInput.value) || 0;
            tenant.subscription_status = statusSelect.value;
            if (onUpdated) onUpdated();
            renderModalContent('overview');
          } catch (err) {
            showToast('❌ فشل حفظ التعديلات: ' + err.message, 'error');
            saveBtn.disabled = false;
            saveBtn.textContent = '💾 حفظ التعديلات';
          }
        };

        tabContainer.append(form);
      } else if (activeTab === 'payment') {
        // Record payment form
        const payBox = el('div', { class: 'card', style: 'padding:14px;background:var(--soft)' });
        payBox.append(el('h4', { style: 'margin:0 0 6px', text: '💵 تسجيل دفعة اشتراك وإصدار إيصال رسمي' }));
        payBox.append(el('p', { style: 'color:var(--muted);font-size:12px;margin:0 0 14px', text: 'تسجيل الإيصال يضيف المبلغ للإيراد الفعلي للشهر ويجدد تاريخ الاستحقاق تلقائياً بعدد الشهور المحدد.' }));

        const form = el('form', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:12px' });

        const monthlyFee = Number(tenant.monthly_fee || 0);
        const monthsInput = createInput('عدد الشهور المدفوعة (1-36)', '1', 'number');
        monthsInput.min = '1';
        monthsInput.max = '36';

        const amountInput = createInput('المبلغ الإجمالي', monthlyFee, 'number');
        amountInput.step = '0.01';

        const methodSelect = el('select', { style: inputStyle() }, [
          el('option', { value: 'BANK_TRANSFER' }, 'تحويل بنكي (Bank Transfer)'),
          el('option', { value: 'CASH' }, 'كاش / نقدي'),
          el('option', { value: 'CARD' }, 'بطاقة مدى / ائتمان'),
          el('option', { value: 'OTHER' }, 'أخرى / تسوية'),
        ]);

        const dateInput = createInput('تاريخ الدفع', new Date().toISOString().slice(0, 10), 'date');
        const refInput = createInput('مرجع التحويل / رقم الحوالة', '');
        const notesInput = createInput('ملاحظات إضافية', '');

        const varianceWrap = el('div', { style: 'grid-column:span 2;margin:4px 0' }, [
          el('label', { style: 'display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer' }, [
            el('input', { type: 'checkbox', id: 'payVarianceCheck', style: 'width:auto;cursor:pointer' }),
            el('span', {}, 'اعتماد مبلغ مختلف عن السعر المتفق عليه (خصم خاص أو تسوية موثقة)'),
          ]),
        ]);

        const expectedNotice = el('div', { style: 'grid-column:span 2;font-size:12px;color:var(--muted);padding:6px;background:var(--card);border-radius:6px' }, `المتوقع: ${money(monthlyFee, tenant.currency || 'SAR')} لشهر واحد`);

        monthsInput.oninput = () => {
          const m = Math.max(1, parseInt(monthsInput.value, 10) || 1);
          const exp = monthlyFee * m;
          amountInput.value = exp;
          expectedNotice.textContent = `المتوقع: ${money(exp, tenant.currency || 'SAR')} حسب السعر الشهري × ${m} شهر`;
        };

        const paySubmitBtn = el('button', { type: 'submit', class: 'btn btn-primary', style: 'grid-column:span 2;padding:10px;font-weight:700' }, 'تسجيل الدفعة وإصدار الإيصال');

        form.append(
          wrapField('عدد الشهور:', monthsInput),
          wrapField('المبلغ الإجمالي:', amountInput),
          wrapField('طريقة الدفع:', methodSelect),
          wrapField('تاريخ الدفع:', dateInput),
          wrapField('رقم المرجع / الحوالة:', refInput),
          wrapField('الملاحظات:', notesInput),
          varianceWrap,
          expectedNotice,
          paySubmitBtn
        );

        form.onsubmit = async (e) => {
          e.preventDefault();
          paySubmitBtn.disabled = true;
          paySubmitBtn.textContent = 'جاري التسجيل وإصدار الإيصال…';
          try {
            const varianceCheck = form.querySelector('#payVarianceCheck');
            const res = await api.post(`/admin/tenants/${tenant.id}/payments`, {
              amount: parseFloat(amountInput.value) || 0,
              period_months: parseInt(monthsInput.value, 10) || 1,
              payment_method: methodSelect.value,
              paid_at: dateInput.value,
              reference: refInput.value.trim(),
              notes: notesInput.value.trim(),
              allow_variance: varianceCheck?.checked || false,
            });
            showToast(`✅ تم تسجيل الدفعة بنجاح! رقم الإيصال: ${res.receipt_number} (${money(res.amount, res.currency)})`, 'success');
            // Reload tenant details
            const updated = await api.get(`/admin/tenants/${tenant.id}`);
            Object.assign(tenant, updated);
            if (onUpdated) onUpdated();
            renderModalContent('history');
          } catch (err) {
            showToast('❌ فشل تسجيل الدفعة: ' + err.message, 'error');
            paySubmitBtn.disabled = false;
            paySubmitBtn.textContent = 'تسجيل الدفعة وإصدار الإيصال';
          }
        };

        payBox.append(form);
        tabContainer.append(payBox);
      } else if (activeTab === 'history') {
        // Payments history list
        const payments = tenant.payments || [];
        const topActions = el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:10px' }, [
          el('h4', { style: 'margin:0', text: `سجل الإيصالات والمدفوعات (${payments.length})` }),
          el('button', {
            class: 'btn btn-ghost btn-small',
            onclick: () => exportTenantPaymentsCsv(tenant.name, payments),
          }, '📥 تنزيل CSV'),
        ]);

        if (!payments.length) {
          tabContainer.append(topActions, emptyState('لا توجد دفعات مسجلة لهذه الشركة بعد.'));
        } else {
          const paymentsTable = table([
            { key: 'receipt_number', label: 'رقم الإيصال', render: (v) => el('b', { style: 'font-family:monospace;color:var(--primary)', text: v || '—' }) },
            { key: 'paid_at', label: 'التاريخ', render: (v) => v ? new Date(v).toLocaleDateString('en-GB') : '—' },
            { key: 'amount', label: 'المبلغ', render: (v, row) => el('b', { text: `${v} ${row.currency || tenant.currency || 'SAR'}` }) },
            { key: 'payment_method', label: 'طريقة الدفع', render: (v) => ({ CASH: 'كاش', BANK_TRANSFER: 'تحويل بنكي', CARD: 'بطاقة', OTHER: 'أخرى' }[v] || v || '—') },
            { key: 'period_months', label: 'المدة', render: (v) => `${v || 1} شهر` },
            { key: 'recorded_by', label: 'سجله', render: (v) => v || '—' },
          ], payments);
          tabContainer.append(topActions, paymentsTable);
        }
      } else if (activeTab === 'users') {
        // Users & Couriers stats
        const users = tenant.users || [];
        const statsRow = el('div', { class: 'cards', style: 'margin-bottom:12px' }, [
          el('div', { class: 'metric blue' }, [el('b', { text: String(tenant.couriers_count || 0) }), el('span', { text: 'إجمالي المناديب المسجلين' })]),
          el('div', { class: 'metric gray' }, [el('b', { text: String(users.length) }), el('span', { text: 'مستخدمو الإدارة والعمليات' })]),
        ]);

        const usersTable = table([
          { key: 'name', label: 'الاسم', render: (v) => el('b', { text: v || '—' }) },
          { key: 'phone', label: 'الهاتف', render: (v) => el('span', { style: 'direction:ltr;display:inline-block', text: v || '—' }) },
          { key: 'role', label: 'الصلاحية', render: (v) => badge(v, 'blue') },
          { key: 'active', label: 'الحالة', render: (v) => badge(v ? 'نشط' : 'موقوف', v ? 'green' : 'red') },
          { key: 'last_login_at', label: 'آخر دخول', render: (v) => v ? new Date(v).toLocaleDateString('en-GB') : '—' },
        ], users);

        tabContainer.append(statsRow, usersTable);
      }

      modalBody.append(headerBox, tabsBar, tabContainer);
    }

    renderModalContent(initialTab);
  } catch (err) {
    modalBody.innerHTML = '';
    modalBody.append(errorState('تعذر تحميل بيانات الشركة: ' + err.message));
  }
}

function inputStyle() {
  return 'width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text);font-family:inherit;font-size:12.5px;box-sizing:border-box';
}

function createInput(placeholder, value = '', type = 'text') {
  return el('input', {
    type,
    placeholder,
    value: value ?? '',
    style: inputStyle(),
  });
}

function wrapField(labelText, fieldElement) {
  return el('div', { style: 'display:flex;flex-direction:column;gap:4px' }, [
    el('label', { style: 'font-weight:700;font-size:12px' }, labelText),
    fieldElement,
  ]);
}

export async function loadTenants(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, 'إدارة المنصة'),
      el('h1', { text: 'الشركات المشتركة' }),
      el('p', { style: 'color:var(--muted);font-size:12px;margin:2px 0 0' }, 'إدارة تراخيص الشركات اللوجستية، متابعة الاشتراكات والأسعار، وتسجيل الدخول كدعم فني'),
    ]),
    el('div', { style: 'display:flex;gap:8px;align-items:center' }, [
      el('button', { class: 'btn btn-primary btn-small', onclick: () => openNewTenantModal(container) }, '➕ إضافة شركة جديدة'),
      el('button', { class: 'btn btn-ghost btn-small', onclick: () => loadTenants(container) }, '↻ تحديث'),
    ]),
  ]));

  const body = el('div', {}, [loadingState('جاري تحميل الشركات...')]);
  container.append(body);

  try {
    const country = appStore.get().selectedCountry;
    const url = '/admin/tenants' + (country ? `?country=${encodeURIComponent(country)}` : '');
    const data = await api.get(url);
    const rows = data.tenants || data || [];
    if (!rows.length) {
      body.replaceWith(emptyState('لا توجد شركات مسجلة في هذا النطاق.'));
      return;
    }

    body.replaceWith(table([
      { key: 'name', label: 'الشركة', render: (v, row) => el('div', { style: 'display:flex;flex-direction:column;gap:2px' }, [
        el('b', { style: 'font-size:13px', text: v || '—' }),
        el('small', { style: 'color:var(--muted)', text: row.contact_phone || '' }),
      ]) },
      { key: 'country', label: 'البلد', render: (v) => v === 'EG' ? '🇪🇬 مصر' : (v === 'SA' ? '🇸🇦 السعودية' : (v || '—')) },
      { key: 'customer_type', label: 'النوع', render: (v) => v === 'DELIVERY_PLATFORM' ? badge('منصة توصيل', 'blue') : badge('شركة لوجستية', 'gray') },
      { key: 'plan', label: 'الباقة', render: (v) => badge(v || '—', 'blue') },
      { key: 'monthly_fee', label: 'الرسوم الشهرية', render: (v, row) => el('b', { text: v != null ? `${v} ${row.currency || 'SAR'}` : '—' }) },
      { key: 'couriers_count', label: 'المناديب', render: (v) => el('span', { style: 'font-weight:700', text: v != null ? String(v) : '—' }) },
      { key: 'status', label: 'حالة الاشتراك', render: (v, row) => {
        const s = row.subscription_status || v || 'ACTIVE';
        return badge(s, s === 'ACTIVE' ? 'green' : (s === 'OVERDUE' ? 'amber' : 'red'));
      } },
      { key: 'actions', label: 'إجراءات تشغيلية', render: (_, row) => el('div', { style: 'display:flex;gap:6px;align-items:center' }, [
        el('button', {
          class: 'btn btn-primary btn-small',
          style: 'padding:4px 8px;font-size:11px',
          title: 'دخول مباشر كدعم فني',
          onclick: () => supportLogin(row.id, row.name),
        }, '🔑 دخول دعم'),
        el('button', {
          class: 'btn btn-ghost btn-small',
          style: 'padding:4px 8px;font-size:11px',
          title: 'إدارة وتعديل بيانات واشتراك الشركة',
          onclick: () => openTenantManagementModal(row.id, 'overview', () => loadTenants(container)),
        }, '⚙ إدارة'),
      ]) },
    ], rows));
  } catch (e) {
    body.replaceWith(errorState('تعذر تحميل الشركات: ' + e.message, () => loadTenants(container)));
  }
}

function openNewTenantModal(mainContainer) {
  const overlay = modal('🏢 تسجيل شركة جديدة', el('div', {}, []));
  const modalBody = overlay.querySelector('.modal-body');

  const form = el('form', { style: 'display:grid;gap:12px;direction:rtl' });

  const nameInput = el('input', {
    type: 'text',
    placeholder: 'اسم الشركة (مثال: أسطول الرياض السريع)',
    style: inputStyle(),
    required: true,
  });

  const phoneInput = el('input', {
    type: 'tel',
    placeholder: 'رقم هاتف المالك/المدير (مثال: 0501234567)',
    style: inputStyle(),
    required: true,
  });

  const passInput = el('input', {
    type: 'password',
    placeholder: 'كلمة المرور (8 أحرف على الأقل)',
    style: inputStyle(),
    required: true,
  });

  const typeSelect = el('select', {
    id: 'ncType',
    style: inputStyle(),
    required: true,
  }, [
    el('option', { value: 'LOGISTICS_OPERATOR' }, 'شركة لوجستية (مشغل أسطول مناديب)'),
    el('option', { value: 'DELIVERY_PLATFORM' }, 'منصة توصيل (Delivery Platform)'),
  ]);

  const marketSelect = el('select', {
    id: 'ncMarket',
    style: inputStyle(),
  }, [
    el('option', { value: 'SA' }, '🇸🇦 المملكة العربية السعودية (SAR)'),
    el('option', { value: 'EG' }, '🇪🇬 جمهورية مصر العربية (EGP)'),
  ]);

  const planSelect = el('select', {
    id: 'ncPlan',
    style: inputStyle(),
  }, [
    el('option', { value: 'GROWTH' }, 'باقة النمو (GROWTH)'),
    el('option', { value: 'STARTER' }, 'الباقة الأساسية (STARTER)'),
    el('option', { value: 'SCALE' }, 'باقة التوسع (SCALE)'),
    el('option', { value: 'ENTERPRISE' }, 'باقة المؤسسات (ENTERPRISE)'),
  ]);

  const submitBtn = el('button', {
    type: 'submit',
    class: 'btn btn-primary',
    style: 'padding:10px;font-weight:700;margin-top:8px',
  }, 'إنشاء الشركة');

  form.append(
    wrapField('اسم الشركة:', nameInput),
    wrapField('رقم هاتف المالك:', phoneInput),
    wrapField('كلمة المرور:', passInput),
    wrapField('نوع الحساب:', typeSelect),
    wrapField('الدولة وسوق التشغيل:', marketSelect),
    wrapField('باقة الاشتراك:', planSelect),
    submitBtn
  );

  form.onsubmit = async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    submitBtn.textContent = 'جاري الإنشاء…';
    try {
      const payload = {
        name: nameInput.value.trim(),
        owner_phone: phoneInput.value.trim(),
        password: passInput.value,
        market: marketSelect.value,
        plan: planSelect.value,
      };
      payload['customer_type'] = typeSelect.value;
      await api.post('/admin/tenants', payload);
      showToast('تم إنشاء الشركة بنجاح!', 'success');
      overlay.close();
      loadTenants(mainContainer);
    } catch (err) {
      showToast(err.message || 'فشل إنشاء الشركة', 'error');
      submitBtn.disabled = false;
      submitBtn.textContent = 'إنشاء الشركة';
    }
  };

  modalBody.append(form);
}
