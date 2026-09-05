// Vehicles & Fleet Maintenance — Frontend V2 (Screen 1 / 6)
import { api } from '../../shared/api/client.js';
import {
  el, loadingState, emptyState, errorState, modal, metricCard, badge, escapeHtml, showToast } from '../../shared/components/ui.js';
import { getLang } from '../../shared/i18n/i18n.js';

let activeFilter = 'ALL'; // 'ALL' | 'MOTORCYCLE' | 'CAR' | 'EXPIRING' | 'INACTIVE'
let cachedCouriers = null;

export async function loadVehicles(container) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';

  const headerActions = el('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, [
    el('button', {
      class: 'btn btn-ghost btn-small',
      onclick: () => loadVehicles(container)
    }, isAr ? 'تحديث ↻' : 'Refresh ↻'),
    el('button', {
      class: 'btn btn-primary btn-small',
      onclick: () => openAddVehicleModal(container)
    }, isAr ? '➕ إضافة مركبة جديدة' : '➕ Add New Vehicle'),
  ]);

  const header = el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'إدارة الأسطول والمركبات والعهد' : 'Fleet Vehicles & Asset Registry'),
      el('h1', { text: isAr ? 'المركبات والصيانة والتأمين' : 'Vehicles, Maintenance & Insurance' }),
    ]),
    headerActions,
  ]);

  const contentArea = el('div', { id: 'vehicles-content' });
  container.append(header, contentArea);

  await renderVehiclesContent(contentArea, container);
}

async function renderVehiclesContent(contentArea, mainContainer) {
  const isAr = getLang() === 'ar';
  contentArea.innerHTML = '';
  contentArea.append(loadingState(isAr ? 'جاري تحميل سجل المركبات والوثائق...' : 'Loading vehicle fleet and documents...'));

  try {
    // 1. Fetch vehicles (active and inactive)
    const vehicles = await api.get('/vehicles/?active_only=false');

    // 2. Fetch full details with documents for each vehicle
    const vehicleDetails = await Promise.all(
      vehicles.map((v) => api.get(`/vehicles/${v.id}`))
    );

    // 3. Fetch couriers for assignment lookups if not cached
    if (!cachedCouriers) {
      try {
        cachedCouriers = await api.get('/hr/couriers');
      } catch {
        cachedCouriers = [];
      }
    }

    renderVehiclesDashboard(contentArea, vehicleDetails, mainContainer);
  } catch (err) {
    contentArea.innerHTML = '';
    contentArea.append(errorState(err.message || (isAr ? 'فشل تحميل بيانات المركبات' : 'Failed to load vehicles'), () => renderVehiclesContent(contentArea, mainContainer)));
  }
}

function renderVehiclesDashboard(contentArea, vehicleDetails, mainContainer) {
  const isAr = getLang() === 'ar';
  contentArea.innerHTML = '';

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  // Analyze expiry alerts
  let totalVehicles = vehicleDetails.length;
  let activeVehicles = 0;
  let motorcycles = 0;
  let cars = 0;
  let expiredCount = 0;
  let expiringSoonCount = 0; // <= 30 days

  const enrichedVehicles = vehicleDetails.map(({ vehicle, documents }) => {
    if (vehicle.operational_status === 'ACTIVE') activeVehicles++;
    if (vehicle.vehicle_type === 'Motorcycle') motorcycles++;
    else cars++;

    const docAlerts = [];
    (documents || []).forEach((d) => {
      if (d.expiry_date) {
        const exp = new Date(d.expiry_date);
        const daysLeft = Math.ceil((exp - today) / (1000 * 60 * 60 * 24));
        if (daysLeft < 0) {
          expiredCount++;
          docAlerts.push({ type: d.document_type, status: 'EXPIRED', daysLeft, date: d.expiry_date });
        } else if (daysLeft <= 30) {
          expiringSoonCount++;
          docAlerts.push({ type: d.document_type, status: 'EXPIRING_SOON', daysLeft, date: d.expiry_date });
        } else {
          docAlerts.push({ type: d.document_type, status: 'VALID', daysLeft, date: d.expiry_date });
        }
      } else {
        docAlerts.push({ type: d.document_type, status: d.status || 'UNKNOWN', daysLeft: null, date: null });
      }
    });

    return { ...vehicle, documents: documents || [], docAlerts };
  });

  // 1. KPI Cards Bar
  const metricsGrid = el('div', { class: 'metrics-grid', style: 'margin-bottom:20px' }, [
    metricCard(totalVehicles, isAr ? 'إجمالي الأسطول' : 'Total Fleet', 'blue'),
    metricCard(activeVehicles, isAr ? 'مركبات نشطة' : 'Active Vehicles', 'green'),
    metricCard(`${motorcycles} 🛵 | ${cars} 🚗`, isAr ? 'دراجات / سيارات' : 'Bikes / Cars', 'purple'),
    metricCard(
      expiringSoonCount,
      isAr ? '⚠️ تنتهي خلال 30 يوماً' : '⚠️ Expiring in 30 Days',
      expiringSoonCount > 0 ? 'amber' : 'green',
      () => { activeFilter = 'EXPIRING'; renderVehiclesDashboard(contentArea, vehicleDetails, mainContainer); }
    ),
    metricCard(
      expiredCount,
      isAr ? '🚨 وثائق منتهية (غرامة!)' : '🚨 Expired (Fine Risk!)',
      expiredCount > 0 ? 'red' : 'green',
      () => { activeFilter = 'EXPIRED'; renderVehiclesDashboard(contentArea, vehicleDetails, mainContainer); }
    ),
  ]);

  // Proactive Warning Banner if any document is expired or expiring
  const alertBanner = (expiredCount > 0 || expiringSoonCount > 0)
    ? el('div', {
        class: 'card',
        style: `margin-bottom:16px;padding:12px 16px;border-radius:10px;display:flex;align-items:center;gap:12px;${
          expiredCount > 0
            ? 'background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.3);color:var(--red)'
            : 'background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.3);color:var(--amber)'
        }`
      }, [
        el('span', { style: 'font-size:24px' }, expiredCount > 0 ? '🚨' : '⚠️'),
        el('div', { style: 'flex:1' }, [
          el('b', { style: 'display:block;font-size:14px;margin-bottom:2px' },
            expiredCount > 0
              ? (isAr ? `تنبيه حرج: توجد ${expiredCount} وثيقة منتهية الصلاحية (استمارة / تأمين)! تجنب الغرامات المرورية وتوقف السائق فوراً.` : `Critical: ${expiredCount} expired documents (Registration/Insurance)! Avoid traffic fines and grounded riders.`)
              : (isAr ? `تنبيه استباقي: توجد ${expiringSoonCount} وثيقة تنتهي خلال 30 يوماً. باشر بالتجديد المبكر قبل فرض الغرامات.` : `Proactive Notice: ${expiringSoonCount} documents expiring within 30 days. Renew early to prevent penalties.`)
          ),
          el('span', { style: 'font-size:12px;opacity:0.85' },
            isAr ? 'اضغط على كارت أي مركبة لتسجيل الوثيقة المجددة أو إضافة وثيقة تأمين جديدة.' : 'Click on any vehicle to upload renewed documents or update insurance.'
          )
        ])
      ])
    : null;

  // 2. Filter Tabs
  const filters = [
    { id: 'ALL', label: isAr ? `الكل (${totalVehicles})` : `All (${totalVehicles})` },
    { id: 'MOTORCYCLE', label: isAr ? `دراجات (${motorcycles})` : `Bikes (${motorcycles})` },
    { id: 'CAR', label: isAr ? `سيارات (${cars})` : `Cars (${cars})` },
    { id: 'EXPIRING', label: isAr ? `تنبيهات التجديد (${expiringSoonCount})` : `Expiring Soon (${expiringSoonCount})` },
    { id: 'EXPIRED', label: isAr ? `منتهية (${expiredCount})` : `Expired (${expiredCount})` },
    { id: 'INACTIVE', label: isAr ? 'المعطلة / موقوفة' : 'Inactive' },
  ];

  const filterBar = el('div', { class: 'tabs', style: 'margin-bottom:16px;display:flex;gap:6px;overflow-x:auto' },
    filters.map(f => el('button', {
      class: `tab ${activeFilter === f.id ? 'active' : ''}`,
      onclick: () => { activeFilter = f.id; renderVehiclesDashboard(contentArea, vehicleDetails, mainContainer); }
    }, f.label))
  );

  // 3. Filtered Vehicle Cards
  const filtered = enrichedVehicles.filter(v => {
    if (activeFilter === 'MOTORCYCLE') return v.vehicle_type === 'Motorcycle';
    if (activeFilter === 'CAR') return v.vehicle_type !== 'Motorcycle';
    if (activeFilter === 'EXPIRING') return v.docAlerts.some(a => a.status === 'EXPIRING_SOON');
    if (activeFilter === 'EXPIRED') return v.docAlerts.some(a => a.status === 'EXPIRED');
    if (activeFilter === 'INACTIVE') return v.operational_status !== 'ACTIVE';
    return true;
  });

  const grid = el('div', {
    style: 'display:grid;grid-template-columns:repeat(auto-fill, minmax(350px, 1fr));gap:16px'
  });

  if (!filtered.length) {
    grid.append(emptyState(isAr ? 'لا توجد مركبات تطابق هذا الفلتر.' : 'No vehicles match this filter.'));
  } else {
    filtered.forEach(v => {
      grid.append(renderVehicleCard(v, isAr, mainContainer));
    });
  }

  contentArea.append(metricsGrid);
  if (alertBanner) contentArea.append(alertBanner);
  contentArea.append(filterBar, grid);
}

function renderVehicleCard(v, isAr, mainContainer) {
  const isBike = v.vehicle_type === 'Motorcycle';
  const hasExpired = v.docAlerts.some(a => a.status === 'EXPIRED');
  const hasExpiring = v.docAlerts.some(a => a.status === 'EXPIRING_SOON');

  let statusBadge;
  if (v.operational_status !== 'ACTIVE') {
    statusBadge = el('span', { class: 'badge badge-gray' }, isAr ? 'موقوفة' : 'Inactive');
  } else if (hasExpired) {
    statusBadge = el('span', { class: 'badge badge-red' }, isAr ? '🚨 غير مطابقة' : '🚨 Non-compliant');
  } else if (hasExpiring) {
    statusBadge = el('span', { class: 'badge badge-amber' }, isAr ? '⚠️ تجديد قريب' : '⚠️ Expiring soon');
  } else {
    statusBadge = el('span', { class: 'badge badge-green' }, isAr ? '🟢 مطابقة وجاهزة' : '🟢 Compliant');
  }

  const card = el('div', {
    class: 'card',
    style: `background:var(--card);border:1px solid ${hasExpired ? 'rgba(239,68,68,0.4)' : 'var(--border)'};border-radius:12px;padding:16px;display:flex;flex-direction:column;justify-content:space-between;gap:12px`
  }, [
    // Top Row
    el('div', {}, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px' }, [
        el('div', {}, [
          el('span', { style: 'font-size:20px;margin-inline-end:6px' }, isBike ? '🛵' : '🚗'),
          el('b', { style: 'font-size:16px;font-family:monospace;letter-spacing:1px' }, v.plate_number),
          el('div', { style: 'font-size:12px;color:var(--muted);margin-top:2px' },
            `${v.make || ''} ${v.model || ''} ${v.model_year ? `(${v.model_year})` : ''} • ${v.vehicle_type}`
          ),
        ]),
        statusBadge
      ]),

      // Documents Matrix
      el('div', { style: 'background:var(--surface2, #f8fafc);border-radius:8px;padding:10px;margin:10px 0;font-size:12px' }, [
        el('div', { style: 'font-weight:700;margin-bottom:6px;color:var(--ink);display:flex;justify-content:space-between' }, [
          el('span', {}, isAr ? 'حالة الوثائق والتأمين:' : 'Documents & Insurance:'),
          el('button', {
            class: 'btn btn-ghost btn-small',
            style: 'padding:2px 6px;font-size:11px',
            onclick: () => openAddDocumentModal(v, mainContainer)
          }, isAr ? '➕ وثيقة جديدة' : '➕ Add Doc')
        ]),
        v.documents.length
          ? el('div', { style: 'display:flex;flex-direction:column;gap:6px' },
              v.documents.map(d => renderDocumentRow(d, isAr))
            )
          : el('div', { style: 'color:var(--muted);font-size:11px' },
              isAr ? '⚠️ لا توجد وثائق مسجلة للمركبة (استمارة / تأمين).' : '⚠️ No documents recorded for this vehicle.'
            )
      ]),
    ]),

    // Actions Footer
    el('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;border-top:1px dashed var(--border);padding-top:10px' }, [
      el('button', {
        class: 'btn btn-small btn-primary',
        style: 'flex:1',
        onclick: () => openAssignRiderModal(v, mainContainer)
      }, isAr ? '🛵 إسناد لسائق' : '🛵 Assign Rider'),
      el('button', {
        class: 'btn btn-small btn-ghost',
        onclick: () => openEditVehicleModal(v, mainContainer)
      }, isAr ? '✏️ تعديل' : '✏️ Edit'),
      el('button', {
        class: 'btn btn-small btn-ghost',
        style: v.operational_status === 'ACTIVE' ? 'color:var(--red)' : 'color:var(--green)',
        onclick: () => toggleVehicleStatus(v, mainContainer)
      }, v.operational_status === 'ACTIVE' ? (isAr ? '🚫 إيقاف' : '🚫 Deactivate') : (isAr ? '🟢 تنشيط' : '🟢 Activate')),
    ])
  ]);

  return card;
}

function renderDocumentRow(d, isAr) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  let docBadge;
  if (!d.expiry_date) {
    docBadge = el('span', { class: 'badge badge-gray' }, isAr ? 'بدون تاريخ' : 'No Date');
  } else {
    const exp = new Date(d.expiry_date);
    const days = Math.ceil((exp - today) / (1000 * 60 * 60 * 24));
    if (days < 0) {
      docBadge = el('span', { class: 'badge badge-red' }, isAr ? `منتهية (${Math.abs(days)} يوم)` : `Expired (${Math.abs(days)}d)`);
    } else if (days <= 30) {
      docBadge = el('span', { class: 'badge badge-amber' }, isAr ? `باقي ${days} يوم` : `${days}d left`);
    } else {
      docBadge = el('span', { class: 'badge badge-green' }, isAr ? `صالحة (${d.expiry_date})` : `Valid (${d.expiry_date})`);
    }
  }

  const docTypeLabels = {
    REGISTRATION: isAr ? 'الاستمارة' : 'Registration',
    INSURANCE: isAr ? 'التأمين' : 'Insurance',
    INSPECTION: isAr ? 'الفحص الدوري' : 'Inspection',
    LICENSE: isAr ? 'رخصة السير' : 'License',
  };

  return el('div', { style: 'display:flex;justify-content:space-between;align-items:center;font-size:11px' }, [
    el('span', { style: 'font-weight:600' }, docTypeLabels[d.document_type] || d.document_type),
    docBadge
  ]);
}

// ── Modals: Add Vehicle, Edit, Assign Rider, Add Document ──

function openAddVehicleModal(mainContainer) {
  const isAr = getLang() === 'ar';
  const overlay = modal(
    isAr ? '➕ إضافة مركبة جديدة للأسطول' : '➕ Add New Vehicle to Fleet',
    el('form', { id: 'add-vehicle-form', style: 'display:flex;flex-direction:column;gap:12px' }, [
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'رقم اللوحة (مثال: أ ب ج 1234):' : 'Plate Number:'),
        el('input', { class: 'input', name: 'plate_number', required: true, placeholder: isAr ? 'مثال: أ ب ج 1234' : 'e.g. ABC 1234', style: 'width:100%' }),
      ]),
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
        el('div', {}, [
          el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'نوع المركبة:' : 'Vehicle Type:'),
          el('select', { class: 'input', name: 'vehicle_type', style: 'width:100%' }, [
            el('option', { value: 'Motorcycle' }, isAr ? 'دراجة نارية 🛵' : 'Motorcycle 🛵'),
            el('option', { value: 'Car' }, isAr ? 'سيارة 🚗' : 'Car 🚗'),
            el('option', { value: 'Van' }, isAr ? 'فان / شاحنة خفيفة 🚐' : 'Van 🚐'),
          ])
        ]),
        el('div', {}, [
          el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'سنة الصنع (الموديل):' : 'Model Year:'),
          el('input', { class: 'input', name: 'model_year', type: 'number', placeholder: '2024', style: 'width:100%' }),
        ])
      ]),
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
        el('div', {}, [
          el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'الشركة الصانعة:' : 'Make:'),
          el('input', { class: 'input', name: 'make', placeholder: 'Honda / Toyota / Bajaj', style: 'width:100%' }),
        ]),
        el('div', {}, [
          el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'طراز المركبة:' : 'Model:'),
          el('input', { class: 'input', name: 'model', placeholder: 'Pulsar / Yaris', style: 'width:100%' }),
        ])
      ]),
      el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:12px' }, [
        el('button', {
          type: 'button',
          class: 'btn btn-ghost',
          onclick: () => overlay.remove()
        }, isAr ? 'إلغاء' : 'Cancel'),
        el('button', {
          type: 'submit',
          class: 'btn btn-primary',
          id: 'btn-submit-vehicle'
        }, isAr ? 'حفظ المركبة' : 'Save Vehicle')
      ])
    ])
  );

  const form = overlay.querySelector('#add-vehicle-form');
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = form.querySelector('#btn-submit-vehicle');
    btn.disabled = true;
    btn.textContent = isAr ? 'جاري الحفظ...' : 'Saving...';

    const formData = new FormData(form);
    const payload = {
      plate_number: formData.get('plate_number'),
      vehicle_type: formData.get('vehicle_type'),
      make: formData.get('make') || null,
      model: formData.get('model') || null,
      model_year: formData.get('model_year') ? Number(formData.get('model_year')) : null,
      market_code: 'SA',
      is_exclusive: true
    };

    try {
      await api.post('/vehicles/', payload);
      overlay.remove();
      await loadVehicles(mainContainer);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = isAr ? 'حفظ المركبة' : 'Save Vehicle';
      showToast(err.message || (isAr ? 'فشل حفظ المركبة' : 'Failed to save vehicle'), 'error');
    }
  };
}

function openEditVehicleModal(vehicle, mainContainer) {
  const isAr = getLang() === 'ar';
  const overlay = modal(
    isAr ? `✏️ تعديل بيانات المركبة (${vehicle.plate_number})` : `✏️ Edit Vehicle (${vehicle.plate_number})`,
    el('form', { id: 'edit-vehicle-form', style: 'display:flex;flex-direction:column;gap:12px' }, [
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'رقم اللوحة:' : 'Plate Number:'),
        el('input', { class: 'input', name: 'plate_number', value: vehicle.plate_number, required: true, style: 'width:100%' }),
      ]),
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
        el('div', {}, [
          el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'نوع المركبة:' : 'Vehicle Type:'),
          el('select', { class: 'input', name: 'vehicle_type', style: 'width:100%' }, [
            el('option', { value: 'Motorcycle', selected: vehicle.vehicle_type === 'Motorcycle' }, isAr ? 'دراجة نارية 🛵' : 'Motorcycle 🛵'),
            el('option', { value: 'Car', selected: vehicle.vehicle_type === 'Car' }, isAr ? 'سيارة 🚗' : 'Car 🚗'),
            el('option', { value: 'Van', selected: vehicle.vehicle_type === 'Van' }, isAr ? 'فان 🚐' : 'Van 🚐'),
          ])
        ]),
        el('div', {}, [
          el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'سنة الصنع:' : 'Model Year:'),
          el('input', { class: 'input', name: 'model_year', type: 'number', value: vehicle.model_year || '', style: 'width:100%' }),
        ])
      ]),
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
        el('div', {}, [
          el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'الشركة الصانعة:' : 'Make:'),
          el('input', { class: 'input', name: 'make', value: vehicle.make || '', style: 'width:100%' }),
        ]),
        el('div', {}, [
          el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'الطراز:' : 'Model:'),
          el('input', { class: 'input', name: 'model', value: vehicle.model || '', style: 'width:100%' }),
        ])
      ]),
      el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:12px' }, [
        el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => overlay.remove() }, isAr ? 'إلغاء' : 'Cancel'),
        el('button', { type: 'submit', class: 'btn btn-primary', id: 'btn-update-vehicle' }, isAr ? 'تحديث البيانات' : 'Update')
      ])
    ])
  );

  const form = overlay.querySelector('#edit-vehicle-form');
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = form.querySelector('#btn-update-vehicle');
    btn.disabled = true;
    btn.textContent = isAr ? 'جاري التحديث...' : 'Updating...';

    const formData = new FormData(form);
    const payload = {
      plate_number: formData.get('plate_number'),
      vehicle_type: formData.get('vehicle_type'),
      make: formData.get('make') || null,
      model: formData.get('model') || null,
      model_year: formData.get('model_year') ? Number(formData.get('model_year')) : null,
    };

    try {
      await api.patch(`/vehicles/${vehicle.id}`, payload);
      overlay.remove();
      await loadVehicles(mainContainer);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = isAr ? 'تحديث البيانات' : 'Update';
      showToast(err.message || (isAr ? 'فشل التحديث' : 'Failed to update vehicle'), 'error');
    }
  };
}

function openAddDocumentModal(vehicle, mainContainer) {
  const isAr = getLang() === 'ar';
  const overlay = modal(
    isAr ? `📄 إضافة وثيقة للمركبة (${vehicle.plate_number})` : `📄 Add Vehicle Document (${vehicle.plate_number})`,
    el('form', { id: 'add-doc-form', style: 'display:flex;flex-direction:column;gap:12px' }, [
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'نوع الوثيقة:' : 'Document Type:'),
        el('select', { class: 'input', name: 'document_type', style: 'width:100%' }, [
          el('option', { value: 'REGISTRATION' }, isAr ? 'استمارة رخصة السير (REGISTRATION)' : 'Registration (Istimara)'),
          el('option', { value: 'INSURANCE' }, isAr ? 'وثيقة التأمين الشامل / ضد الغير (INSURANCE)' : 'Insurance Policy'),
          el('option', { value: 'INSPECTION' }, isAr ? 'شهادة الفحص الدوري (INSPECTION)' : 'Periodic Inspection'),
          el('option', { value: 'LICENSE' }, isAr ? 'رخصة سير الدراجة / المركبة (LICENSE)' : 'Vehicle License'),
        ])
      ]),
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'رقم الوثيقة / بوليصة التأمين:' : 'Document / Policy Number:'),
        el('input', { class: 'input', name: 'document_number', placeholder: 'e.g. POL-998822', style: 'width:100%' }),
      ]),
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'تاريخ انتهاء الصلاحية (مهم للتنبيه الاستباقي):' : 'Expiry Date (Crucial for Proactive Alert):'),
        el('input', { class: 'input', name: 'expiry_date', type: 'date', required: true, style: 'width:100%' }),
      ]),
      el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:12px' }, [
        el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => overlay.remove() }, isAr ? 'إلغاء' : 'Cancel'),
        el('button', { type: 'submit', class: 'btn btn-primary', id: 'btn-save-doc' }, isAr ? 'تسجيل الوثيقة' : 'Save Document')
      ])
    ])
  );

  const form = overlay.querySelector('#add-doc-form');
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = form.querySelector('#btn-save-doc');
    btn.disabled = true;
    btn.textContent = isAr ? 'جاري الحفظ...' : 'Saving...';

    const formData = new FormData(form);
    const payload = {
      document_type: formData.get('document_type'),
      document_number: formData.get('document_number') || null,
      expiry_date: formData.get('expiry_date') || null,
      status: 'VALID'
    };

    try {
      await api.post(`/vehicles/${vehicle.id}/documents`, payload);
      overlay.remove();
      await loadVehicles(mainContainer);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = isAr ? 'تسجيل الوثيقة' : 'Save Document';
      showToast(err.message || (isAr ? 'فشل حفظ الوثيقة' : 'Failed to save document'), 'error');
    }
  };
}

function openAssignRiderModal(vehicle, mainContainer) {
  const isAr = getLang() === 'ar';
  const overlay = modal(
    isAr ? `🛵 إسناد المركبة (${vehicle.plate_number}) لسائق` : `🛵 Assign Vehicle (${vehicle.plate_number}) to Courier`,
    el('form', { id: 'assign-rider-form', style: 'display:flex;flex-direction:column;gap:12px' }, [
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'اختر السائق:' : 'Select Courier:'),
        el('select', { class: 'input', name: 'courier_id', required: true, style: 'width:100%' }, [
          el('option', { value: '' }, isAr ? '— اختر سائقاً من الأسطول —' : '— Select a courier —'),
          ...(cachedCouriers || []).map(c => el('option', { value: String(c.id) }, `${c.name} (${c.phone || 'بدون جوال'})`))
        ])
      ]),
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'ساري من تاريخ:' : 'Effective From:'),
        el('input', {
          class: 'input',
          name: 'effective_from',
          type: 'date',
          value: new Date().toISOString().slice(0, 10),
          required: true,
          style: 'width:100%'
        }),
      ]),
      el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:12px' }, [
        el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => overlay.remove() }, isAr ? 'إلغاء' : 'Cancel'),
        el('button', { type: 'submit', class: 'btn btn-primary', id: 'btn-save-assign' }, isAr ? 'تأكيد الإسناد' : 'Confirm Assignment')
      ])
    ])
  );

  const form = overlay.querySelector('#assign-rider-form');
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = form.querySelector('#btn-save-assign');
    btn.disabled = true;
    btn.textContent = isAr ? 'جاري الإسناد...' : 'Assigning...';

    const formData = new FormData(form);
    const courierId = Number(formData.get('courier_id'));
    const effectiveFrom = formData.get('effective_from');

    try {
      await api.post(`/vehicles/assignments?vehicle_id=${vehicle.id}`, {
        courier_id: courierId,
        effective_from: effectiveFrom,
        is_primary: true
      });
      overlay.remove();
      showToast(isAr ? 'تم إسناد المركبة للسائق بنجاح!' : 'Vehicle assigned to courier successfully!', 'success');
      await loadVehicles(mainContainer);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = isAr ? 'تأكيد الإسناد' : 'Confirm Assignment';
      showToast(err.message || (isAr ? 'فشل إسناد المركبة' : 'Failed to assign vehicle'), 'error');
    }
  };
}

async function toggleVehicleStatus(vehicle, mainContainer) {
  const isAr = getLang() === 'ar';
  const isCurrentlyActive = vehicle.operational_status === 'ACTIVE';
  const confirmMsg = isCurrentlyActive
    ? (isAr ? `هل تريد تعطيل المركبة (${vehicle.plate_number})؟` : `Deactivate vehicle (${vehicle.plate_number})?`)
    : (isAr ? `هل تريد إعادة تنشيط المركبة (${vehicle.plate_number})؟` : `Reactivate vehicle (${vehicle.plate_number})?`);

  if (!confirm(confirmMsg)) return;

  try {
    if (isCurrentlyActive) {
      await api.delete(`/vehicles/${vehicle.id}`);
    } else {
      await api.patch(`/vehicles/${vehicle.id}`, { operational_status: 'ACTIVE' });
    }
    await loadVehicles(mainContainer);
  } catch (err) {
    showToast(err.message || (isAr ? 'فشل تغيير حالة المركبة' : 'Failed to change vehicle status'), 'error');
  }
}
