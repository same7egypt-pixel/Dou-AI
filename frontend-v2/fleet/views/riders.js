// Riders screen — list/search/filter/create/edit/open Rider 360 with Driver Taxonomy & Readiness
import { api } from '../../shared/api/client.js';
import { appStore, isDeliveryPlatform } from '../../shared/state/store.js';
import { el, loadingState, emptyState, errorState, table, button, escapeHtml, modal, formRow, inputField, selectField, badge, searchableSelect } from '../../shared/components/ui.js';
import { go } from '../shell.js';
import { loadRider360 } from './rider360.js';
import { openBulkImportModal, openImportHistoryModal } from './imports.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

export async function loadRiders(container) {
  const isAr = getLang() === 'ar';
  const role = appStore.get().role || localStorage.getItem('dou_role_v2') || 'COMPANY_ADMIN';
  const canManageRiders = ['COMPANY', 'COMPANY_ADMIN', 'OPERATIONS', 'HR', 'DOU_ADMIN', 'DOU_OPS'].includes(role);
  
  const actionButtons = [];
  if (canManageRiders) {
    actionButtons.push(
      el('button', {
        class: 'btn btn-primary btn-blue',
        id: 'btn-add-rider',
        onclick: () => openAddRider(container)
      }, isAr ? '+ إضافة سائق' : '+ Add Driver'),
      el('button', {
        class: 'btn btn-ghost',
        id: 'btn-vehicles-fleet',
        style: 'font-weight:700;color:var(--primary)',
        onclick: () => openVehiclesFleetModal(container)
      }, isAr ? '🚗 أسطول المركبات' : '🚗 Fleet Vehicles'),
      el('button', {
        class: 'btn btn-ghost',
        id: 'btn-bulk-import',
        style: 'font-weight:700',
        onclick: () => openBulkImportModal({ onRidersImported: () => loadRiderList(container) })
      }, isAr ? 'استيراد جماعي' : 'Bulk Import'),
      el('button', {
        class: 'btn btn-ghost',
        onclick: () => downloadRiderTemplate()
      }, isAr ? 'تنزيل القالب' : 'Download Template'),
      el('button', {
        class: 'btn btn-ghost',
        onclick: () => openImportHistoryModal()
      }, isAr ? 'سجل الاستيراد' : 'Import History'),
      // The rider app has a "company messages" screen with nothing able to
      // write to it: sending existed only on the retired dashboard, so the
      // riders' inbox was permanently empty.
      el('button', {
        class: 'btn btn-ghost',
        id: 'btn-broadcast',
        onclick: () => openBroadcastModal()
      }, isAr ? '📢 رسالة للمناديب' : '📢 Message riders')
    );
  }

  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'إدارة القوى العاملة والمناديب' : 'Workforce & Rider Management'),
      el('h1', { text: isAr ? 'السائقون' : 'Drivers & Workforce' })
    ]),
    el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' }, actionButtons),
  ]));

  const filters = el('div', { class: 'filters', style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:16px' }, [
    el('input', {
      id: 'rider-search',
      placeholder: isAr ? '🔍 بحث بالاسم أو الجوال...' : '🔍 Search by name or phone...',
      style: 'min-width:240px;padding:8px 12px;border:1px solid var(--border);border-radius:8px',
      oninput: debounce(() => loadRiderList(container), 300)
    }),
    el('select', {
      id: 'rider-type-filter',
      style: 'padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text)',
      onchange: () => loadRiderList(container)
    }, [
      el('option', { value: '' }, isAr ? '🏷️ كل أنواع السائقين' : '🏷️ All Driver Types'),
      el('option', { value: 'COMPANY' }, isAr ? '🏢 كفالة شركة (Sponsored)' : '🏢 Company Sponsored'),
      el('option', { value: 'FREELANCER' }, isAr ? '🛵 فريلانسر (Freelancer)' : '🛵 Freelancer'),
      el('option', { value: 'OPERATOR' }, isAr ? '🤝 شركة مشغلة (3PL)' : '🤝 3PL Operator'),
    ]),
    el('select', {
      id: 'rider-status-filter',
      style: 'padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text)',
      onchange: () => loadRiderList(container)
    }, [
      el('option', { value: '' }, isAr ? 'كل الحالات التشغيلية' : 'All Operational Statuses'),
      el('option', { value: 'ACTIVE' }, isAr ? '🟢 نشط' : '🟢 Active'),
      el('option', { value: 'INACTIVE' }, isAr ? '⚪ غير نشط' : '⚪ Inactive'),
    ]),
  ]);
  container.append(filters);

  const list = el('div', {}, [loadingState(isAr ? 'جاري تحميل قائمة السائقين...' : 'Loading driver list...')]);
  container.append(list);
  loadRiderList(container);
}

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function downloadRiderTemplate() {
  const headers = 'name,mobile,national_id_or_iqama,nationality,city,branch,courier_type,base_salary,rider_rate_per_order,vehicle_type,vehicle_plate\n';
  const example = 'محمد علي,966501234567,2450000000,SA,Riyadh,Riyadh North,COMPANY,3000,5,Motorcycle,ABC 1234\nأحمد سعيد,966507654321,2460000000,EG,Riyadh,Riyadh South,FREELANCER,0,15,Car,XYZ 5678\n';
  const blob = new Blob(['\ufeff' + headers + example], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'riders_import_template.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

async function loadRiderList(container) {
  const isAr = getLang() === 'ar';
  const list = container.querySelector('.state-loading')?.parentElement || container.lastElementChild;
  const search = document.getElementById('rider-search')?.value || '';
  const typeFilter = document.getElementById('rider-type-filter')?.value || '';
  const status = document.getElementById('rider-status-filter')?.value || '';
  const activeOperatorId = appStore.get().activeOperatorId;

  try {
    const params = new URLSearchParams({ page: 1, page_size: 50 });
    if (search) params.set('search', search);
    if (status) params.set('employment_status', status);
    if (typeFilter) params.set('courier_type', typeFilter);
    if (activeOperatorId) params.set('operator_id', activeOperatorId);
    
    const data = await api.get(`/fleet/couriers/page?${params}`);
    const rows = data.rows || [];

    if (!rows.length) {
      list.replaceWith(emptyState(isAr ? 'لا يوجد سائقون مطابقة لمعايير البحث الحالية.' : 'No drivers match the current search filters.'));
      return;
    }

    const columns = [
      { key: 'name', label: isAr ? 'السائق' : 'Driver', render: (v, r) => el('div', {}, [
        el('b', { style: 'display:block;color:var(--text)' }, v || '—'),
        el('small', { style: 'color:var(--muted);font-size:11px' }, r.phone || '')
      ]) },
      { key: 'courier_type', label: isAr ? 'نوع الانتماء' : 'Employment Type', render: (v) => {
        if (!v) return el('span', { class: 'badge badge-gray' }, '—');
        const type = String(v).toUpperCase();
        const badgeColor = type.includes('FREE') ? 'green' : (type.includes('OP') ? 'amber' : 'blue');
        const label = type.includes('FREE') 
          ? (isAr ? '🛵 فريلانسر' : '🛵 Freelancer') 
          : (type.includes('OP') ? (isAr ? '🤝 شركة 3PL' : '🤝 3PL Operator') : (isAr ? '🏢 كفالة شركة' : '🏢 Company Sponsored'));
        return el('span', { class: `badge badge-${badgeColor}` }, label);
      }},
      { key: 'readiness', label: isAr ? 'الجاهزية التشغيلية' : 'Operational Readiness', render: (_, r) => {
        const isReady = r.documents_valid && r.vehicle_plate;
        return el('span', {
          class: `badge badge-${isReady ? 'green' : 'amber'}`,
          style: 'cursor:pointer',
          onclick: () => window.openRider360(r.id)
        }, isReady ? (isAr ? 'جاهز للعمل ✅' : 'Operationally Ready ✅') : (isAr ? 'مستندات/مركبة ⚠️' : 'Docs/Vehicle Pending ⚠️'));
      }},
      { key: 'employment_status', label: isAr ? 'الحالة' : 'Status', render: (v) => el('span', { class: `badge badge-${v === 'ACTIVE' ? 'green' : 'gray'}` }, v === 'ACTIVE' ? (isAr ? 'نشط' : 'Active') : (isAr ? 'موقوف' : 'Suspended')) },
    ];

    columns.push({
      key: 'actions',
      label: isAr ? 'إجراءات التحكم' : 'Actions',
      render: (_, row) => el('div', { style: 'display:flex;gap:4px;flex-wrap:wrap' }, [
        el('button', {
          class: 'btn btn-ghost btn-small',
          style: 'padding:4px 8px;font-size:11.5px',
          onclick: () => window.openRider360(row.id)
        }, isAr ? '👁️ ملف 360' : '👁️ Profile 360'),
        el('button', {
          class: 'btn btn-ghost btn-small',
          style: 'padding:4px 8px;font-size:11.5px;color:var(--primary);border-color:rgba(37,99,235,0.2)',
          onclick: () => openEditRiderModal(row, () => loadRiderList(container))
        }, isAr ? '✏️ تعديل' : '✏️ Edit'),
        el('button', {
          class: 'btn btn-ghost btn-small',
          style: 'padding:4px 8px;font-size:11.5px;color:var(--red);border-color:rgba(220,38,38,0.2)',
          onclick: async () => {
            if (!confirm(isAr ? `هل تريد بالتأكيد حذف / تعطيل السائق (${row.name})؟` : `Are you sure you want to suspend / delete driver (${row.name})?`)) return;
            try {
              await api.delete(`/fleet/couriers/${row.id}`);
              alert(isAr ? '✅ تم حذف / تعطيل السائق بنجاح.' : '✅ Driver suspended/deleted successfully.');
              loadRiderList(container);
            } catch (err) {
              alert((isAr ? '❌ تعذر الحذف: ' : '❌ Failed to delete: ') + err.message);
            }
          }
        }, isAr ? '🗑️ حذف' : '🗑️ Delete'),
      ])
    });

    list.replaceWith(table(columns, rows));
  } catch (e) {
    list.replaceWith(errorState((isAr ? 'تعذر تحميل السائقين: ' : 'Failed to load drivers: ') + e.message, () => loadRiderList(container)));
  }
}

async function openAddRider(container) {
  try {
    const [structure, allSupervisors] = await Promise.all([
      api.get('/hr/contract-structure').catch(() => []),
      api.get('/hr/supervisors').catch(() => []),
    ]);
    const contracts = structure || [];

    // Cascading state
    let selectedContract = contracts[0] || null;
    let availableBranches = selectedContract?.branches || [];
    let selectedBranch = availableBranches[0] || null;
    let availableSupervisors = selectedBranch?.supervisors?.length ? selectedBranch.supervisors : (allSupervisors || []);

    const hierarchySummary = el('div', {
      id: 'hierarchy-summary',
      style: 'background:rgba(37,99,235,0.08);border:1px solid rgba(37,99,235,0.2);border-radius:8px;padding:8px 12px;font-size:12px;color:var(--text);margin-bottom:12px'
    });

    function updateHierarchySummary() {
      const ctName = selectedContract?.name || 'العقد الرئيسي';
      const brCity = selectedBranch?.city || 'فرع الرياض';
      const supVal = document.getElementById('ar-supervisor')?.value;
      const supObj = availableSupervisors.find(s => String(s.id) === supVal);
      const supName = supObj ? supObj.name : 'بدون مشرف';
      hierarchySummary.innerHTML = `🏢 <b>التسلسل الهرمي:</b> المندوب ➔ المشرف: <b>${supName}</b> ➔ الفرع: <b>${brCity}</b> ➔ العقد: <b>${ctName}</b>`;
    }

    const contractSelect = el('select', {
      id: 'ar-contract',
      style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text)',
      onchange: (e) => {
        selectedContract = contracts.find(c => String(c.id) === e.target.value) || null;
        availableBranches = selectedContract?.branches || [];
        selectedBranch = availableBranches[0] || null;
        updateBranchSelect();
        updateSupervisorSelect();
        updateHierarchySummary();
      }
    }, contracts.map(c => el('option', { value: String(c.id) }, c.name)));

    const branchSelect = el('select', {
      id: 'ar-branch',
      style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text)',
      onchange: (e) => {
        selectedBranch = availableBranches.find(b => String(b.id) === e.target.value) || null;
        updateSupervisorSelect();
        updateHierarchySummary();
      }
    });

    const supervisorSelect = el('select', {
      id: 'ar-supervisor',
      style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text)',
      onchange: () => updateHierarchySummary()
    });

    function updateBranchSelect() {
      branchSelect.innerHTML = '';
      if (!availableBranches.length) {
        branchSelect.append(el('option', { value: '1' }, 'فرع الرياض'));
        return;
      }
      availableBranches.forEach(b => {
        branchSelect.append(el('option', { value: String(b.id) }, `فرع ${b.city || b.id}`));
      });
    }

    function updateSupervisorSelect() {
      supervisorSelect.innerHTML = '';
      supervisorSelect.append(el('option', { value: '' }, 'بدون مشرف'));
      availableSupervisors = (selectedBranch?.supervisors?.length) ? selectedBranch.supervisors : (allSupervisors || []);
      availableSupervisors.forEach(s => {
        supervisorSelect.append(el('option', { value: String(s.id) }, s.name));
      });
    }

    updateBranchSelect();
    updateSupervisorSelect();
    setTimeout(updateHierarchySummary, 50);

    let m = null;
    const content = el('form', { id: 'add-rider-form', onsubmit: async (e) => {
      e.preventDefault();
      const name = document.getElementById('ar-name').value.trim();
      const phone = document.getElementById('ar-phone').value.trim();
      const password = document.getElementById('ar-password').value || 'Password123!';
      const nationalId = document.getElementById('ar-national-id').value.trim();
      const courierType = document.getElementById('ar-type').value;
      const salary = parseFloat(document.getElementById('ar-salary').value) || 0;
      const rate = parseFloat(document.getElementById('ar-rate').value) || 0;
      const vehiclePlate = document.getElementById('ar-plate').value.trim();
      const vehicleType = document.getElementById('ar-vehicle-type').value;
      const contractId = document.getElementById('ar-contract').value;
      const branchId = document.getElementById('ar-branch').value;
      const supervisorId = document.getElementById('ar-supervisor').value;

      if (!name || !phone) return alert('الاسم والجوال مطلوبان.');
      if (!contractId || !branchId || !selectedBranch) {
        return alert('اختر العقد وفرع التشغيل قبل إضافة السائق.');
      }

      try {
        await api.post('/fleet/couriers', {
          name, phone, password,
          national_id_or_iqama: nationalId || undefined,
          courier_type: courierType,
          base_salary: salary,
          per_delivery_rate: rate,
          vehicle_plate: vehiclePlate || undefined,
          vehicle_type: vehicleType,
          contract_id: parseInt(contractId),
          contract_branch_id: parseInt(branchId),
          supervisor_id: supervisorId ? parseInt(supervisorId) : undefined,
          country: 'SA',
          city_id: selectedBranch?.city_id || 1,
        });
        alert('✅ أُضيف السائق بنجاح وتم ربطه بالهيكل التشغيلي.');
        m.close();
        loadRiderList(container);
      } catch (err) {
        alert('❌ فشل إضافة السائق: ' + err.message);
      }
    }}, [
      hierarchySummary,
      el('div', { style: 'display:grid;grid-template-columns:repeat(3, 1fr);gap:10px;margin-bottom:12px;background:var(--bg);padding:10px;border-radius:8px;border:1px solid var(--border)' }, [
        el('div', {}, [
          el('label', { style: 'display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:3px' }, '1️⃣ العقد التجاري: *'),
          contractSelect
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:3px' }, '2️⃣ المدينة / الفرع: *'),
          branchSelect
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:3px' }, '3️⃣ المشرف المسؤول:'),
          supervisorSelect
        ]),
      ]),
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px' }, [
        inputField('ar-name', 'اسم السائق الثلاثي', { required: true }),
        inputField('ar-phone', 'رقم الجوال (9665xxxxxxxx)', { required: true }),
        inputField('ar-password', 'كلمة المرور الابتدائية', { type: 'password', value: 'Password123!' }),
        inputField('ar-national-id', 'رقم الهوية الوطنية / الإقامة'),
        selectField('ar-type', 'نوع السائق / الانتماء', [
          { value: 'COMPANY', label: '🏢 كفالة شركة (Sponsored)' },
          { value: 'FREELANCER', label: '🛵 فريلانسر (Freelancer)' },
          { value: '3PL_OPERATOR', label: '🤝 شركة مشغلة (3PL)' }
        ]),
        inputField('ar-salary', 'الراتب الأساسي (ر.س)', { type: 'number', placeholder: '3000' }),
        inputField('ar-rate', 'أجر التوصيل لكل طلب (ر.س)', { type: 'number', placeholder: '5' }),
        inputField('ar-plate', 'لوحة المركبة (إن وجدت)', { placeholder: 'أ ب ج 1234' }),
        selectField('ar-vehicle-type', 'نوع المركبة', [
          { value: 'Motorcycle', label: 'دباب / دراجة نارية' },
          { value: 'Car', label: 'سيارة صغيرة' },
          { value: 'Van', label: 'فان بضائع' }
        ]),
      ]),
      el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:16px' }, [
        el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.close() }, 'إلغاء'),
        el('button', { type: 'submit', class: 'btn btn-primary' }, 'حفظ وإضافة السائق')
      ])
    ]);

    m = modal('➕ إضافة سائق جديد وربطه بالهيكل التشغيلي', content);
  } catch (err) {
    alert('تعذر فتح نموذج الإضافة: ' + err.message);
  }
}

async function openEditRiderModal(courier, onUpdated) {
  try {
    const [structure, allSupervisors, fullProfile] = await Promise.all([
      api.get('/hr/contract-structure').catch(() => []),
      api.get('/hr/supervisors').catch(() => []),
      api.get(`/fleet/couriers/${courier.id}`).catch(() => courier),
    ]);
    const contracts = structure || [];
    const p = fullProfile || courier;

    const content = el('form', { style: 'display:grid;gap:12px;direction:rtl' }, [
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'اسم السائق الثلاثي: *'),
          el('input', { id: 'er-name', value: p.name || '', required: true, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'رقم الجوال: *'),
          el('input', { id: 'er-phone', value: p.phone || '', required: true, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
        ]),
      ]),
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'رقم الهوية الوطنية / الإقامة:'),
          el('input', { id: 'er-iqama', value: p.iqama_number || p.national_id_or_iqama || '', placeholder: '10xxxxxxxx / 20xxxxxxxx', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'الآيبان البنكي (IBAN):'),
          el('input', { id: 'er-iban', value: p.bank_iban || '', placeholder: 'SA0000000000000000000000', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
        ]),
      ]),
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'الراتب الأساسي (ر.س):'),
          el('input', { type: 'number', id: 'er-salary', value: p.base_salary || 0, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'أجر التوصيل لكل طلب (ر.س):'),
          el('input', { type: 'number', step: '0.5', id: 'er-per-order', value: p.per_delivery_rate || 0, style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
        ]),
      ]),
      el('div', { style: 'display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px' }, [
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'الحالة التشغيلية:'),
          el('select', { id: 'er-status', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' }, [
            el('option', { value: 'ACTIVE', selected: p.employment_status === 'ACTIVE' }, '🟢 نشط ومفعل'),
            el('option', { value: 'SUSPENDED', selected: p.employment_status === 'SUSPENDED' }, '🔴 موقوف مؤقتاً'),
            el('option', { value: 'INACTIVE', selected: p.employment_status === 'INACTIVE' }, '⚪ غير نشط')
          ])
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'رقم لوحة المركبة:'),
          el('input', { id: 'er-plate', value: p.vehicle_plate || '', placeholder: 'أ ب ج 1234', style: 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px' })
        ]),
        el('div', {}, [
          el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, 'المشرف المسؤول:'),
          searchableSelect({
            id: 'er-supervisor',
            placeholder: '🔍 ابحث عن المشرف...',
            value: p.supervisor_id ? String(p.supervisor_id) : '',
            options: [
              { value: '', label: 'بدون مشرف' },
              ...allSupervisors.map(s => ({
                value: String(s.id),
                label: s.name,
                sublabel: s.phone ? `📱 ${s.phone}` : ''
              }))
            ]
          })
        ]),
      ]),
      el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:14px;padding-top:12px;border-top:1px solid var(--border)' }, [
        el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
        el('button', { type: 'submit', class: 'btn btn-primary' }, '💾 حفظ التعديلات')
      ])
    ]);

    const m = modal(`✏️ تعديل بيانات السائق: ${p.name}`, content);

    content.onsubmit = async (e) => {
      e.preventDefault();
      const payload = {
        name: document.getElementById('er-name').value.trim(),
        phone: document.getElementById('er-phone').value.trim(),
        national_id_or_iqama: document.getElementById('er-iqama').value.trim(),
        bank_iban: document.getElementById('er-iban').value.trim(),
        base_salary: parseFloat(document.getElementById('er-salary').value || 0),
        per_delivery_rate: parseFloat(document.getElementById('er-per-order').value || 0),
        employment_status: document.getElementById('er-status').value,
        vehicle_plate: document.getElementById('er-plate').value.trim(),
        supervisor_id: document.getElementById('er-supervisor').value ? Number(document.getElementById('er-supervisor').value) : null,
      };

      try {
        await api.patch(`/fleet/couriers/${courier.id}`, payload);
        alert('✅ تم تحديث بيانات السائق بنجاح.');
        m.remove();
        onUpdated();
      } catch (err) {
        alert('❌ تعذر التحديث: ' + err.message);
      }
    };
  } catch (err) {
    alert('تعذر فتح نموذج التعديل: ' + err.message);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// MODAL: VEHICLES FLEET REGISTRY (إدارة أسطول المركبات والعهد)
// ─────────────────────────────────────────────────────────────────────────────
export async function openVehiclesFleetModal(container) {
  try {
    const role = appStore.get().role || localStorage.getItem('dou_role_v2') || 'COMPANY_ADMIN';
    const isAdmin = ['COMPANY', 'COMPANY_ADMIN', 'OPERATIONS', 'DOU_ADMIN', 'DOU_OPS'].includes(role);

    const vehicles = await api.get('/vehicles/').catch(() => []);

    const content = el('div', { style: 'display:grid;gap:14px;min-width:650px;direction:rtl' }, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:center' }, [
        el('div', {}, [
          el('h3', { style: 'margin:0;font-size:15px;color:var(--text)' }, `سجل مركبات الأسطول والعهد (${vehicles.length})`),
          el('p', { style: 'margin:4px 0 0 0;font-size:12px;color:var(--muted)' }, 'متابعة الفحص الدوري والتأمين ورخص السير')
        ]),
        isAdmin ? el('button', {
          class: 'btn btn-primary btn-small',
          onclick: () => openAddVehicleModal(() => { m.remove(); openVehiclesFleetModal(container); })
        }, '➕ إضافة مركبة جديدة') : null
      ]),
      vehicles.length ? table([
        { key: 'plate_number', label: 'رقم اللوحة', render: (v) => el('b', { dir: 'ltr', style: 'font-family:monospace;font-size:13px;color:var(--text)' }, v) },
        { key: 'vehicle_type', label: 'النوع', render: (v) => {
          const isMoto = String(v).toLowerCase().includes('moto');
          return el('span', { class: `badge badge-${isMoto ? 'blue' : 'green'}` }, isMoto ? '🛵 دباب' : '🚗 سيارة');
        }},
        { key: 'make', label: 'الماركة والموديل', render: (v, r) => `${v || ''} ${r.model || ''} ${r.model_year || ''}`.trim() || '—' },
        { key: 'compliance_status', label: 'الامتثال', render: (v) => el('span', { class: `badge badge-${v === 'COMPLIANT' ? 'green' : 'amber'}` }, v === 'COMPLIANT' ? 'ساري الفحص ✅' : 'يحتاج تجديد ⚠️') },
        { key: 'operational_status', label: 'الحالة', render: (v) => el('span', { class: `badge badge-${v === 'ACTIVE' ? 'green' : 'gray'}` }, v === 'ACTIVE' ? 'نشطة' : 'متوقفة') },
        { key: 'actions', label: 'إجراءات', render: (_, r) => el('div', { style: 'display:flex;gap:4px' }, [
          el('button', {
            class: 'btn btn-ghost btn-small',
            style: 'padding:2px 6px;font-size:11px;color:var(--primary)',
            onclick: () => openEditVehicleModal(r, () => { m.remove(); openVehiclesFleetModal(container); })
          }, '✏️ تعديل'),
          el('button', {
            class: 'btn btn-ghost btn-small',
            style: 'padding:2px 6px;font-size:11px;color:var(--red)',
            onclick: async () => {
              if (!confirm(`هل تريد بالتأكيد تعطيل/حذف المركبة ${r.plate_number}؟`)) return;
              try {
                await api.delete(`/vehicles/${r.id}`);
                alert('✅ تم تعطيل المركبة بنجاح.');
                m.remove();
                openVehiclesFleetModal(container);
              } catch (err) {
                alert('❌ تعذر الحذف: ' + err.message);
              }
            }
          }, '🗑️ حذف'),
        ])}
      ], vehicles) : emptyState('لا توجد مركبات مسجلة في الأسطول حالياً.')
    ]);

    const m = modal('🚗 إدارة أسطول المركبات والعهد التشغيلية', content);

  } catch (e) {
    alert('تعذر فتح سجل المركبات: ' + e.message);
  }
}

async function openEditVehicleModal(vehicle, onUpdated) {
  const content = el('form', { style: 'display:grid;gap:12px;direction:rtl' }, [
    el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'رقم اللوحة: *'),
        el('input', { id: 'ev-plate', value: vehicle.plate_number || '', required: true, style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'نوع المركبة: *'),
        el('select', { id: 'ev-type', style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' }, [
          el('option', { value: 'Motorcycle', selected: vehicle.vehicle_type === 'Motorcycle' }, 'دباب / دراجة نارية'),
          el('option', { value: 'Car', selected: vehicle.vehicle_type === 'Car' }, 'سيارة صغيرة'),
          el('option', { value: 'Van', selected: vehicle.vehicle_type === 'Van' }, 'فان بضائع')
        ])
      ]),
    ]),
    el('div', { style: 'display:grid;grid-template-columns:repeat(3, 1fr);gap:10px' }, [
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'الماركة:'),
        el('input', { id: 'ev-make', value: vehicle.make || '', placeholder: 'تويوتا / سوزوكي', style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'الموديل:'),
        el('input', { id: 'ev-model', value: vehicle.model || '', placeholder: 'Yaris / GN125', style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'الحالة:'),
        el('select', { id: 'ev-status', style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' }, [
          el('option', { value: 'ACTIVE', selected: vehicle.operational_status === 'ACTIVE' }, '🟢 نشطة'),
          el('option', { value: 'INACTIVE', selected: vehicle.operational_status === 'INACTIVE' }, '⚪ متوقفة')
        ])
      ]),
    ]),
    el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:10px' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
      el('button', { type: 'submit', class: 'btn btn-primary' }, '💾 حفظ التعديل')
    ])
  ]);

  const m = modal(`✏️ تعديل بيانات المركبة: ${vehicle.plate_number}`, content);

  content.onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api.patch(`/vehicles/${vehicle.id}`, {
        plate_number: document.getElementById('ev-plate').value.trim(),
        vehicle_type: document.getElementById('ev-type').value,
        make: document.getElementById('ev-make').value.trim() || undefined,
        model: document.getElementById('ev-model').value.trim() || undefined,
        operational_status: document.getElementById('ev-status').value,
      });
      alert('✅ تم تعديل بيانات المركبة بنجاح.');
      m.remove();
      onUpdated();
    } catch (err) {
      alert('❌ تعذر التعديل: ' + err.message);
    }
  };
}

async function openAddVehicleModal(onCreated) {
  const content = el('form', { style: 'display:grid;gap:12px' }, [
    el('div', { style: 'display:grid;grid-template-columns:1fr 1fr;gap:10px' }, [
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'رقم اللوحة: *'),
        el('input', { id: 'veh-plate', placeholder: 'مثال: أ ب ج 1234', required: true, style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'نوع المركبة: *'),
        el('select', { id: 'veh-type', style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' }, [
          el('option', { value: 'Motorcycle' }, 'دباب / دراجة نارية'),
          el('option', { value: 'Car' }, 'سيارة صغيرة'),
          el('option', { value: 'Van' }, 'فان بضائع')
        ])
      ]),
    ]),
    el('div', { style: 'display:grid;grid-template-columns:repeat(3, 1fr);gap:10px' }, [
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'الماركة:'),
        el('input', { id: 'veh-make', placeholder: 'مثال: سوزوكي / تويوتا', style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'الموديل:'),
        el('input', { id: 'veh-model', placeholder: 'GN125 / Yaris', style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' })
      ]),
      el('div', {}, [
        el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px' }, 'سنة الصنع:'),
        el('input', { type: 'number', id: 'veh-year', placeholder: '2024', style: 'width:100%;padding:8px;border:1px solid var(--border);border-radius:8px' })
      ]),
    ]),
    el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:10px' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => m.remove() }, 'إلغاء'),
      el('button', { type: 'submit', class: 'btn btn-primary' }, 'تسجيل المركبة')
    ])
  ]);

  const m = modal('➕ تسجيل مركبة جديدة في الأسطول', content);

  content.onsubmit = async (e) => {
    e.preventDefault();
    const plate = document.getElementById('veh-plate').value.trim();
    const type = document.getElementById('veh-type').value;
    const make = document.getElementById('veh-make').value.trim();
    const model = document.getElementById('veh-model').value.trim();
    const year = parseInt(document.getElementById('veh-year').value) || undefined;

    try {
      await api.post('/vehicles/', {
        plate_number: plate,
        vehicle_type: type,
        make: make || undefined,
        model: model || undefined,
        model_year: year,
        market_code: 'SA',
        is_exclusive: true
      });
      alert('✅ تم تسجيل المركبة بنجاح.');
      m.remove();
      onCreated();
    } catch (err) {
      alert('❌ تعذر تسجيل المركبة: ' + err.message);
    }
  };
}


// ─────────────────────────────────────────────────────────────────────────────
// Broadcast — the sending half of the rider app's company-messages screen
// ─────────────────────────────────────────────────────────────────────────────
function openBroadcastModal() {
  const isAr = getLang() === 'ar';
  const content = el('form', { onsubmit: async (e) => {
    e.preventDefault();
    const msg = document.getElementById('bc-msg');
    const text = document.getElementById('bc-text').value.trim();
    if (!text) return;
    const button = document.getElementById('bc-send');
    button.disabled = true;
    try {
      const res = await api.post('/hr/broadcast', { message: text });
      msg.style.color = 'var(--green)';
      msg.textContent = isAr
        ? `✅ أُرسلت الرسالة إلى ${res.sent_to ?? 0} مندوب.`
        : `✅ Sent to ${res.sent_to ?? 0} riders.`;
      setTimeout(() => m.remove(), 1500);
    } catch (err) {
      msg.style.color = 'var(--red)';
      msg.textContent = '❌ ' + err.message;
      button.disabled = false;
    }
  }}, [
    el('p', { style: 'margin:0 0 12px;font-size:12px;color:var(--muted)' },
      isAr
        ? 'تصل الرسالة إلى كل مناديبك داخل تطبيق السائق، في شاشة «رسائل الشركة».'
        : 'This reaches every one of your riders in the driver app, under "Company messages".'),
    formRow([el('div', {}, [
      el('label', { for: 'bc-text', text: isAr ? 'نص الرسالة' : 'Message' }),
      el('textarea', {
        id: 'bc-text', name: 'bc-text', rows: '4', required: true, maxlength: '600',
        style: 'width:100%;padding:10px;border:1px solid var(--border);border-radius:8px;font-family:inherit',
        placeholder: isAr ? 'مثال: غداً اجتماع تشغيلي الساعة 9 صباحاً.' : 'e.g. Operations meeting tomorrow at 9am.',
      }),
    ])]),
    el('p', { id: 'bc-msg', style: 'margin:8px 0 0;font-size:12px' }),
    el('button', { class: 'btn btn-primary btn-blue btn-full', type: 'submit', id: 'bc-send', style: 'margin-top:12px' },
      isAr ? '📢 إرسال للجميع' : '📢 Send to all riders'),
  ]);
  const m = modal(isAr ? '📢 رسالة لكل المناديب' : '📢 Message all riders', content);
}
