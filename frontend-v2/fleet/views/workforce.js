// Workforce & Operating Zones Management
// Connects 5+ workforce endpoints:
//   - GET /workforce/teams
//   - POST /workforce/teams
//   - GET /workforce/teams/{id}/memberships
//   - POST /workforce/teams/{id}/memberships
//   - POST /workforce/riders/{courier_id}/team-transfer
//   - GET /workforce/teams/{id}/supervisors
//   - POST /workforce/teams/{id}/supervisors
//   - GET /workforce/zones
//   - POST /workforce/zones

import { api } from '../../shared/api/client.js';
import { el, loadingState, emptyState, errorState, metricCard, badge, modal } from '../../shared/components/ui.js';
import { getLang } from '../../shared/i18n/i18n.js';

export async function loadWorkforce(container) {
  container.innerHTML = '';
  const isAr = getLang() === 'ar';

  const shell = el('div', {
    class: 'workforce-workspace',
    style: 'max-width:1100px;margin:0 auto;padding:16px 20px 80px;direction:rtl;font-family:inherit;'
  });
  if (!isAr) shell.style.direction = 'ltr';

  container.append(shell);

  // Header
  const header = el('div', {
    class: 'card',
    style: 'padding:20px 24px;margin-bottom:18px;background:var(--card);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow-sm);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px;'
  }, [
    el('div', { style: 'display:flex;align-items:center;gap:14px' }, [
      el('span', { style: 'font-size:32px;line-height:1' }, '🌐'),
      el('div', {}, [
        el('h1', { style: 'font-size:20px;font-weight:800;margin:0;color:var(--ink)' },
          isAr ? 'إدارة الفرق والمناطق التشغيلية' : 'Workforce Teams & Operating Zones'
        ),
        el('p', { style: 'font-size:13px;color:var(--muted);margin:4px 0 0' },
          isAr ? 'تقسيم الأسطول إلى مجموعات ميدانية ومناطق جغرافية وتعيين المشرفين ونقل السائقين' : 'Organize 200+ fleet into geographic zones and operational teams'
        )
      ])
    ]),
    el('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;' }, [
      el('button', {
        type: 'button',
        class: 'btn btn-secondary',
        style: 'min-height:42px;font-weight:700;display:flex;align-items:center;gap:6px',
        onclick: () => openTransferRiderModal(isAr, () => loadCurrentTab())
      }, [
        el('span', {}, '🔀'),
        el('span', {}, isAr ? 'نقل سائق بين الفرق' : 'Transfer Rider')
      ]),
      el('button', {
        type: 'button',
        class: 'btn btn-primary',
        style: 'min-height:42px;font-weight:700;display:flex;align-items:center;gap:6px',
        onclick: () => {
          if (activeTab === 'teams') {
            openCreateTeamModal(isAr, () => loadCurrentTab());
          } else {
            openCreateZoneModal(isAr, () => loadCurrentTab());
          }
        }
      }, [
        el('span', {}, '➕'),
        el('span', { id: 'btn-main-action' }, isAr ? 'إنشاء فريق عمل' : 'New Team')
      ])
    ])
  ]);
  shell.append(header);

  // Tabs
  const tabs = [
    { id: 'teams', icon: '👥', label_ar: 'فرق العمل الميدانية (Teams)', label_en: 'Workforce Teams' },
    { id: 'zones', icon: '📍', label_ar: 'المناطق الجغرافية (Zones)', label_en: 'Operating Zones' },
  ];

  let activeTab = 'teams';
  const tabContainer = el('div', {
    style: 'display:flex;gap:10px;border-bottom:1px solid var(--border);padding-bottom:10px;margin-bottom:18px;'
  });

  const tabButtons = {};
  tabs.forEach(t => {
    const btn = el('button', {
      type: 'button',
      class: `btn ${activeTab === t.id ? 'btn-primary' : 'btn-ghost'}`,
      style: 'min-height:42px;padding:8px 18px;border-radius:10px;font-size:14px;font-weight:700;display:flex;align-items:center;gap:8px;',
      onclick: () => switchTab(t.id)
    }, [
      el('span', {}, t.icon),
      el('span', {}, isAr ? t.label_ar : t.label_en)
    ]);
    tabButtons[t.id] = btn;
    tabContainer.append(btn);
  });
  shell.append(tabContainer);

  // Content Area
  const contentArea = el('div', { id: 'workforce-content-area' });
  shell.append(contentArea);

  function switchTab(tabId) {
    activeTab = tabId;
    Object.entries(tabButtons).forEach(([id, btn]) => {
      btn.className = id === tabId ? 'btn btn-primary' : 'btn btn-ghost';
    });
    const mainActionBtn = document.getElementById('btn-main-action');
    if (mainActionBtn) {
      if (tabId === 'teams') {
        mainActionBtn.textContent = isAr ? 'إنشاء فريق عمل' : 'New Team';
      } else {
        mainActionBtn.textContent = isAr ? 'إضافة منطقة جغرافية' : 'New Zone';
      }
    }
    loadCurrentTab();
  }

  async function loadCurrentTab() {
    contentArea.innerHTML = '';
    contentArea.append(loadingState(isAr ? 'جاري تحميل البيانات...' : 'Loading workforce data...'));

    try {
      if (activeTab === 'teams') {
        await renderTeamsTab(contentArea, isAr, loadCurrentTab);
      } else {
        await renderZonesTab(contentArea, isAr, loadCurrentTab);
      }
    } catch (err) {
      contentArea.innerHTML = '';
      contentArea.append(errorState(err.message, loadCurrentTab));
    }
  }

  loadCurrentTab();
}

// ── 1. TEAMS TAB ──
async function renderTeamsTab(container, isAr, reloadTab) {
  // Fetch teams and zones in parallel
  const [teams, zones] = await Promise.all([
    api.get('/workforce/teams?active_only=false'),
    api.get('/workforce/zones?active_only=false'),
  ]);

  const zoneMap = new Map();
  zones.forEach(z => zoneMap.set(z.id, z));

  container.innerHTML = '';

  // KPI Overview
  const kpiRow = el('div', {
    style: 'display:grid;grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));gap:12px;margin-bottom:18px;'
  }, [
    metricCard(teams.length, isAr ? 'إجمالي فرق العمل' : 'Total Teams', 'blue'),
    metricCard(teams.filter(t => t.is_active).length, isAr ? 'الفرق النشطة' : 'Active Teams', 'green'),
    metricCard(zones.length, isAr ? 'المناطق المغطاة' : 'Zones Covered', 'blue'),
  ]);
  container.append(kpiRow);

  if (!teams || teams.length === 0) {
    container.append(emptyState(
      isAr ? 'لم يتم إنشاء فرق عمل بعد. ابدأ بإنشاء فريقك الأول لتوزيع الأسطول.' : 'No workforce teams yet. Create your first team to organize riders.',
      el('button', {
        class: 'btn btn-primary',
        style: 'margin-top:14px;font-weight:700',
        onclick: () => openCreateTeamModal(isAr, reloadTab)
      }, isAr ? '➕ إنشاء أول فريق' : '➕ Create First Team')
    ));
    return;
  }

  // Teams Table / Grid
  const list = el('div', { style: 'display:grid;grid-template-columns:repeat(auto-fit, minmax(320px, 1fr));gap:14px;' });

  teams.forEach(team => {
    const zone = team.zone_id ? zoneMap.get(team.zone_id) : null;
    const zoneName = zone ? (isAr ? zone.name_ar : (zone.name_en || zone.name_ar)) : (isAr ? 'غير محدد' : 'Unassigned');

    const card = el('div', {
      class: 'card',
      style: 'padding:18px;background:var(--card);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow-sm);display:flex;flex-direction:column;justify-content:space-between;gap:14px;'
    }, [
      el('div', {}, [
        el('div', { style: 'display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;' }, [
          el('div', {}, [
            el('h3', { style: 'margin:0;font-size:16px;font-weight:800;color:var(--ink)' }, isAr ? team.name_ar : (team.name_en || team.name_ar)),
            el('span', { style: 'font-size:12px;font-family:monospace;color:var(--muted);font-weight:700' }, `[${team.code}]`)
          ]),
          el('span', { class: `badge badge-${team.is_active ? 'green' : 'gray'}` },
            team.is_active ? (isAr ? 'نشط' : 'Active') : (isAr ? 'معطل' : 'Inactive')
          )
        ]),
        el('div', { style: 'font-size:13px;color:var(--muted);display:flex;flex-direction:column;gap:4px;' }, [
          el('div', {}, [
            el('b', { style: 'color:var(--ink)' }, isAr ? 'المنطقة الجغرافية: ' : 'Zone: '),
            el('span', {}, zoneName)
          ]),
        ])
      ]),

      // Actions Toolbar
      el('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;border-top:1px solid var(--border);padding-top:12px;' }, [
        el('button', {
          type: 'button',
          class: 'btn btn-secondary btn-small',
          style: 'flex:1;min-height:36px;font-weight:700;display:flex;align-items:center;justify-content:center;gap:4px;',
          onclick: () => openTeamMembersModal(team, isAr, reloadTab)
        }, [
          el('span', {}, '👥'),
          el('span', {}, isAr ? 'الأعضاء' : 'Members')
        ]),
        el('button', {
          type: 'button',
          class: 'btn btn-ghost btn-small',
          style: 'min-height:36px;font-weight:700;display:flex;align-items:center;gap:4px;',
          onclick: () => openAssignSupervisorModal(team, isAr, reloadTab)
        }, [
          el('span', {}, '👔'),
          el('span', {}, isAr ? 'تعيين مشرف' : 'Supervisor')
        ]),
        el('button', {
          type: 'button',
          class: 'btn btn-primary btn-small',
          style: 'min-height:36px;font-weight:700;display:flex;align-items:center;gap:4px;',
          onclick: () => openAddMemberModal(team, isAr, reloadTab)
        }, [
          el('span', {}, '➕'),
          el('span', {}, isAr ? 'إضافة سائق' : 'Add Rider')
        ])
      ])
    ]);
    list.append(card);
  });

  container.append(list);
}

// ── 2. ZONES TAB ──
async function renderZonesTab(container, isAr, reloadTab) {
  const [zones, cities] = await Promise.all([
    api.get('/workforce/zones?active_only=false'),
    api.get('/hr/operating-cities'),
  ]);

  const cityMap = new Map();
  cities.forEach(c => cityMap.set(c.id, c.name));

  container.innerHTML = '';

  const kpiRow = el('div', {
    style: 'display:grid;grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));gap:12px;margin-bottom:18px;'
  }, [
    metricCard(zones.length, isAr ? 'إجمالي المناطق' : 'Total Zones', 'blue'),
    metricCard(zones.filter(z => z.is_active).length, isAr ? 'المناطق النشطة' : 'Active Zones', 'green'),
    metricCard(cities.length, isAr ? 'المدن التشغيلية' : 'Operating Cities', 'blue'),
  ]);
  container.append(kpiRow);

  if (!zones || zones.length === 0) {
    container.append(emptyState(
      isAr ? 'لا توجد مناطق جغرافية مسجلة بعد. حدد مناطق التغطية للبدء.' : 'No operating zones defined yet.',
      el('button', {
        class: 'btn btn-primary',
        style: 'margin-top:14px;font-weight:700',
        onclick: () => openCreateZoneModal(isAr, reloadTab)
      }, isAr ? '➕ إضافة منطقة' : '➕ Add Zone')
    ));
    return;
  }

  // Zones Table
  const table = el('div', {
    class: 'card',
    style: 'padding:0;overflow-x:auto;background:var(--card);border:1px solid var(--border);border-radius:14px;'
  }, [
    el('table', { style: 'width:100%;border-collapse:collapse;text-align:inherit;font-size:13px;' }, [
      el('thead', { style: 'background:var(--card-subtle, #f8fafc);border-bottom:1px solid var(--border);' }, [
        el('tr', {}, [
          el('th', { style: 'padding:12px 16px;font-weight:700;color:var(--muted)' }, isAr ? 'كود المنطقة' : 'Code'),
          el('th', { style: 'padding:12px 16px;font-weight:700;color:var(--muted)' }, isAr ? 'اسم المنطقة (عربي)' : 'Name (AR)'),
          el('th', { style: 'padding:12px 16px;font-weight:700;color:var(--muted)' }, isAr ? 'اسم المنطقة (إنجليزي)' : 'Name (EN)'),
          el('th', { style: 'padding:12px 16px;font-weight:700;color:var(--muted)' }, isAr ? 'المدينة التشغيلية' : 'City'),
          el('th', { style: 'padding:12px 16px;font-weight:700;color:var(--muted)' }, isAr ? 'الحالة' : 'Status'),
        ])
      ]),
      el('tbody', {}, zones.map(z => {
        const cityName = cityMap.get(z.operating_city_id) || `City #${z.operating_city_id}`;
        return el('tr', { style: 'border-bottom:1px solid var(--border);' }, [
          el('td', { style: 'padding:12px 16px;font-family:monospace;font-weight:700;' }, z.code),
          el('td', { style: 'padding:12px 16px;font-weight:700;color:var(--ink)' }, z.name_ar),
          el('td', { style: 'padding:12px 16px;color:var(--muted)' }, z.name_en || '—'),
          el('td', { style: 'padding:12px 16px;' }, cityName),
          el('td', { style: 'padding:12px 16px;' }, [
            el('span', { class: `badge badge-${z.is_active ? 'green' : 'gray'}` },
              z.is_active ? (isAr ? 'نشط' : 'Active') : (isAr ? 'معطل' : 'Inactive')
            )
          ])
        ]);
      }))
    ])
  ]);

  container.append(table);
}

// ── MODALS ──

// 1. Create Team Modal
async function openCreateTeamModal(isAr, onSuccess) {
  const zones = await api.get('/workforce/zones?active_only=true');

  const zoneOptions = [
    el('option', { value: '' }, isAr ? '-- بدون ربط بمنطقة --' : '-- No Zone --'),
    ...zones.map(z => el('option', { value: String(z.id) }, `${z.code} - ${isAr ? z.name_ar : (z.name_en || z.name_ar)}`))
  ];

  const codeInput = el('input', { class: 'input', placeholder: 'e.g. TM-CENTRAL-01', required: 'true' });
  const nameArInput = el('input', { class: 'input', placeholder: 'مثال: فريق وسط الرياض', required: 'true' });
  const nameEnInput = el('input', { class: 'input', placeholder: 'e.g. Central Riyadh Team' });
  const zoneSelect = el('select', { class: 'input' }, zoneOptions);

  const errorMsg = el('div', { style: 'color:#ef4444;font-size:12px;font-weight:700;display:none;margin-top:6px' });

  const content = el('form', {
    style: 'display:flex;flex-direction:column;gap:12px;',
    onsubmit: async (e) => {
      e.preventDefault();
      errorMsg.style.display = 'none';

      const payload = {
        code: codeInput.value.trim().toUpperCase(),
        name_ar: nameArInput.value.trim(),
        name_en: nameEnInput.value.trim() || null,
        zone_id: zoneSelect.value ? Number(zoneSelect.value) : null,
      };

      try {
        await api.post('/workforce/teams', payload);
        modalInstance.close();
        onSuccess();
      } catch (err) {
        errorMsg.textContent = err.message || (isAr ? 'حدث خطأ أثناء إنشاء الفريق' : 'Failed to create team');
        errorMsg.style.display = 'block';
      }
    }
  }, [
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'كود الفريق (فريد)' : 'Team Code (Unique)'),
      codeInput
    ]),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'اسم الفريق (عربي) *' : 'Team Name (AR) *'),
      nameArInput
    ]),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'اسم الفريق (إنجليزي)' : 'Team Name (EN)'),
      nameEnInput
    ]),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'المنطقة الجغرافية' : 'Operating Zone'),
      zoneSelect
    ]),
    errorMsg,
    el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:8px;' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => modalInstance.close() }, isAr ? 'إلغاء' : 'Cancel'),
      el('button', { type: 'submit', class: 'btn btn-primary', style: 'font-weight:700' }, isAr ? 'حفظ الفريق' : 'Create Team')
    ])
  ]);

  const modalInstance = modal(isAr ? 'إنشاء فريق عمل ميداني جديد' : 'Create Workforce Team', content);
}

// 2. Create Zone Modal
async function openCreateZoneModal(isAr, onSuccess) {
  const cities = await api.get('/hr/operating-cities');

  const cityOptions = cities.map(c => el('option', { value: String(c.id) }, `${c.name} (${c.reference_name || ''})`));

  const codeInput = el('input', { class: 'input', placeholder: 'e.g. ZN-RUH-NORTH', required: 'true' });
  const nameArInput = el('input', { class: 'input', placeholder: 'مثال: شمال الرياض', required: 'true' });
  const nameEnInput = el('input', { class: 'input', placeholder: 'e.g. North Riyadh' });
  const citySelect = el('select', { class: 'input' }, cityOptions);

  const errorMsg = el('div', { style: 'color:#ef4444;font-size:12px;font-weight:700;display:none;margin-top:6px' });

  const content = el('form', {
    style: 'display:flex;flex-direction:column;gap:12px;',
    onsubmit: async (e) => {
      e.preventDefault();
      errorMsg.style.display = 'none';

      const payload = {
        code: codeInput.value.trim().toUpperCase(),
        name_ar: nameArInput.value.trim(),
        name_en: nameEnInput.value.trim() || null,
        operating_city_id: Number(citySelect.value),
      };

      try {
        await api.post('/workforce/zones', payload);
        modalInstance.close();
        onSuccess();
      } catch (err) {
        errorMsg.textContent = err.message || (isAr ? 'حدث خطأ أثناء إنشاء المنطقة' : 'Failed to create zone');
        errorMsg.style.display = 'block';
      }
    }
  }, [
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'كود المنطقة (فريد)' : 'Zone Code (Unique)'),
      codeInput
    ]),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'اسم المنطقة (عربي) *' : 'Zone Name (AR) *'),
      nameArInput
    ]),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'اسم المنطقة (إنجليزي)' : 'Zone Name (EN)'),
      nameEnInput
    ]),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'المدينة التشغيلية *' : 'Operating City *'),
      citySelect
    ]),
    errorMsg,
    el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:8px;' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => modalInstance.close() }, isAr ? 'إلغاء' : 'Cancel'),
      el('button', { type: 'submit', class: 'btn btn-primary', style: 'font-weight:700' }, isAr ? 'حفظ المنطقة' : 'Create Zone')
    ])
  ]);

  const modalInstance = modal(isAr ? 'إضافة منطقة جغرافية جديدة' : 'Create Operating Zone', content);
}

// 3. Assign Supervisor Modal
async function openAssignSupervisorModal(team, isAr, onSuccess) {
  const supervisors = await api.get('/hr/supervisors');

  const supOptions = supervisors.map(s => el('option', { value: String(s.id) }, `${s.name} (${s.phone || 'No phone'})`));

  const supSelect = el('select', { class: 'input' }, supOptions);
  const dateInput = el('input', {
    type: 'date',
    class: 'input',
    value: new Date().toISOString().slice(0, 10),
    required: 'true'
  });

  const errorMsg = el('div', { style: 'color:#ef4444;font-size:12px;font-weight:700;display:none;margin-top:6px' });

  const content = el('form', {
    style: 'display:flex;flex-direction:column;gap:12px;',
    onsubmit: async (e) => {
      e.preventDefault();
      errorMsg.style.display = 'none';

      const payload = {
        supervisor_id: Number(supSelect.value),
        effective_from: dateInput.value,
      };

      try {
        await api.post(`/workforce/teams/${team.id}/supervisors`, payload);
        modalInstance.close();
        onSuccess();
      } catch (err) {
        errorMsg.textContent = err.message || (isAr ? 'حدث خطأ أثناء تعيين المشرف' : 'Failed to assign supervisor');
        errorMsg.style.display = 'block';
      }
    }
  }, [
    el('p', { style: 'font-size:13px;color:var(--muted);margin:0 0 10px' },
      isAr ? `تعيين مشرف مسؤول عن متابعة فريق "${team.name_ar}"` : `Assign supervisor to team "${team.name_ar}"`
    ),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'اختر المشرف الميداني *' : 'Select Supervisor *'),
      supSelect
    ]),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'تاريخ سريان التعيين *' : 'Effective From *'),
      dateInput
    ]),
    errorMsg,
    el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:8px;' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => modalInstance.close() }, isAr ? 'إلغاء' : 'Cancel'),
      el('button', { type: 'submit', class: 'btn btn-primary', style: 'font-weight:700' }, isAr ? 'تأكيد التعيين' : 'Confirm Assignment')
    ])
  ]);

  const modalInstance = modal(isAr ? 'تعيين مشرف للفريق' : 'Assign Team Supervisor', content);
}

// 4. Add Member Modal
async function openAddMemberModal(team, isAr, onSuccess) {
  const couriers = await api.get('/hr/couriers');

  const courierOptions = couriers.map(c => el('option', { value: String(c.id) }, `${c.name} (${c.phone || `#${c.id}`})`));

  const courierSelect = el('select', { class: 'input' }, courierOptions);
  const dateInput = el('input', {
    type: 'date',
    class: 'input',
    value: new Date().toISOString().slice(0, 10),
    required: 'true'
  });

  const errorMsg = el('div', { style: 'color:#ef4444;font-size:12px;font-weight:700;display:none;margin-top:6px' });

  const content = el('form', {
    style: 'display:flex;flex-direction:column;gap:12px;',
    onsubmit: async (e) => {
      e.preventDefault();
      errorMsg.style.display = 'none';

      const payload = {
        courier_id: Number(courierSelect.value),
        effective_from: dateInput.value,
        is_primary: true,
      };

      try {
        await api.post(`/workforce/teams/${team.id}/memberships`, payload);
        modalInstance.close();
        onSuccess();
      } catch (err) {
        errorMsg.textContent = err.message || (isAr ? 'حدث خطأ أثناء إضافة السائق' : 'Failed to add rider to team');
        errorMsg.style.display = 'block';
      }
    }
  }, [
    el('p', { style: 'font-size:13px;color:var(--muted);margin:0 0 10px' },
      isAr ? `إسناد سائق جديد لفريق "${team.name_ar}"` : `Add rider to team "${team.name_ar}"`
    ),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'اختر السائق *' : 'Select Rider *'),
      courierSelect
    ]),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'تاريخ بدء الانضمام للفريق *' : 'Effective From *'),
      dateInput
    ]),
    errorMsg,
    el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:8px;' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => modalInstance.close() }, isAr ? 'إلغاء' : 'Cancel'),
      el('button', { type: 'submit', class: 'btn btn-primary', style: 'font-weight:700' }, isAr ? 'إضافة للفريق' : 'Add to Team')
    ])
  ]);

  const modalInstance = modal(isAr ? 'إضافة سائق لفريق العمل' : 'Add Rider to Team', content);
}

// 5. Transfer Rider Modal
async function openTransferRiderModal(isAr, onSuccess) {
  const [couriers, teams] = await Promise.all([
    api.get('/hr/couriers'),
    api.get('/workforce/teams?active_only=true')
  ]);

  const courierOptions = couriers.map(c => el('option', { value: String(c.id) }, `${c.name} (${c.phone || `#${c.id}`})`));
  const teamOptions = teams.map(t => el('option', { value: String(t.id) }, `${t.code} - ${isAr ? t.name_ar : (t.name_en || t.name_ar)}`));

  const courierSelect = el('select', { class: 'input' }, courierOptions);
  const teamSelect = el('select', { class: 'input' }, teamOptions);
  const dateInput = el('input', {
    type: 'date',
    class: 'input',
    value: new Date().toISOString().slice(0, 10),
    required: 'true'
  });

  const errorMsg = el('div', { style: 'color:#ef4444;font-size:12px;font-weight:700;display:none;margin-top:6px' });

  const content = el('form', {
    style: 'display:flex;flex-direction:column;gap:12px;',
    onsubmit: async (e) => {
      e.preventDefault();
      errorMsg.style.display = 'none';

      const courierId = Number(courierSelect.value);
      const payload = {
        team_id: Number(teamSelect.value),
        effective_on: dateInput.value,
      };

      try {
        await api.post(`/workforce/riders/${courierId}/team-transfer`, payload);
        modalInstance.close();
        onSuccess();
      } catch (err) {
        errorMsg.textContent = err.message || (isAr ? 'حدث خطأ أثناء نقل السائق' : 'Failed to transfer rider');
        errorMsg.style.display = 'block';
      }
    }
  }, [
    el('p', { style: 'font-size:13px;color:var(--muted);margin:0 0 10px' },
      isAr ? 'نقل السائق رسميًا من فريقه الحالي إلى فريق آخر مع حفظ سجل التواريخ المالي والتشغيلي.' : 'Formally transfer rider to a new team preserving historical audit logs.'
    ),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'السائق المطلوب نقله *' : 'Rider to Transfer *'),
      courierSelect
    ]),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'الفريق المستهدف *' : 'Target Team *'),
      teamSelect
    ]),
    el('div', {}, [
      el('label', { style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;' }, isAr ? 'تاريخ بدء النقل *' : 'Effective Date *'),
      dateInput
    ]),
    errorMsg,
    el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:8px;' }, [
      el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => modalInstance.close() }, isAr ? 'إلغاء' : 'Cancel'),
      el('button', { type: 'submit', class: 'btn btn-primary', style: 'font-weight:700' }, isAr ? 'تأكيد النقل' : 'Execute Transfer')
    ])
  ]);

  const modalInstance = modal(isAr ? 'نقل سائق بين فرق العمل' : 'Transfer Rider Between Teams', content);
}

// 6. View Team Members Modal
async function openTeamMembersModal(team, isAr, reloadTab) {
  const modalContainer = el('div', { style: 'display:flex;flex-direction:column;gap:12px;' });
  modalContainer.append(loadingState(isAr ? 'جاري تحميل أعضاء الفريق...' : 'Loading team members...'));

  const modalInstance = modal(isAr ? `أعضاء فريق: ${team.name_ar}` : `Members of: ${team.name_ar}`, modalContainer);

  try {
    const [memberships, couriers, supervisors] = await Promise.all([
      api.get(`/workforce/teams/${team.id}/memberships`),
      api.get('/hr/couriers'),
      api.get(`/workforce/teams/${team.id}/supervisors`),
    ]);

    const courierMap = new Map();
    couriers.forEach(c => courierMap.set(c.id, c));

    modalContainer.innerHTML = '';

    // Supervisor banner
    if (supervisors && supervisors.length > 0) {
      const activeSup = supervisors[0];
      modalContainer.append(el('div', {
        class: 'card',
        style: 'padding:10px 14px;background:#f0fdf4;border:1px solid #86efac;border-radius:10px;display:flex;align-items:center;gap:10px;'
      }, [
        el('span', { style: 'font-size:20px' }, '👔'),
        el('div', {}, [
          el('b', { style: 'font-size:13px;color:#166534' }, isAr ? 'المشرف المسؤول: ' : 'Assigned Supervisor: '),
          el('span', { style: 'font-size:13px;color:#15803d' }, `User #${activeSup.supervisor_id} (${isAr ? 'من تاريخ:' : 'From:'} ${activeSup.effective_from})`)
        ])
      ]));
    }

    if (!memberships || memberships.length === 0) {
      modalContainer.append(emptyState(isAr ? 'لا يوجد سائقون في هذا الفريق حالياً' : 'No riders in this team yet'));
    } else {
      const list = el('div', { style: 'display:flex;flex-direction:column;gap:8px;max-height:350px;overflow-y:auto;' });

      memberships.forEach(m => {
        const c = courierMap.get(m.courier_id);
        const name = c ? c.name : `Rider #${m.courier_id}`;
        const phone = c ? c.phone : '';

        const item = el('div', {
          class: 'card',
          style: 'padding:10px 14px;background:var(--card);border:1px solid var(--border);border-radius:10px;display:flex;justify-content:space-between;align-items:center;'
        }, [
          el('div', { style: 'display:flex;align-items:center;gap:10px' }, [
            el('span', { style: 'font-size:20px' }, '🚴'),
            el('div', {}, [
              el('h4', { style: 'margin:0;font-size:14px;font-weight:700;color:var(--ink)' }, name),
              el('span', { style: 'font-size:12px;color:var(--muted)' }, `${phone || ''} • ${isAr ? 'انضم:' : 'Joined:'} ${m.effective_from}`)
            ])
          ]),
          el('span', { class: 'badge badge-green' }, isAr ? 'عضو نشط' : 'Active')
        ]);
        list.append(item);
      });

      modalContainer.append(list);
    }

    modalContainer.append(el('div', { style: 'display:flex;justify-content:space-between;gap:10px;margin-top:10px;' }, [
      el('button', {
        class: 'btn btn-primary btn-small',
        style: 'font-weight:700',
        onclick: () => {
          modalInstance.close();
          openAddMemberModal(team, isAr, reloadTab);
        }
      }, isAr ? '➕ إضافة سائق لهذا الفريق' : '➕ Add Rider to Team'),
      el('button', {
        class: 'btn btn-ghost btn-small',
        onclick: () => modalInstance.close()
      }, isAr ? 'إغلاق' : 'Close')
    ]));

  } catch (err) {
    modalContainer.innerHTML = '';
    modalContainer.append(errorState(err.message, () => openTeamMembersModal(team, isAr, reloadTab)));
  }
}
