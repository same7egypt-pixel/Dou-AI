// Integration — where a platform's data actually arrives.
//
// The whole ingestion pipeline existed in the backend and was reachable from no
// screen: seventeen endpoints under /sources, source platforms, connections,
// identity mappings, raw rows and normalized delivery facts, none of them
// touched by a single line of frontend code. An operator could not see what had
// arrived, what had failed, or why — and a delivery fact is what payroll pays
// on.
//
// Five tabs, in the order the operator needs them: what feeds us, what key it
// uses, who the riders are on the other side, what arrived, and what it became.
import { api } from '../../shared/api/client.js';
import { el, loadingState, emptyState, errorState, metricCard, modal, table, badge } from '../../shared/components/ui.js';
import { getLang } from '../../shared/i18n/i18n.js';

let activeTab = 'sources';
let selectedPlatform = '';

const T = {
  ar: {
    kicker: 'التكامل ومصادر البيانات',
    title: 'استقبال البيانات من المنصات',
    refresh: '↻ تحديث',
    tabs: {
      sources: '🔌 المصادر والاتصالات',
      keys: '🔑 مفاتيح الـAPI',
      riders: '🧑‍✈️ مطابقة هويات المناديب',
      rows: '📥 الصفوف الواردة',
      facts: '✅ التوصيلات المعتمدة',
    },
  },
  en: {
    kicker: 'Integration & Data Sources',
    title: 'Platform Data Ingestion',
    refresh: '↻ Refresh',
    tabs: {
      sources: '🔌 Sources & Connections',
      keys: '🔑 API Keys',
      riders: '🧑‍✈️ Rider Identity Mapping',
      rows: '📥 Incoming Rows',
      facts: '✅ Accepted Deliveries',
    },
  },
};

export async function renderIntegration(container) {
  const isAr = getLang() === 'ar';
  const L = isAr ? T.ar : T.en;
  container.innerHTML = '';

  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, L.kicker),
      el('h1', { text: L.title })
    ]),
    el('div', { class: 'header-actions' }, [
      el('button', { class: 'btn btn-ghost', onclick: () => renderIntegration(container) }, L.refresh)
    ])
  ]));

  const tabs = ['sources', 'keys', 'riders', 'rows', 'facts'];
  container.append(el('div', { class: 'tabs', style: 'margin-bottom:16px' },
    tabs.map(id => el('button', {
      class: `tab ${activeTab === id ? 'active' : ''}`,
      onclick: () => { activeTab = id; renderIntegration(container); }
    }, L.tabs[id]))
  ));

  const area = el('div', { id: 'integration-content' });
  container.append(area);

  const render = {
    sources: renderSources, keys: renderKeys, riders: renderRiderMappings,
    rows: renderRawRows, facts: renderFacts,
  }[activeTab];
  render(area, container);
}

// ── المصادر والاتصالات ──────────────────────────────────────────────────────
async function renderSources(area, container) {
  area.append(loadingState('جاري تحميل المصادر...'));
  try {
    const [platforms, connections] = await Promise.all([
      api.get('/sources/platforms'),
      api.get('/sources/connections').catch(() => []),
    ]);
    area.innerHTML = '';

    area.append(el('div', { style: 'display:flex;justify-content:flex-end;margin-bottom:12px;gap:8px' }, [
      el('button', { class: 'btn btn-primary', onclick: () => openSourceModal(container) }, '➕ إضافة مصدر بيانات'),
    ]));

    if (!platforms.length) {
      area.append(emptyState('لا توجد مصادر بيانات بعد. أضف المنصة التي ستُرسل لك بيانات التوصيل — نينجا، هنقرستيشن، أو أي مصدر آخر.'));
      return;
    }

    platforms.forEach(p => {
      const conns = connections.filter(c => c.source_platform_id === p.id);
      area.append(el('div', { class: 'card', style: 'padding:16px;margin-bottom:12px;border:1px solid var(--border);border-radius:12px;background:var(--card)' }, [
        el('div', { style: 'display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px' }, [
          el('div', {}, [
            el('div', { style: 'display:flex;align-items:center;gap:8px' }, [
              el('h3', { style: 'margin:0;font-size:15px;color:var(--text)' }, `🔌 ${p.name_ar || p.code}`),
              el('span', { class: `badge ${p.is_active ? 'badge-green' : ''}` }, p.is_active ? '● فعّال' : '○ متوقف'),
            ]),
            el('div', { style: 'font-size:12px;color:var(--muted);margin-top:4px' },
              `الرمز: ${p.code} | عدد الاتصالات: ${conns.length}`)
          ]),
          el('button', { class: 'btn btn-ghost btn-small', onclick: () => openConnectionModal(container, p) },
            '➕ إضافة اتصال'),
        ]),
        conns.length ? el('div', { style: 'margin-top:12px;border-top:1px solid var(--border);padding-top:10px;display:grid;gap:6px' },
          conns.map(c => el('div', { style: 'font-size:12px;color:var(--muted);display:flex;gap:10px;flex-wrap:wrap' }, [
            el('b', { style: 'color:var(--text)' }, c.connection_name),
            el('span', {}, `التكرار: ${c.import_frequency || '—'}`),
            el('span', {}, `آخر استيراد: ${c.last_import_at || '—'}`),
            el('span', { class: `badge ${c.is_active ? 'badge-green' : ''}` }, c.is_active ? 'فعّال' : 'متوقف'),
          ]))
        ) : null
      ].filter(Boolean)));
    });
  } catch (e) {
    area.innerHTML = '';
    area.append(errorState('تعذر تحميل المصادر: ' + e.message, () => renderSources(area, container)));
  }
}

// ── مفاتيح API ──────────────────────────────────────────────────────────────
async function renderKeys(area, container) {
  area.append(loadingState('جاري تحميل المفاتيح...'));
  try {
    const keys = await api.get('/enterprise/credentials?active_only=false');
    area.innerHTML = '';
    area.append(el('div', { style: 'display:flex;justify-content:flex-end;margin-bottom:12px' }, [
      el('button', { class: 'btn btn-primary', onclick: () => openKeyModal(container) }, '➕ إصدار مفتاح جديد'),
    ]));
    area.append(el('p', { style: 'font-size:12px;color:var(--muted);line-height:1.8;margin:0 0 12px' },
      'المفتاح يُعرض مرة واحدة فقط عند الإصدار ولا يمكن استرجاعه بعدها — يُخزَّن مجزّأً. ' +
      'إذا فُقد، دوّر المفتاح لإصدار بديل وإبطال القديم.'));

    if (!keys.length) {
      area.append(emptyState('لا توجد مفاتيح API بعد. أصدر مفتاحًا لتتمكن المنصة من إرسال بيانات التوصيل إليك.'));
      return;
    }
    area.append(table([
      { key: 'partner_name', label: 'الشريك' },
      { key: 'key_prefix', label: 'بادئة المفتاح', render: (v) => el('code', { style: 'font-size:12px' }, (v || '') + '…') },
      { key: 'scopes', label: 'النطاقات', render: (v) => el('span', { style: 'font-size:12px;color:var(--muted)' }, v || '—') },
      { key: 'rate_limit_per_minute', label: 'الحد/دقيقة', render: (v) => String(v ?? '—') },
      { key: 'last_rotated_at', label: 'آخر تدوير', render: (v) => (v ? String(v).slice(0, 10) : '—') },
      { key: 'is_active', label: 'الحالة', render: (v) => badge(v ? 'فعّال' : 'مُبطَل', v ? 'green' : 'red') },
      { key: 'id', label: '', render: (_v, k) => el('button', { class: 'btn btn-ghost btn-small', onclick: () => rotateKey(container, k) }, '🔄 تدوير') },
    ], keys));
  } catch (e) {
    area.innerHTML = '';
    area.append(errorState('تعذر تحميل المفاتيح: ' + e.message, () => renderKeys(area, container)));
  }
}

// ── مطابقة هويات المناديب ───────────────────────────────────────────────────
async function renderRiderMappings(area, container) {
  area.append(loadingState('جاري تحميل المطابقات...'));
  try {
    const [mappings, couriersPage, platforms] = await Promise.all([
      api.get('/sources/rider-mappings'),
      api.get('/fleet/couriers/page?page=1&page_size=200').catch(() => ({ rows: [] })),
      api.get('/sources/platforms').catch(() => []),
    ]);
    const couriers = couriersPage.rows || [];
    const byId = new Map(couriers.map(c => [c.id, c]));
    area.innerHTML = '';

    area.append(el('p', { style: 'font-size:12px;color:var(--muted);line-height:1.8;margin:0 0 12px' },
      'المنصة تعرف المندوب بمعرّفها هي، وDOU يعرفه بسجلّه. المطابقة هي ما يجعل توصيلة قادمة من ' +
      'المنصة تُحتسب للمندوب الصحيح في الرواتب. أي صف يصل بمعرّف غير مطابق يُرفض ويظهر في «الصفوف الواردة».'));

    area.append(el('div', { style: 'display:flex;justify-content:flex-end;margin-bottom:12px' }, [
      el('button', { class: 'btn btn-primary', onclick: () => openMappingModal(container, platforms, couriers) },
        '➕ إضافة مطابقة'),
    ]));

    if (!mappings.length) {
      area.append(emptyState('لا توجد مطابقات هوية بعد.'));
      return;
    }
    area.append(table([
      { key: 'source_rider_id', label: 'معرّف المصدر', render: (v) => el('code', { style: 'font-size:12px' }, v) },
      { key: 'courier_id', label: 'المندوب في DOU', render: (v) => {
        const c = byId.get(v);
        return c ? `${c.name} — ${c.phone || '—'}` : `مندوب #${v}`;
      } },
      { key: 'match_method', label: 'طريقة المطابقة', render: (v) => v || '—' },
      { key: 'confidence', label: 'الثقة', render: (v) => (v != null ? String(v) : '—') },
      { key: 'effective_from', label: 'ساري من', render: (v) => v || '—' },
      { key: 'status', label: 'الحالة', render: (v) => badge(v === 'ACTIVE' ? 'فعّالة' : v, v === 'ACTIVE' ? 'green' : 'amber') },
    ], mappings));
  } catch (e) {
    area.innerHTML = '';
    area.append(errorState('تعذر تحميل المطابقات: ' + e.message, () => renderRiderMappings(area, container)));
  }
}

// ── الصفوف الواردة ──────────────────────────────────────────────────────────
async function renderRawRows(area, container) {
  area.append(loadingState('جاري تحميل الصفوف الواردة...'));
  try {
    const rows = await api.get('/sources/raw-rows');
    area.innerHTML = '';

    const counts = rows.reduce((acc, r) => { acc[r.status] = (acc[r.status] || 0) + 1; return acc; }, {});
    const rejected = counts.REJECTED || 0;

    area.append(el('div', { class: 'cards', style: 'margin-bottom:16px' }, [
      metricCard(rows.length, 'إجمالي الصفوف الواردة', 'blue'),
      metricCard(counts.NORMALIZED || 0, 'تحوّلت إلى توصيلات معتمدة', 'good'),
      metricCard(rejected, 'مرفوضة — تحتاج تدخّلًا', rejected ? 'trend' : 'blue'),
      metricCard(counts.PENDING || 0, 'بانتظار المعالجة', 'blue'),
    ]));

    area.append(el('div', { style: 'display:flex;justify-content:flex-end;margin-bottom:12px;gap:8px' }, [
      el('button', { class: 'btn btn-primary', onclick: () => reprocess(container) },
        '🔄 إعادة معالجة الصفوف غير المعتمدة'),
    ]));

    if (!rows.length) {
      area.append(emptyState('لم تصل أي صفوف بعد. بمجرد أن ترسل المنصة أول دفعة ستظهر هنا بحالتها.'));
      return;
    }

    // The reason a row failed is the entire value of this tab: it names the
    // mapping the operator has to add, then reprocess.
    area.append(table([
      { key: 'source_id', label: 'المعرّف من المصدر', render: (v) => el('code', { style: 'font-size:12px' }, v) },
      { key: 'status', label: 'الحالة', render: (v) => badge(
        v === 'NORMALIZED' ? 'معتمد' : v === 'REJECTED' ? 'مرفوض' : v,
        v === 'NORMALIZED' ? 'green' : v === 'REJECTED' ? 'red' : 'amber'
      ) },
      { key: 'validation_issues', label: 'سبب الرفض', render: (v) => el(
        'span', { style: 'font-size:12px;color:var(--muted)' },
        (v || []).map(i => i.reason).join(' · ') || '—'
      ) },
      { key: 'created_at', label: 'وصل في', render: (v) => String(v || '').slice(0, 16).replace('T', ' ') },
    ], rows.slice(0, 200)));
  } catch (e) {
    area.innerHTML = '';
    area.append(errorState('تعذر تحميل الصفوف: ' + e.message, () => renderRawRows(area, container)));
  }
}

// ── التوصيلات المعتمدة ──────────────────────────────────────────────────────
async function renderFacts(area, container) {
  area.append(loadingState('جاري تحميل التوصيلات...'));
  try {
    const [facts, couriersPage] = await Promise.all([
      api.get('/sources/delivery-facts'),
      api.get('/fleet/couriers/page?page=1&page_size=200').catch(() => ({ rows: [] })),
    ]);
    const byId = new Map((couriersPage.rows || []).map(c => [c.id, c]));
    area.innerHTML = '';

    area.append(el('p', { style: 'font-size:12px;color:var(--muted);line-height:1.8;margin:0 0 12px' },
      'هذه هي التوصيلات التي تُحتسب في الرواتب والتقارير. كل توصيلة مرتبطة بالصف الخام الذي أنتجها، ' +
      'فيمكن تتبّع أي رقم في كشف الراتب حتى مصدره الأصلي.'));

    if (!facts.length) {
      area.append(emptyState('لا توجد توصيلات معتمدة بعد.'));
      return;
    }
    area.append(table([
      { key: 'source_delivery_id', label: 'معرّف التوصيلة', render: (v) => el('code', { style: 'font-size:12px' }, v) },
      { key: 'courier_id', label: 'المندوب', render: (v) => {
        const c = byId.get(v);
        return c ? c.name : (v ? `مندوب #${v}` : '—');
      } },
      { key: 'event_type', label: 'الحالة', render: (v) => badge(v === 'COMPLETED' ? 'مكتملة' : v, v === 'COMPLETED' ? 'green' : 'amber') },
      { key: 'event_date', label: 'التاريخ', render: (v) => v || '—' },
      { key: 'distance_km', label: 'المسافة', render: (v) => (v != null ? `${v} كم` : '—') },
      { key: 'revenue_amount', label: 'الإيراد', render: (v) => (v != null ? `${v} ر.س` : '—') },
      { key: 'raw_row_id', label: 'الصف الخام', render: (v) => (v ? `#${v}` : '—') },
    ], facts.slice(0, 200)));
  } catch (e) {
    area.innerHTML = '';
    area.append(errorState('تعذر تحميل التوصيلات: ' + e.message, () => renderFacts(area, container)));
  }
}

// ── الإجراءات ───────────────────────────────────────────────────────────────
async function reprocess(container) {
  if (!confirm('إعادة معالجة كل صف لم يتحوّل بعد إلى توصيلة معتمدة؟\n\n' +
    'الصفوف المعتمدة لا تُمس — إعادة المعالجة لا يمكن أن تحتسب توصيلة مرتين.')) return;
  try {
    const res = await api.post('/sources/raw-rows/reprocess');
    alert(`✅ تمت إعادة المعالجة.\n\nاعتُمد: ${res.normalized}\nما زال مرفوضًا: ${res.rejected}`);
    renderIntegration(container);
  } catch (e) {
    alert('❌ تعذرت إعادة المعالجة: ' + e.message);
  }
}

function openSourceModal(container) {
  const content = el('form', { style: 'display:grid;gap:14px;direction:rtl' }, [
    field('src-code', 'رمز المصدر (بالإنجليزية، بدون مسافات): *', { placeholder: 'NINJA', required: true }),
    field('src-name', 'اسم المصدر بالعربية: *', { placeholder: 'نينجا', required: true }),
    field('src-name-en', 'الاسم بالإنجليزية:', { placeholder: 'Ninja' }),
    el('p', { id: 'src-msg', style: 'margin:0;font-size:12px;min-height:16px' }),
    actions('src-submit', '💾 حفظ المصدر', () => m.remove()),
  ]);
  const m = modal('🔌 إضافة مصدر بيانات', content);
  content.onsubmit = submitter(content, 'src-msg', 'src-submit', m, container, async () => {
    await api.post('/sources/platforms', {
      code: content.querySelector('#src-code').value.trim().toUpperCase(),
      name_ar: content.querySelector('#src-name').value.trim(),
      name_en: content.querySelector('#src-name-en').value.trim() || null,
    });
    return '✅ تمت إضافة المصدر.';
  });
}

function openConnectionModal(container, platform) {
  const content = el('form', { style: 'display:grid;gap:14px;direction:rtl' }, [
    el('p', { style: 'margin:0;font-size:12px;color:var(--muted)' }, `اتصال جديد بمصدر «${platform.name_ar || platform.code}».`),
    field('cn-name', 'اسم الاتصال: *', { placeholder: 'استيراد يومي — الرياض', required: true }),
    el('div', {}, [
      label('cn-freq', 'تكرار الاستيراد:'),
      el('select', { id: 'cn-freq', style: inputStyle }, [
        el('option', { value: 'REALTIME' }, 'لحظي (API)'),
        el('option', { value: 'HOURLY' }, 'كل ساعة'),
        el('option', { value: 'DAILY', selected: true }, 'يومي'),
        el('option', { value: 'WEEKLY' }, 'أسبوعي'),
      ])
    ]),
    el('p', { id: 'cn-msg', style: 'margin:0;font-size:12px;min-height:16px' }),
    actions('cn-submit', '💾 حفظ الاتصال', () => m.remove()),
  ]);
  const m = modal('➕ إضافة اتصال', content);
  content.onsubmit = submitter(content, 'cn-msg', 'cn-submit', m, container, async () => {
    await api.post('/sources/connections', {
      source_platform_id: platform.id,
      connection_name: content.querySelector('#cn-name').value.trim(),
      import_frequency: content.querySelector('#cn-freq').value,
    });
    return '✅ تمت إضافة الاتصال.';
  });
}

function openKeyModal(container) {
  const content = el('form', { style: 'display:grid;gap:14px;direction:rtl' }, [
    field('key-partner', 'اسم الشريك: *', { placeholder: 'Ninja Dispatch API', required: true }),
    field('key-scopes', 'النطاقات (مفصولة بمسافة):', { value: 'performance:write' }),
    el('p', { id: 'key-msg', style: 'margin:0;font-size:12px;min-height:16px' }),
    el('div', { id: 'key-out' }),
    actions('key-submit', '🔑 إصدار المفتاح', () => m.remove()),
  ]);
  const m = modal('🔑 إصدار مفتاح API', content);
  content.onsubmit = async (e) => {
    e.preventDefault();
    const msg = content.querySelector('#key-msg');
    const btn = content.querySelector('#key-submit');
    btn.disabled = true;
    msg.style.color = 'var(--muted)';
    msg.textContent = '⏳ جاري الإصدار…';
    try {
      const res = await api.post('/enterprise/credentials', {
        partner_name: content.querySelector('#key-partner').value.trim(),
        scopes: content.querySelector('#key-scopes').value.trim(),
      });
      msg.textContent = '';
      // Shown once. The server stores only a hash, so there is no second chance
      // to read it — saying so here is more useful than a copy button.
      content.querySelector('#key-out').append(el('div', {
        style: 'background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px'
      }, [
        el('b', { style: 'display:block;color:var(--red);margin-bottom:6px' },
          '⚠️ انسخ المفتاح الآن — لن يُعرض مرة أخرى'),
        el('code', { style: 'display:block;word-break:break-all;font-size:12px;color:var(--text)' }, res.api_key),
      ]));
      btn.remove();
    } catch (err) {
      msg.style.color = 'var(--red)';
      msg.textContent = '❌ ' + err.message;
      btn.disabled = false;
    }
  };
}

async function rotateKey(container, key) {
  if (!confirm(`تدوير مفتاح «${key.partner_name}»؟\n\nسيتوقف المفتاح الحالي فورًا، ولن تصل بيانات المنصة حتى تُحدَّث لديها بالمفتاح الجديد.`)) return;
  try {
    const res = await api.post(`/enterprise/credentials/${key.id}/rotate`);
    const content = el('div', { style: 'direction:rtl' }, [
      el('b', { style: 'display:block;color:var(--red);margin-bottom:6px' }, '⚠️ انسخ المفتاح الآن — لن يُعرض مرة أخرى'),
      el('code', { style: 'display:block;word-break:break-all;font-size:12px' }, res.api_key),
    ]);
    modal('🔄 المفتاح الجديد', content);
  } catch (e) {
    alert('❌ تعذر التدوير: ' + e.message);
  }
}

function openMappingModal(container, platforms, couriers) {
  if (!platforms.length) { alert('أضف مصدر بيانات أولًا من تبويب «المصادر والاتصالات».'); return; }
  if (!couriers.length) { alert('لا يوجد مناديب في حسابك بعد.'); return; }
  const today = new Date().toISOString().slice(0, 10);
  const content = el('form', { style: 'display:grid;gap:14px;direction:rtl' }, [
    el('div', {}, [
      label('mp-platform', 'المصدر: *'),
      el('select', { id: 'mp-platform', required: true, style: inputStyle },
        platforms.map(p => el('option', { value: String(p.id) }, p.name_ar || p.code)))
    ]),
    field('mp-source-id', 'معرّف المندوب لدى المصدر: *', { placeholder: 'NINJA-C1', required: true }),
    el('div', {}, [
      label('mp-courier', 'المندوب في DOU: *'),
      el('select', { id: 'mp-courier', required: true, style: inputStyle },
        couriers.map(c => el('option', { value: String(c.id) }, `${c.name} — ${c.phone || '—'}`)))
    ]),
    field('mp-from', 'ساري من: *', { type: 'date', value: today, required: true }),
    el('p', { id: 'mp-msg', style: 'margin:0;font-size:12px;min-height:16px' }),
    actions('mp-submit', '💾 حفظ المطابقة', () => m.remove()),
  ]);
  const m = modal('🧑‍✈️ إضافة مطابقة هوية', content);
  content.onsubmit = submitter(content, 'mp-msg', 'mp-submit', m, container, async () => {
    await api.post('/sources/rider-mappings', {
      source_platform_id: Number(content.querySelector('#mp-platform').value),
      source_rider_id: content.querySelector('#mp-source-id').value.trim(),
      courier_id: Number(content.querySelector('#mp-courier').value),
      match_method: 'MANUAL',
      confidence: 1.0,
      effective_from: content.querySelector('#mp-from').value,
    });
    return '✅ تمت إضافة المطابقة. أعد معالجة الصفوف المرفوضة لتُحتسب.';
  });
}

// ── أدوات صغيرة ─────────────────────────────────────────────────────────────
const inputStyle = 'width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px';

function label(forId, text) {
  return el('label', { for: forId, style: 'display:block;font-size:12px;font-weight:700;margin-bottom:4px;color:var(--ink)' }, text);
}

function field(id, labelText, attrs = {}) {
  return el('div', {}, [
    label(id, labelText),
    el('input', { id, style: inputStyle, ...attrs })
  ]);
}

function actions(submitId, submitText, onCancel) {
  return el('div', { style: 'display:flex;justify-content:flex-end;gap:10px;margin-top:6px;padding-top:12px;border-top:1px solid var(--border)' }, [
    el('button', { type: 'button', class: 'btn btn-ghost', onclick: onCancel }, 'إلغاء'),
    el('button', { type: 'submit', class: 'btn btn-primary', id: submitId }, submitText),
  ]);
}

function submitter(content, msgId, btnId, m, container, work) {
  return async (e) => {
    e.preventDefault();
    const msg = content.querySelector('#' + msgId);
    const btn = content.querySelector('#' + btnId);
    btn.disabled = true;
    msg.style.color = 'var(--muted)';
    msg.textContent = '⏳ جاري الحفظ…';
    try {
      msg.style.color = 'var(--green)';
      msg.textContent = await work();
      setTimeout(() => { m.remove(); renderIntegration(container); }, 1200);
    } catch (err) {
      msg.style.color = 'var(--red)';
      msg.textContent = '❌ ' + err.message;
      btn.disabled = false;
    }
  };
}
