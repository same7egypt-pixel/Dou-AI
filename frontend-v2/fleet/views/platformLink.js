// My standing with the platform — the vendor side of the portal.
//
// A vendor reaches this screen because a platform it works for opened its
// dashboard. It shows the vendor's own riders as that platform records them,
// its own lapsed documents, and where it ranks among the platform's other
// vendors — by position only. Peer names never cross the boundary, which is the
// condition that makes vendors willing to be measured at all.
//
// The vendor's own fleet, payroll and rider management stay where they are.
// This screen is an addition, not a replacement, so a platform closing the
// portal takes away a view and not a subscription.
import { api } from '../../shared/api/client.js';
import { el, loadingState, emptyState, errorState, metricCard, badge, table, showToast } from '../../shared/components/ui.js';
import { getLang } from '../../shared/i18n/i18n.js';
import { go } from '../shell.js';

let activePlatform = null;
let horizonDays = 30;

export async function renderPlatformLink(container) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';

  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'الربط مع المنصة' : 'Platform Link'),
      el('h1', { text: isAr ? 'أدائي لدى المنصة' : 'My Standing with the Platform' })
    ]),
    el('div', { class: 'header-actions' }, [
      el('button', { class: 'btn btn-ghost', onclick: () => renderPlatformLink(container) },
        isAr ? '↻ تحديث' : '↻ Refresh')
    ])
  ]));

  const pane = el('div', {}, [loadingState(isAr ? 'جاري التحميل...' : 'Loading...')]);
  container.append(pane);

  // 1. Check for incoming partnership invitations from delivery platforms
  try {
    const invites = await api.get('/enterprise/operators/invitations/incoming');
    const incomingList = Array.isArray(invites) ? invites : (invites.invitations || []);
    if (incomingList.length > 0) {
      const inviteCards = incomingList.map(inv => el('div', {
        class: 'card',
        style: 'background:var(--surface, #1e293b);border:2px solid var(--primary, #3b82f6);padding:16px 20px;margin-bottom:18px;border-radius:12px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px;box-shadow:0 4px 12px rgba(0,0,0,0.1);'
      }, [
        el('div', {}, [
          el('div', { style: 'font-weight:700;font-size:15px;color:var(--text, #fff);display:flex;align-items:center;gap:8px;' }, [
            el('span', { text: '📬' }),
            el('span', { text: isAr ? `دعوة شراكة رسمية من منصة: ${inv.platform_name || ('منصة #' + inv.platform_tenant_id)}` : `Official Partnership Invitation: ${inv.platform_name || ('Platform #' + inv.platform_tenant_id)}` })
          ]),
          el('div', { style: 'color:var(--muted);font-size:13px;margin-top:6px;' },
            isAr ? `نوع الشراكة: ${inv.relationship_type || 'مشغل لوجستي'} · تاريخ الإرسال: ${inv.invited_at ? new Date(inv.invited_at).toLocaleDateString('en-GB') : 'اليوم'}`
                 : `Relationship: ${inv.relationship_type || 'Operator'} · Invited: ${inv.invited_at ? new Date(inv.invited_at).toLocaleDateString() : 'Today'}`)
        ]),
        el('div', { style: 'display:flex;gap:10px;' }, [
          el('button', {
            class: 'btn btn-primary btn-small',
            style: 'padding:8px 16px;font-weight:600;',
            onclick: async () => {
              try {
                await api.post(`/enterprise/operators/invitations/${inv.id}/respond`, { action: 'ACCEPT' });
                showToast(isAr ? 'تم قبول الشراكة وتفعيل الربط بنجاح!' : 'Partnership accepted and activated!', 'success');
                renderPlatformLink(container);
              } catch (err) {
                showToast((isAr ? 'خطأ في قبول الدعوة: ' : 'Error: ') + (err.message || err), 'error');
              }
            }
          }, isAr ? '✅ قبول الشراكة' : '✅ Accept Partnership'),
          el('button', {
            class: 'btn btn-ghost btn-small',
            style: 'color:var(--red, #ef4444);padding:8px 14px;',
            onclick: async () => {
              if (confirm(isAr ? 'هل أنت متأكد من رفض دعوة الشراكة هذه؟' : 'Are you sure you want to decline this invitation?')) {
                try {
                  await api.post(`/enterprise/operators/invitations/${inv.id}/respond`, { action: 'REJECT' });
                  renderPlatformLink(container);
                } catch (err) {
                  showToast((isAr ? 'خطأ: ' : 'Error: ') + (err.message || err), 'error');
                }
              }
            }
          }, isAr ? '❌ رفض' : '❌ Decline')
        ])
      ]));
      container.insertBefore(el('div', { style: 'margin-bottom:14px;' }, inviteCards), pane);
    }
  } catch (err) {
    console.warn('Could not load incoming invitations', err);
  }

  try {
    const list = await api.get('/analytics/reports/vendor-portal/platforms');
    const platforms = list.platforms || [];
    if (!platforms.length) {
      pane.innerHTML = '';
      pane.append(emptyState(isAr
        ? 'لا توجد منصة مفعلة حالياً. تُفعَّل هذه الشاشة تلقائياً عند قبول دعوة الشراكة من المنصة التي تعمل معها.'
        : 'No platform active yet. This screen activates upon accepting a partnership invitation from your delivery platform.'));
      return;
    }
    if (!activePlatform || !platforms.some(p => p.platform_tenant_id === activePlatform)) {
      activePlatform = platforms[0].platform_tenant_id;
    }

    if (platforms.length > 1) {
      pane.innerHTML = '';
      container.insertBefore(el('div', { class: 'filters', style: 'margin-bottom:14px' },
        platforms.map(p => el('button', {
          class: `btn btn-small ${p.platform_tenant_id === activePlatform ? 'btn-primary' : 'btn-ghost'}`,
          onclick: () => { activePlatform = p.platform_tenant_id; renderPlatformLink(container); }
        }, p.platform))), pane);
    }

    await renderStanding(pane, isAr, platforms.find(p => p.platform_tenant_id === activePlatform));
  } catch (e) {
    pane.innerHTML = '';
    pane.append(errorState((isAr ? 'تعذر تحميل بيانات الربط: ' : 'Could not load: ') + e.message));
  }
}

function comparison(label, mine, peers, isAr, suffix = '%') {
  if (mine === null || mine === undefined) return null;
  const best = peers?.best, median = peers?.median;
  const tone = (best !== null && mine >= best) ? 'green' : (median !== null && mine >= median ? 'amber' : 'alert');
  return el('div', { style: 'padding:10px 0;border-bottom:1px solid var(--border)' }, [
    el('div', { style: 'display:flex;justify-content:space-between;align-items:center;gap:10px' }, [
      el('b', { style: 'font-size:13px' }, label),
      el('span', { class: `badge badge-${tone}`, style: 'font-size:12.5px' }, `${mine}${suffix}`)
    ]),
    el('small', { style: 'color:var(--muted);font-size:11.5px' },
      isAr ? `أفضل مورّد: ${best ?? '—'}${suffix} · الوسيط: ${median ?? '—'}${suffix}`
           : `Best: ${best ?? '—'}${suffix} · Median: ${median ?? '—'}${suffix}`)
  ]);
}

async function renderStanding(pane, isAr, platform) {
  const q = activePlatform ? `?platform_tenant_id=${activePlatform}` : '';
  const data = await api.get(`/analytics/reports/vendor-portal/standing${q}`);
  pane.innerHTML = '';

  if (!data.granted) {
    pane.append(emptyState(isAr ? 'انتهت صلاحية الإتاحة من هذه المنصة.' : 'Access from this platform has expired.'));
    return;
  }
  const s = data.standing;
  if (!s) {
    pane.append(emptyState(data.note || (isAr ? 'لا توجد بيانات لك في هذه الفترة.' : 'No data for this period.')));
    return;
  }

  pane.append(el('div', { class: 'cards' }, [
    metricCard(`${s.rank} / ${s.of}`, isAr ? 'ترتيبي بين المورّدين' : 'My Rank',
      s.rank === 1 ? 'trend' : (s.rank <= Math.ceil(s.of / 2) ? 'blue' : 'alert'), null,
      isAr ? 'مرتّب بالالتزام أولًا' : 'Ranked by compliance first'),
    metricCard(s.riders, isAr ? 'مناديبي لدى المنصة' : 'My Riders', 'blue', null,
      `${s.active_riders} ${isAr ? 'نشط' : 'active'}`),
    metricCard(s.orders_month, isAr ? 'طلبات الشهر' : 'Orders This Month', 'blue', null,
      s.target_achievement !== null ? `${s.target_achievement}% ${isAr ? 'من التارجت' : 'of target'}` : ''),
    metricCard(s.riders_expired, isAr ? 'وثائق منتهية' : 'Expired Documents',
      s.riders_expired > 0 ? 'alert' : 'trend', null,
      isAr ? 'مسؤوليتي أنا كمورّد' : 'My responsibility as vendor'),
  ]));

  pane.append(el('div', { class: 'card', style: 'margin-top:16px' }, [
    el('h3', { style: 'margin:0 0 4px 0;font-size:15px' },
      isAr ? '📊 موقعي مقارنة بالمورّدين الآخرين' : '📊 How I compare'),
    el('p', { style: 'margin:0 0 8px 0;font-size:12px;color:var(--muted)' },
      isAr ? 'تُعرض القيم دون أسماء المورّدين الآخرين.' : 'Values only; peer identities are never shown.'),
    comparison(isAr ? 'نسبة الحضور' : 'Attendance', s.attendance_rate, s.peers?.attendance, isAr),
    comparison(isAr ? 'نسبة الالتزام' : 'Compliance', s.compliance_rate, s.peers?.compliance, isAr),
    comparison(isAr ? 'إنجاز التارجت' : 'Target achievement', s.target_achievement, s.peers?.target, isAr),
  ].filter(Boolean)));

  if (platform?.expires) {
    pane.append(el('p', { style: 'margin-top:12px;font-size:12px;color:var(--muted)' },
      isAr ? `تنتهي إتاحة المنصة في ${platform.expires}` : `Platform access expires ${platform.expires}`));
  }

  await renderMyCompliance(pane, isAr);
}

async function renderMyCompliance(pane, isAr) {
  const q = activePlatform ? `platform_tenant_id=${activePlatform}&` : '';
  const data = await api.get(`/analytics/reports/vendor-portal/compliance?${q}horizon_days=${horizonDays}`);
  const rows = data.rows || [];

  pane.append(el('h3', { style: 'margin:22px 0 8px 0;font-size:15px' },
    isAr ? '🛡️ وثائق مناديبي التي تحتاج تجديدًا' : '🛡️ My riders needing renewal'));

  pane.append(el('div', { class: 'filters', style: 'margin-bottom:12px' },
    [7, 30, 60, 90].map(d => el('button', {
      class: `btn btn-small ${horizonDays === d ? 'btn-primary' : 'btn-ghost'}`,
      onclick: () => { horizonDays = d; renderPlatformLink(document.getElementById('content-area')); }
    }, isAr ? `${d} يومًا` : `${d} days`))));

  if (!rows.length) {
    pane.append(emptyState(isAr
      ? `لا توجد وثائق منتهية أو توشك خلال ${horizonDays} يومًا.`
      : `Nothing expiring within ${horizonDays} days.`));
    return;
  }

  pane.append(table([
    { key: 'severity', label: isAr ? 'الحالة' : 'Status', render: (v, r) => v === 'EXPIRED'
      ? el('span', { class: 'badge badge-alert' }, isAr ? `منتهٍ منذ ${Math.abs(r.days_remaining)} يومًا` : `Expired ${Math.abs(r.days_remaining)}d`)
      : el('span', { class: 'badge badge-amber' }, isAr ? `خلال ${r.days_remaining} يومًا` : `In ${r.days_remaining}d`) },
    { key: 'document', label: isAr ? 'الوثيقة' : 'Document', render: (v) => el('b', {}, v) },
    { key: 'rider_name', label: isAr ? 'المندوب' : 'Rider', render: (v, r) => el('div', {}, [
      el('b', { style: 'display:block;color:var(--text)' }, v || '—'),
      el('small', { style: 'color:var(--muted);font-size:11px' }, r.rider_phone || '')
    ]) },
    { key: 'expiry_date', label: isAr ? 'تاريخ الانتهاء' : 'Expiry', render: (v) => el('span', { style: 'font-variant-numeric:tabular-nums' }, v || '—') },
    { key: 'rider_id', label: isAr ? 'إجراء' : 'Action', render: (v) => el('button', {
      class: 'btn btn-ghost btn-small',
      onclick: () => { window.__rider360InitialId = v; window.__rider360InitialTab = 'documents'; go('rider360'); }
    }, isAr ? 'فتح الملف ➔' : 'Open ➔') },
  ], rows));
}
