// Super Admin — Tenants
import { api } from '../../shared/api/client.js';
import { appStore } from '../../shared/state/store.js';
import { el, loadingState, emptyState, errorState, table, button, escapeHtml, modal, badge } from '../../shared/components/ui.js';

export async function loadTenants(container) {
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, 'إدارة الشركات'),
      el('h1', { text: 'الشركات المشتركة' })
    ]),
    el('div', { style: 'display:flex;gap:8px;align-items:center' }, [
      el('button', { class: 'btn btn-primary btn-small', onclick: () => openNewTenantModal(container) }, '➕ إضافة شركة جديدة'),
      el('button', { class: 'btn btn-ghost btn-small', onclick: () => loadTenants(container) }, '↻ تحديث'),
    ])
  ]));
  const body = el('div', {}, [loadingState('جاري تحميل الشركات...')]);
  container.append(body);
  try {
    const country = appStore.get().selectedCountry;
    const url = '/admin/tenants' + (country ? `?country=${encodeURIComponent(country)}` : '');
    const data = await api.get(url);
    const rows = data.tenants || data || [];
    if (!rows.length) { body.replaceWith(emptyState('لا توجد شركات بعد.')); return; }

    function showTenantDetails(tenant) {
      const content = el('div', { style: 'display:grid;gap:12px;direction:rtl' }, [
        el('div', { style: 'display:flex;justify-content:space-between;align-items:center' }, [
          el('h3', { text: tenant.name || 'تفاصيل الشركة' }),
          badge(tenant.subscription_status || tenant.status || 'ACTIVE', (tenant.subscription_status === 'ACTIVE' || tenant.status === 'ACTIVE') ? 'green' : 'amber'),
        ]),
        el('div', { class: 'card', style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:12px;font-size:13px' }, [
          el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'البلد: '), el('b', { text: tenant.country || '—' })]),
          el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'العملة: '), el('b', { text: tenant.currency || '—' })]),
          el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'الباقة: '), el('b', { text: tenant.plan || '—' })]),
          el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'نوع الحساب: '), el('b', { text: tenant.customer_type === 'DELIVERY_PLATFORM' ? 'منصة توصيل' : (tenant.customer_type === 'LOGISTICS_OPERATOR' ? 'شركة لوجستية' : '—') })]),
          el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'الرسوم الشهرية: '), el('b', { text: tenant.monthly_fee != null ? `${tenant.monthly_fee} ${tenant.currency || ''}`.trim() : '—' })]),
          el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'عدد المناديب: '), el('b', { text: tenant.couriers_count != null ? String(tenant.couriers_count) : '—' })]),
          el('div', {}, [el('span', { style: 'color:var(--muted)' }, 'تاريخ الاستحقاق: '), el('b', { text: tenant.due_date ? new Date(tenant.due_date).toLocaleDateString('ar-SA') : '—' })]),
        ]),
      ]);
      modal(`تفاصيل شركة ${tenant.name || '—'}`, content);
    }

    body.replaceWith(table([
      { key: 'name', label: 'الشركة', render: (v) => v || '—' },
      { key: 'country', label: 'البلد', render: (v) => v || '—' },
      { key: 'customer_type', label: 'النوع', render: (v) => v === 'DELIVERY_PLATFORM' ? 'منصة' : (v === 'LOGISTICS_OPERATOR' ? 'لوجستي' : '—') },
      { key: 'currency', label: 'العملة', render: (v) => v || '—' },
      { key: 'status', label: 'الحالة', render: (v, row) => badge(row.subscription_status || v || '—', (row.subscription_status === 'ACTIVE' || v === 'ACTIVE') ? 'green' : 'amber') },
      { key: 'actions', label: 'إجراء', render: (_, row) => el('button', { class: 'btn btn-ghost btn-small', onclick: () => showTenantDetails(row) }, 'تفاصيل') },
    ], rows));
  } catch (e) { body.replaceWith(errorState('تعذر التحميل: ' + e.message)); }
}

function openNewTenantModal(mainContainer) {
  const overlay = modal('🏢 تسجيل شركة جديدة', el('div', {}, []));
  const modalBody = overlay.querySelector('.modal-body');

  const form = el('form', { style: 'display:grid;gap:12px;direction:rtl' });

  const nameInput = el('input', {
    type: 'text',
    placeholder: 'اسم الشركة (مثال: أسطول الرياض السريع)',
    style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
    required: true
  });

  const phoneInput = el('input', {
    type: 'tel',
    placeholder: 'رقم هاتف المالك/المدير (مثال: 0501234567)',
    style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
    required: true
  });

  const passInput = el('input', {
    type: 'password',
    placeholder: 'كلمة المرور (8 أحرف على الأقل)',
    style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
    required: true
  });

  const typeSelect = el('select', {
    id: 'ncType',
    style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
    required: true
  }, [
    el('option', { value: 'LOGISTICS_OPERATOR' }, 'شركة لوجستية (مشغل أسطول مناديب)'),
    el('option', { value: 'DELIVERY_PLATFORM' }, 'منصة توصيل (Delivery Platform)'),
  ]);

  const marketSelect = el('select', {
    id: 'ncMarket',
    style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
  }, [
    el('option', { value: 'SA' }, '🇸🇦 المملكة العربية السعودية (SAR)'),
    el('option', { value: 'EG' }, '🇪🇬 جمهورية مصر العربية (EGP)'),
  ]);

  const planSelect = el('select', {
    id: 'ncPlan',
    style: 'width:100%;padding:8px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)',
  }, [
    el('option', { value: 'GROWTH' }, 'باقة النمو (GROWTH)'),
    el('option', { value: 'STARTER' }, 'الباقة الأساسية (STARTER)'),
    el('option', { value: 'SCALE' }, 'باقة التوسع (SCALE)'),
    el('option', { value: 'ENTERPRISE' }, 'باقة المؤسسات (ENTERPRISE)'),
  ]);

  const submitBtn = el('button', {
    type: 'submit',
    class: 'btn btn-primary',
    style: 'padding:10px;font-weight:700;margin-top:8px'
  }, 'إنشاء الشركة');

  form.append(
    el('label', { style: 'font-size:12px;font-weight:700' }, 'اسم الشركة:'),
    nameInput,
    el('label', { style: 'font-size:12px;font-weight:700' }, 'رقم هاتف المالك:'),
    phoneInput,
    el('label', { style: 'font-size:12px;font-weight:700' }, 'كلمة المرور:'),
    passInput,
    el('label', { style: 'font-size:12px;font-weight:700' }, 'نوع الحساب:'),
    typeSelect,
    el('label', { style: 'font-size:12px;font-weight:700' }, 'الدولة وسوق التشغيل:'),
    marketSelect,
    el('label', { style: 'font-size:12px;font-weight:700' }, 'باقة الاشتراك:'),
    planSelect,
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
      alert('تم إنشاء الشركة بنجاح!');
      overlay.close();
      loadTenants(mainContainer);
    } catch (err) {
      alert(err.message || 'فشل إنشاء الشركة');
      submitBtn.disabled = false;
      submitBtn.textContent = 'إنشاء الشركة';
    }
  };

  modalBody.append(form);
}
