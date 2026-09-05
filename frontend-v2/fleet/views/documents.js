// Documents, KYC Pipeline & Expiry Radar — Frontend V2 (Screen 2 / 6)
import { api } from '../../shared/api/client.js';
import {
  el, loadingState, emptyState, errorState, modal, metricCard, badge, escapeHtml, showToast } from '../../shared/components/ui.js';
import { getLang } from '../../shared/i18n/i18n.js';

let activeSubTab = 'radar'; // 'radar' | 'review' | 'requirements'
let expiryFilter = 'ALL'; // 'ALL' | 'EXPIRED' | '30DAYS' | '60DAYS' | 'VALID'

export async function loadDocuments(container, tabOverride = null) {
  const isAr = getLang() === 'ar';
  if (tabOverride) activeSubTab = tabOverride;

  container.innerHTML = '';

  const headerActions = el('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, [
    el('button', {
      class: 'btn btn-ghost btn-small',
      onclick: () => loadDocuments(container, activeSubTab)
    }, isAr ? 'تحديث ↻' : 'Refresh ↻'),
    el('button', {
      class: 'btn btn-primary btn-small',
      onclick: () => openUploadDocumentModal(container)
    }, isAr ? '📤 رفع وثيقة مندوب' : '📤 Upload Rider Doc'),
  ]);

  const header = el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'الامتثال والتحقق والتنبيهات المبكرة' : 'KYC, Compliance & Proactive Expiry Alerts'),
      el('h1', { text: isAr ? 'الوثائق والامتثال والجاهزية (KYC)' : 'Documents, Compliance & KYC' }),
    ]),
    headerActions,
  ]);

  const tabsNav = el('div', { class: 'tabs', style: 'margin-bottom:16px' }, [
    el('button', {
      class: `tab ${activeSubTab === 'radar' ? 'active' : ''}`,
      onclick: () => { activeSubTab = 'radar'; renderDocumentsTab(contentArea, container); }
    }, isAr ? '🚨 رادار انتهاء الإقامات والرخص' : '🚨 Expiry Radar (Iqama/License)'),
    el('button', {
      class: `tab ${activeSubTab === 'review' ? 'active' : ''}`,
      onclick: () => { activeSubTab = 'review'; renderDocumentsTab(contentArea, container); }
    }, isAr ? '📋 طابور مراجعة وتدقيق الوثائق' : '📋 Document Review Queue'),
    el('button', {
      class: `tab ${activeSubTab === 'requirements' ? 'active' : ''}`,
      onclick: () => { activeSubTab = 'requirements'; renderDocumentsTab(contentArea, container); }
    }, isAr ? '⚙️ سياسات ومتطلبات الـ KYC' : '⚙️ KYC Rules & Requirements'),
  ]);

  const contentArea = el('div', { id: 'documents-content' });
  container.append(header, tabsNav, contentArea);

  await renderDocumentsTab(contentArea, container);
}

async function renderDocumentsTab(contentArea, mainContainer) {
  const isAr = getLang() === 'ar';
  contentArea.innerHTML = '';
  contentArea.append(loadingState(isAr ? 'جاري تحميل بيانات الوثائق والامتثال...' : 'Loading documents and compliance data...'));

  try {
    if (activeSubTab === 'radar') {
      await renderExpiryRadar(contentArea, mainContainer);
    } else if (activeSubTab === 'review') {
      await renderReviewQueue(contentArea, mainContainer);
    } else {
      await renderRequirements(contentArea, mainContainer);
    }
  } catch (err) {
    contentArea.innerHTML = '';
    // `/hr/couriers` admits company admins and supervisors, not operations. An
    // operations account reached this screen from the sidebar and was handed the
    // backend's raw English "Not allowed" — a wall with no explanation, in a
    // right-to-left Arabic interface. The supervisor workspace already answers
    // the same situation properly; this says the same thing.
    if (err.status === 403 || String(err.message).includes('Not allowed')) {
      contentArea.append(renderAccessDeniedBanner(isAr));
    } else {
      contentArea.append(errorState(err.message || (isAr ? 'فشل تحميل بيانات الوثائق' : 'Failed to load documents data'), () => renderDocumentsTab(contentArea, mainContainer)));
    }
  }
}

function renderAccessDeniedBanner(isAr) {
  return el('div', {
    class: 'card',
    style: 'padding:24px;border:1px solid #f59e0b;background:#fffbeb;border-radius:14px;text-align:center;'
  }, [
    el('div', { style: 'font-size:36px;margin-bottom:8px' }, '🔒'),
    el('h3', { style: 'font-size:16px;font-weight:800;color:#92400e;margin:0 0 8px' },
      isAr ? 'صلاحية ملفات المناديب مطلوبة' : 'Rider records access required'
    ),
    el('p', { style: 'font-size:13px;line-height:1.7;color:#b45309;margin:0' },
      isAr
        ? 'ملفات الوثائق والإقامات تُفتح بحساب مدير الشركة أو المشرف الميداني. حسابك الحالي لا يملك هذه الصلاحية — كلّم مدير الشركة لو محتاج تشوفها.'
        : 'Document and residency files open for a company admin or a field supervisor. Your account does not carry that permission — ask your company admin if you need access.'
    ),
  ]);
}

// ── TAB 1: رادار انتهاء الإقامات والرخص (THE PROACTIVE ALERT RADAR) ──
async function renderExpiryRadar(contentArea, mainContainer) {
  const isAr = getLang() === 'ar';
  // Fetch couriers with their document expiry dates calculated on backend
  const couriers = await api.get('/hr/couriers');

  contentArea.innerHTML = '';

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  let expiredCount = 0;
  let within30Count = 0;
  let within60Count = 0;
  let compliantCount = 0;

  const analyzed = couriers.map(c => {
    const alerts = [];

    // Iqama Expiry
    if (c.iqama_expiry) {
      const exp = new Date(c.iqama_expiry);
      const days = Math.ceil((exp - today) / (1000 * 60 * 60 * 24));
      if (days < 0) alerts.push({ doc: isAr ? 'الإقامة' : 'Iqama', days, date: c.iqama_expiry, level: 'EXPIRED' });
      else if (days <= 30) alerts.push({ doc: isAr ? 'الإقامة' : 'Iqama', days, date: c.iqama_expiry, level: '30DAYS' });
      else if (days <= 60) alerts.push({ doc: isAr ? 'الإقامة' : 'Iqama', days, date: c.iqama_expiry, level: '60DAYS' });
    } else {
      alerts.push({ doc: isAr ? 'الإقامة' : 'Iqama', days: null, date: null, level: 'MISSING' });
    }

    // Driving License Expiry
    if (c.license_expiry) {
      const exp = new Date(c.license_expiry);
      const days = Math.ceil((exp - today) / (1000 * 60 * 60 * 24));
      if (days < 0) alerts.push({ doc: isAr ? 'رخصة القيادة' : 'Driver License', days, date: c.license_expiry, level: 'EXPIRED' });
      else if (days <= 30) alerts.push({ doc: isAr ? 'رخصة القيادة' : 'Driver License', days, date: c.license_expiry, level: '30DAYS' });
      else if (days <= 60) alerts.push({ doc: isAr ? 'رخصة القيادة' : 'Driver License', days, date: c.license_expiry, level: '60DAYS' });
    }

    const highestRisk = alerts.some(a => a.level === 'EXPIRED') ? 'EXPIRED'
      : alerts.some(a => a.level === '30DAYS') ? '30DAYS'
      : alerts.some(a => a.level === '60DAYS') ? '60DAYS'
      : (alerts.some(a => a.level === 'MISSING') ? 'MISSING' : 'VALID');

    if (highestRisk === 'EXPIRED') expiredCount++;
    else if (highestRisk === '30DAYS') within30Count++;
    else if (highestRisk === '60DAYS') within60Count++;
    else compliantCount++;

    return { ...c, alerts, highestRisk };
  });

  // 1. KPI Cards
  const metricsGrid = el('div', { class: 'metrics-grid', style: 'margin-bottom:20px' }, [
    metricCard(couriers.length, isAr ? 'إجمالي المناديب' : 'Total Couriers', 'blue'),
    metricCard(
      expiredCount,
      isAr ? '🚨 منتهية الآن (غرامة / إيقاف)' : '🚨 Expired (Fines / Grounded)',
      expiredCount > 0 ? 'red' : 'green',
      () => { expiryFilter = 'EXPIRED'; renderFilteredCouriers(); }
    ),
    metricCard(
      within30Count,
      isAr ? '⚠️ تنتهي خلال 30 يوماً' : '⚠️ Expiring in 30 Days',
      within30Count > 0 ? 'amber' : 'green',
      () => { expiryFilter = '30DAYS'; renderFilteredCouriers(); }
    ),
    metricCard(
      within60Count,
      isAr ? '⏳ تنتهي خلال 60 يوماً' : '⏳ Expiring in 60 Days',
      within60Count > 0 ? 'blue' : 'green',
      () => { expiryFilter = '60DAYS'; renderFilteredCouriers(); }
    ),
    metricCard(compliantCount, isAr ? '🟢 مطابقة وسارية' : '🟢 Compliant', 'green', () => { expiryFilter = 'VALID'; renderFilteredCouriers(); }),
  ]);

  // 2. Alert Banner
  let alertBanner = null;
  if (expiredCount > 0 || within30Count > 0) {
    alertBanner = el('div', {
      class: 'card',
      style: `margin-bottom:16px;padding:12px 18px;border-radius:10px;display:flex;align-items:center;gap:12px;${
        expiredCount > 0
          ? 'background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.3);color:var(--red)'
          : 'background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.3);color:var(--amber)'
      }`
    }, [
      el('span', { style: 'font-size:26px' }, expiredCount > 0 ? '🚨' : '⚠️'),
      el('div', { style: 'flex:1' }, [
        el('b', { style: 'display:block;font-size:14px;margin-bottom:2px' },
          expiredCount > 0
            ? (isAr ? `تنبيه امتثال حرج: يوجد ${expiredCount} مندوب بوثائق منتهية (إقامة / رخصة). هذا يعرض الشركة لغرامات منصة قوى والجوازات وتوقف المناديب.` : `Critical Compliance Alert: ${expiredCount} couriers have expired documents (Iqama/License). Risk of Qiwa fines and grounded operations.`)
            : (isAr ? `تنبيه تجديد مبكر: يوجد ${within30Count} مندوب تنتهي إقاماتهم خلال 30 يوماً. باشر بإجراءات سداد الرسوم والتجديد.` : `Early Renewal Warning: ${within30Count} couriers with Iqamas expiring within 30 days. Initiate renewal fees.`)
        ),
        el('span', { style: 'font-size:12px;opacity:0.9' },
          isAr ? 'اضغط على زر "تحديث التاريخ" أو "رفع وثيقة" لتسجيل الإقامة المجددة فور صدورها.' : 'Click "Update Date" or "Upload Doc" to register the renewed document.'
        )
      ])
    ]);
  }

  // 3. Filter Buttons
  const filterRow = el('div', { class: 'tabs', style: 'margin-bottom:16px;display:flex;gap:6px;overflow-x:auto' }, [
    el('button', { class: `tab ${expiryFilter === 'ALL' ? 'active' : ''}`, onclick: () => { expiryFilter = 'ALL'; renderFilteredCouriers(); } }, isAr ? `الكل (${couriers.length})` : `All (${couriers.length})`),
    el('button', { class: `tab ${expiryFilter === 'EXPIRED' ? 'active' : ''}`, onclick: () => { expiryFilter = 'EXPIRED'; renderFilteredCouriers(); } }, isAr ? `🚨 منتهية (${expiredCount})` : `🚨 Expired (${expiredCount})`),
    el('button', { class: `tab ${expiryFilter === '30DAYS' ? 'active' : ''}`, onclick: () => { expiryFilter = '30DAYS'; renderFilteredCouriers(); } }, isAr ? `⚠️ تنتهي خلال 30 يوماً (${within30Count})` : `⚠️ 30 Days (${within30Count})`),
    el('button', { class: `tab ${expiryFilter === '60DAYS' ? 'active' : ''}`, onclick: () => { expiryFilter = '60DAYS'; renderFilteredCouriers(); } }, isAr ? `⏳ تنتهي خلال 60 يوماً (${within60Count})` : `⏳ 60 Days (${within60Count})`),
    el('button', { class: `tab ${expiryFilter === 'VALID' ? 'active' : ''}`, onclick: () => { expiryFilter = 'VALID'; renderFilteredCouriers(); } }, isAr ? `🟢 سارية ومطابقة (${compliantCount})` : `🟢 Valid (${compliantCount})`),
  ]);

  const cardsContainer = el('div', {
    style: 'display:grid;grid-template-columns:repeat(auto-fill, minmax(360px, 1fr));gap:16px'
  });

  function renderFilteredCouriers() {
    filterRow.querySelectorAll('.tab').forEach((b, idx) => {
      const keys = ['ALL', 'EXPIRED', '30DAYS', '60DAYS', 'VALID'];
      if (keys[idx] === expiryFilter) b.classList.add('active');
      else b.classList.remove('active');
    });

    cardsContainer.innerHTML = '';
    const filtered = analyzed.filter(c => {
      if (expiryFilter === 'EXPIRED') return c.highestRisk === 'EXPIRED';
      if (expiryFilter === '30DAYS') return c.highestRisk === '30DAYS';
      if (expiryFilter === '60DAYS') return c.highestRisk === '60DAYS';
      if (expiryFilter === 'VALID') return c.highestRisk === 'VALID';
      return true;
    });

    if (!filtered.length) {
      cardsContainer.append(emptyState(isAr ? 'لا يوجد مناديب يطابقون هذا الفلتر.' : 'No couriers match this filter.'));
      return;
    }

    filtered.forEach(c => {
      cardsContainer.append(renderCourierComplianceCard(c, isAr, mainContainer));
    });
  }

  contentArea.append(metricsGrid);
  if (alertBanner) contentArea.append(alertBanner);
  contentArea.append(filterRow, cardsContainer);

  renderFilteredCouriers();
}

function renderCourierComplianceCard(c, isAr, mainContainer) {
  let riskBadge;
  if (c.highestRisk === 'EXPIRED') {
    riskBadge = el('span', { class: 'badge badge-red', style: 'font-weight:700' }, isAr ? '🚨 وثيقة منتهية' : '🚨 Expired Doc');
  } else if (c.highestRisk === '30DAYS') {
    riskBadge = el('span', { class: 'badge badge-amber', style: 'font-weight:700' }, isAr ? '⚠️ تجديد عاجل (30 يوم)' : '⚠️ Renew (30d)');
  } else if (c.highestRisk === '60DAYS') {
    riskBadge = el('span', { class: 'badge badge-blue', style: 'font-weight:700' }, isAr ? '⏳ تنبيه مسبق (60 يوم)' : '⏳ Notice (60d)');
  } else {
    riskBadge = el('span', { class: 'badge badge-green' }, isAr ? '🟢 أوراق سارية' : '🟢 Compliant');
  }

  const card = el('div', {
    class: 'card',
    style: `background:var(--card);border:1px solid ${c.highestRisk === 'EXPIRED' ? 'rgba(239,68,68,0.4)' : 'var(--border)'};border-radius:12px;padding:16px;display:flex;flex-direction:column;justify-content:space-between;gap:12px`
  }, [
    el('div', {}, [
      el('div', { style: 'display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px' }, [
        el('div', {}, [
          el('b', { style: 'font-size:15px;color:var(--ink)' }, `🛵 ${c.name}`),
          el('div', { style: 'font-size:12px;color:var(--muted);margin-top:2px' }, `📱 ${c.phone} • ${c.work_city || 'الرياض'}`),
        ]),
        riskBadge
      ]),

      // Document Status Breakdown
      el('div', { style: 'background:var(--surface2, #f8fafc);border-radius:8px;padding:10px;margin:8px 0;font-size:12px;display:flex;flex-direction:column;gap:6px' }, [
        el('div', { style: 'display:flex;justify-content:space-between;align-items:center' }, [
          el('span', { style: 'color:var(--muted)' }, isAr ? 'صلاحية الإقامة:' : 'Iqama Expiry:'),
          renderExpiryPill(c.iqama_expiry, isAr)
        ]),
        el('div', { style: 'display:flex;justify-content:space-between;align-items:center' }, [
          el('span', { style: 'color:var(--muted)' }, isAr ? 'رخصة القيادة:' : 'Driver License:'),
          renderExpiryPill(c.license_expiry, isAr)
        ]),
        el('div', { style: 'display:flex;justify-content:space-between;align-items:center' }, [
          el('span', { style: 'color:var(--muted)' }, isAr ? 'رخصة سير المركبة:' : 'Vehicle License:'),
          renderExpiryPill(c.vehicle_license_expiry, isAr)
        ]),
      ])
    ]),

    el('div', { style: 'display:flex;gap:6px;border-top:1px dashed var(--border);padding-top:10px' }, [
      el('button', {
        class: 'btn btn-small btn-primary',
        style: 'flex:1',
        onclick: () => openUpdateDatesModal(c, mainContainer)
      }, isAr ? '✏️ تحديث التواريخ' : '✏️ Update Dates'),
      el('button', {
        class: 'btn btn-small btn-ghost',
        onclick: () => openRiderDocsDrawer(c, mainContainer)
      }, isAr ? '📁 الوثائق المرفوعة' : '📁 Uploaded Docs'),
    ])
  ]);

  return card;
}

function renderExpiryPill(dateStr, isAr) {
  if (!dateStr) {
    return el('span', { class: 'badge badge-gray', style: 'font-size:11px' }, isAr ? 'غير مسجل' : 'Not recorded');
  }

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const exp = new Date(dateStr);
  const days = Math.ceil((exp - today) / (1000 * 60 * 60 * 24));

  if (days < 0) {
    return el('span', { class: 'badge badge-red', style: 'font-weight:700;font-size:11px' },
      isAr ? `منتهية منذ ${Math.abs(days)} يوم (${dateStr})` : `Expired ${Math.abs(days)}d ago`
    );
  } else if (days <= 30) {
    return el('span', { class: 'badge badge-amber', style: 'font-weight:700;font-size:11px' },
      isAr ? `باقي ${days} يوم (${dateStr})` : `${days}d left (${dateStr})`
    );
  } else if (days <= 60) {
    return el('span', { class: 'badge badge-blue', style: 'font-size:11px' },
      isAr ? `باقي ${days} يوم` : `${days}d left`
    );
  } else {
    return el('span', { class: 'badge badge-green', style: 'font-size:11px' }, dateStr);
  }
}

// ── TAB 2: طابور مراجعة وتدقيق الوثائق (REVIEW QUEUE) ──
async function renderReviewQueue(contentArea, mainContainer) {
  const isAr = getLang() === 'ar';
  // Get all documents across riders for this tenant
  const couriers = await api.get('/hr/couriers');

  const allDocs = [];
  const courierDocsLists = await Promise.all(
    couriers.map(async (c) => {
      const docs = await api.get(`/documents/RIDER/${c.id}`);
      return docs.map(d => ({ ...d, courier_name: c.name, courier_id: c.id }));
    })
  );
  courierDocsLists.forEach(docs => allDocs.push(...docs));

  contentArea.innerHTML = '';

  const pendingDocs = allDocs.filter(d => d.status === 'PENDING');
  const reviewedDocs = allDocs.filter(d => d.status !== 'PENDING');

  const banner = el('div', { class: 'card', style: 'padding:14px 18px;margin-bottom:16px;background:var(--card);border:1px solid var(--border);display:flex;justify-content:space-between;align-items:center' }, [
    el('div', {}, [
      el('h3', { style: 'margin:0;font-size:15px;color:var(--ink)' }, isAr ? 'طابور التدقيق والاعتماد' : 'Audit & Verification Queue'),
      el('p', { style: 'margin:2px 0 0;font-size:12px;color:var(--muted)' },
        isAr ? 'مراجعة أوراق المناديب الجديدة والتأكد من مطابقتها قبل إدخالهم في الجدولة.' : 'Review new rider submissions and verify authenticity.'
      )
    ]),
    el('span', { class: `badge badge-${pendingDocs.length > 0 ? 'amber' : 'green'}`, style: 'font-size:13px;padding:4px 12px;font-weight:700' },
      isAr ? `${pendingDocs.length} وثيقة معلقة` : `${pendingDocs.length} Pending Docs`
    )
  ]);

  const list = el('div', { style: 'display:flex;flex-direction:column;gap:10px' });

  if (!allDocs.length) {
    list.append(emptyState(isAr ? 'لا توجد وثائق مرفوعة في النظام حالياً.' : 'No documents uploaded yet.'));
  } else {
    // Show pending first
    const sorted = [...pendingDocs, ...reviewedDocs];
    sorted.forEach(d => {
      list.append(renderDocumentReviewRow(d, isAr, mainContainer));
    });
  }

  contentArea.append(banner, list);
}

function renderDocumentReviewRow(doc, isAr, mainContainer) {
  const isPending = doc.status === 'PENDING';
  const isValid = doc.status === 'VALID';

  const row = el('div', {
    class: 'card',
    style: `background:var(--card);border:1px solid ${isPending ? 'var(--primary)' : 'var(--border)'};border-radius:10px;padding:12px 16px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px`
  }, [
    el('div', { style: 'display:flex;align-items:center;gap:12px' }, [
      el('span', { style: 'font-size:24px' }, '📄'),
      el('div', {}, [
        el('b', { style: 'font-size:14px;color:var(--ink)' }, doc.filename),
        el('div', { style: 'font-size:12px;color:var(--muted);margin-top:2px' },
          `👤 ${doc.courier_name} • ${isAr ? 'نوع الوثيقة:' : 'Type:'} ${doc.document_type_id} • ${doc.expiry_date ? `${isAr ? 'تنتهي:' : 'Expires:'} ${doc.expiry_date}` : ''}`
        ),
      ])
    ]),

    el('div', { style: 'display:flex;align-items:center;gap:8px' }, [
      el('span', {
        class: `badge badge-${isValid ? 'green' : (isPending ? 'amber' : 'red')}`,
        style: 'font-weight:700'
      }, doc.status),

      isPending ? el('button', {
        class: 'btn btn-small btn-primary',
        onclick: () => submitDocDecision(doc.id, 'VALID', mainContainer)
      }, isAr ? '✅ اعتماد صالحة' : '✅ Approve') : null,

      isPending ? el('button', {
        class: 'btn btn-small btn-ghost',
        style: 'color:var(--red)',
        onclick: () => submitDocDecision(doc.id, 'REJECTED', mainContainer)
      }, isAr ? '❌ رفض' : '❌ Reject') : null,
    ].filter(Boolean))
  ]);

  return row;
}

async function submitDocDecision(docId, decision, mainContainer) {
  const isAr = getLang() === 'ar';
  try {
    await api.post(`/documents/${docId}/review`, { decision, review_note: isAr ? 'تمت المراجعة والاعتماد' : 'Reviewed and approved' });
    showToast(isAr ? 'تم حفظ القرار بنجاح!' : 'Decision saved successfully!', 'success');
    await loadDocuments(mainContainer, 'review');
  } catch (err) {
    showToast(err.message || (isAr ? 'فشل حفظ القرار' : 'Failed to save decision'), 'error');
  }
}

// ── TAB 3: سياسات ومتطلبات الـ KYC ──
async function renderRequirements(contentArea, mainContainer) {
  const isAr = getLang() === 'ar';
  const [types, reqs] = await Promise.all([
    api.get('/documents/types'),
    api.get('/documents/requirements')
  ]);

  contentArea.innerHTML = '';

  const headerBox = el('div', { class: 'card', style: 'padding:14px 18px;margin-bottom:16px;background:var(--card);border:1px solid var(--border);display:flex;justify-content:space-between;align-items:center' }, [
    el('div', {}, [
      el('h3', { style: 'margin:0;font-size:15px;color:var(--ink)' }, isAr ? 'قواعد الجاهزية والامتثال للمناديب' : 'Mandatory KYC Rules'),
      el('p', { style: 'margin:2px 0 0;font-size:12px;color:var(--muted)' },
        isAr ? 'تحديد الوثائق الإلزامية التي بدونها يعتبر المندوب غير جاهز للتشغيل.' : 'Configure required documents for active operational clearance.'
      )
    ]),
    el('button', {
      class: 'btn btn-primary btn-small',
      onclick: () => openAddRequirementModal(types, mainContainer)
    }, isAr ? '➕ إضافة متطلب إلزامي' : '➕ Add Requirement')
  ]);

  const list = el('div', { style: 'display:flex;flex-direction:column;gap:8px' });

  if (!reqs.length) {
    list.append(emptyState(isAr ? 'لا توجد سياسات KYC محددة.' : 'No KYC requirements configured.'));
  } else {
    reqs.forEach(r => {
      const matchedType = types.find(t => t.id === r.document_type_id);
      list.append(el('div', {
        class: 'card',
        style: 'padding:12px 16px;display:flex;justify-content:space-between;align-items:center;background:var(--card);border:1px solid var(--border);border-radius:10px'
      }, [
        el('div', {}, [
          el('b', { style: 'font-size:14px' }, matchedType ? matchedType.name_ar : `Doc Type #${r.document_type_id}`),
          el('div', { style: 'font-size:12px;color:var(--muted);margin-top:2px' },
            `${isAr ? 'النطاق:' : 'Scope:'} ${r.scope} • ${isAr ? 'السوق:' : 'Market:'} ${r.market_code}`
          )
        ]),
        el('span', { class: `badge badge-${r.is_mandatory ? 'red' : 'blue'}` },
          r.is_mandatory ? (isAr ? 'إلزامي للعمل ⚠️' : 'Mandatory ⚠️') : (isAr ? 'اختياري' : 'Optional')
        )
      ]));
    });
  }

  contentArea.append(headerBox, list);
}

// ── Modals: Update Dates, Upload Document, Add Requirement ──

function openUpdateDatesModal(courier, mainContainer) {
  const isAr = getLang() === 'ar';
  const overlay = modal(
    isAr ? `✏️ تحديث تواريخ وثائق المندوب (${courier.name})` : `✏️ Update Expiry Dates (${courier.name})`,
    el('form', { id: 'update-dates-form', style: 'display:flex;flex-direction:column;gap:12px' }, [
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'تاريخ انتهاء الإقامة (Iqama Expiry):' : 'Iqama Expiry:'),
        el('input', { class: 'input', name: 'iqama_expiry', type: 'date', value: courier.iqama_expiry || '', style: 'width:100%' }),
      ]),
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'تاريخ انتهاء رخصة القيادة (Driving License):' : 'Driving License Expiry:'),
        el('input', { class: 'input', name: 'license_expiry', type: 'date', value: courier.license_expiry || '', style: 'width:100%' }),
      ]),
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'تاريخ انتهاء رخصة سير المركبة (استمارة الدراجة):' : 'Vehicle License Expiry:'),
        el('input', { class: 'input', name: 'vehicle_license_expiry', type: 'date', value: courier.vehicle_license_expiry || '', style: 'width:100%' }),
      ]),
      el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:12px' }, [
        el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => overlay.remove() }, isAr ? 'إلغاء' : 'Cancel'),
        el('button', { type: 'submit', class: 'btn btn-primary', id: 'btn-save-dates' }, isAr ? 'حفظ التواريخ' : 'Save Dates')
      ])
    ])
  );

  const form = overlay.querySelector('#update-dates-form');
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = form.querySelector('#btn-save-dates');
    btn.disabled = true;
    btn.textContent = isAr ? 'جاري الحفظ...' : 'Saving...';

    const formData = new FormData(form);
    const payload = {
      iqama_expiry: formData.get('iqama_expiry') || null,
      license_expiry: formData.get('license_expiry') || null,
      vehicle_license_expiry: formData.get('vehicle_license_expiry') || null,
    };

    try {
      await api.patch(`/hr/couriers/${courier.id}`, payload);
      overlay.remove();
      showToast(isAr ? 'تم تحديث تواريخ الصلاحية بنجاح!' : 'Dates updated successfully!', 'success');
      await loadDocuments(mainContainer, 'radar');
    } catch (err) {
      btn.disabled = false;
      btn.textContent = isAr ? 'حفظ التواريخ' : 'Save Dates';
      showToast(err.message || (isAr ? 'فشل حفظ التواريخ' : 'Failed to save dates'), 'error');
    }
  };
}

async function openRiderDocsDrawer(courier, mainContainer) {
  const isAr = getLang() === 'ar';
  const overlay = modal(
    isAr ? `📁 وثائق المندوب: ${courier.name}` : `📁 Documents of ${courier.name}`,
    loadingState(isAr ? 'جاري تحميل وثائق المندوب...' : 'Loading rider documents...')
  );

  try {
    const docs = await api.get(`/documents/RIDER/${courier.id}`);
    const body = overlay.querySelector('.modal-body');
    body.innerHTML = '';

    if (!docs.length) {
      body.append(emptyState(isAr ? 'لا توجد وثائق مرفوعة لهذا المندوب.' : 'No documents uploaded for this courier.'));
      return;
    }

    const list = el('div', { style: 'display:flex;flex-direction:column;gap:8px' });
    docs.forEach(d => {
      list.append(el('div', {
        style: 'background:var(--surface2, #f8fafc);border-radius:8px;padding:10px 12px;display:flex;justify-content:space-between;align-items:center'
      }, [
        el('div', {}, [
          el('b', { style: 'font-size:13px' }, d.filename),
          el('div', { style: 'font-size:11px;color:var(--muted)' },
            `${isAr ? 'الصلاحية:' : 'Expiry:'} ${d.expiry_date || '—'} • ${d.created_at.slice(0, 10)}`
          )
        ]),
        el('span', { class: `badge badge-${d.status === 'VALID' ? 'green' : 'amber'}` }, d.status)
      ]));
    });

    body.append(list);
  } catch (err) {
    overlay.querySelector('.modal-body').innerHTML = '';
    overlay.querySelector('.modal-body').append(errorState(err.message));
  }
}

async function openUploadDocumentModal(mainContainer) {
  const isAr = getLang() === 'ar';
  const [couriers, types] = await Promise.all([
    api.get('/hr/couriers'),
    api.get('/documents/types')
  ]);

  const overlay = modal(
    isAr ? '📤 تسجيل ورفع وثيقة جديدة' : '📤 Upload New Document',
    el('form', { id: 'upload-doc-form', style: 'display:flex;flex-direction:column;gap:12px' }, [
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'اختر المندوب:' : 'Select Courier:'),
        el('select', { class: 'input', name: 'owner_id', required: true, style: 'width:100%' }, [
          el('option', { value: '' }, isAr ? '— اختر سائقاً —' : '— Select a courier —'),
          ...couriers.map(c => el('option', { value: String(c.id) }, `${c.name} (${c.phone || 'بدون جوال'})`))
        ])
      ]),
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'نوع الوثيقة:' : 'Document Type:'),
        el('select', { class: 'input', name: 'document_type_id', required: true, style: 'width:100%' }, [
          ...types.map(t => el('option', { value: String(t.id) }, `${t.name_ar} (${t.code})`))
        ])
      ]),
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'اسم الملف (مثال: iqama_mohamed.pdf):' : 'Filename:'),
        el('input', { class: 'input', name: 'filename', required: true, placeholder: 'iqama.pdf', style: 'width:100%' }),
      ]),
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'تاريخ انتهاء الصلاحية:' : 'Expiry Date:'),
        el('input', { class: 'input', name: 'expiry_date', type: 'date', required: true, style: 'width:100%' }),
      ]),
      el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:12px' }, [
        el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => overlay.remove() }, isAr ? 'إلغاء' : 'Cancel'),
        el('button', { type: 'submit', class: 'btn btn-primary', id: 'btn-submit-upload' }, isAr ? 'حفظ الوثيقة' : 'Save Document')
      ])
    ])
  );

  const form = overlay.querySelector('#upload-doc-form');
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = form.querySelector('#btn-submit-upload');
    btn.disabled = true;
    btn.textContent = isAr ? 'جاري الحفظ...' : 'Saving...';

    const formData = new FormData(form);
    const payload = {
      owner_type: 'RIDER',
      owner_id: Number(formData.get('owner_id')),
      document_type_id: Number(formData.get('document_type_id')),
      filename: formData.get('filename'),
      mime_type: 'application/pdf',
      file_size_bytes: 1024,
      expiry_date: formData.get('expiry_date') || null,
    };

    try {
      await api.post('/documents/upload', payload);
      overlay.remove();
      showToast(isAr ? 'تم تسجيل الوثيقة بنجاح وإرسالها لطابور التدقيق!' : 'Document uploaded successfully!', 'success');
      await loadDocuments(mainContainer, 'review');
    } catch (err) {
      btn.disabled = false;
      btn.textContent = isAr ? 'حفظ الوثيقة' : 'Save Document';
      showToast(err.message || (isAr ? 'فشل حفظ الوثيقة' : 'Failed to upload document'), 'error');
    }
  };
}

function openAddRequirementModal(types, mainContainer) {
  const isAr = getLang() === 'ar';
  const overlay = modal(
    isAr ? '➕ إضافة متطلب KYC إلزامي' : '➕ Add Mandatory KYC Rule',
    el('form', { id: 'add-req-form', style: 'display:flex;flex-direction:column;gap:12px' }, [
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'نوع الوثيقة:' : 'Document Type:'),
        el('select', { class: 'input', name: 'document_type_id', required: true, style: 'width:100%' }, [
          ...types.map(t => el('option', { value: String(t.id) }, `${t.name_ar} (${t.code})`))
        ])
      ]),
      el('div', {}, [
        el('label', { style: 'font-size:12px;font-weight:700;display:block;margin-bottom:4px' }, isAr ? 'النطاق:' : 'Scope:'),
        el('select', { class: 'input', name: 'scope', style: 'width:100%' }, [
          el('option', { value: 'RIDER' }, isAr ? 'للمندوب (RIDER)' : 'Rider'),
          el('option', { value: 'VEHICLE' }, isAr ? 'للمركبة (VEHICLE)' : 'Vehicle'),
        ])
      ]),
      el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:12px' }, [
        el('button', { type: 'button', class: 'btn btn-ghost', onclick: () => overlay.remove() }, isAr ? 'إلغاء' : 'Cancel'),
        el('button', { type: 'submit', class: 'btn btn-primary', id: 'btn-save-req' }, isAr ? 'تأكيد المتطلب' : 'Save Rule')
      ])
    ])
  );

  const form = overlay.querySelector('#add-req-form');
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = form.querySelector('#btn-save-req');
    btn.disabled = true;
    btn.textContent = isAr ? 'جاري الحفظ...' : 'Saving...';

    const formData = new FormData(form);
    const payload = {
      document_type_id: Number(formData.get('document_type_id')),
      scope: formData.get('scope'),
      market_code: 'SA',
      is_mandatory: true
    };

    try {
      await api.post('/documents/requirements', payload);
      overlay.remove();
      showToast(isAr ? 'تمت إضافة المتطلب الإلزامي بنجاح!' : 'Requirement added successfully!', 'success');
      await loadDocuments(mainContainer, 'requirements');
    } catch (err) {
      btn.disabled = false;
      btn.textContent = isAr ? 'تأكيد المتطلب' : 'Save Rule';
      showToast(err.message || (isAr ? 'فشل إضافة المتطلب' : 'Failed to add requirement'), 'error');
    }
  };
}
