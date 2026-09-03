// Shell — Main application shell with Navigation, Context Selector & Dynamic Views
import { api } from '../shared/api/client.js';
import { appStore, isDeliveryPlatform, can } from '../shared/state/store.js';
import { el, modal } from '../shared/components/ui.js';
import { openNotificationsModal } from '../shared/components/notifications.js';
import { t, getLang, toggleLang, setLang } from '../shared/i18n/i18n.js';

let currentView = 'commandCenter';
let viewLoaders = {};

const VIEW_LABELS_AR = {
  commandCenter: 'مركز القيادة',
  riders: 'السائقون وفريق العمل',
  rider360: 'ملف السائق 360',
  shifts: 'الورديات والحضور',
  needsAttention: 'يحتاج انتباه',
  capacity: 'تخطيط السعة',
  reports: 'التقارير والتحليلات',
  payroll: 'الرواتب والعمليات المالية',
  vendors: 'المورّدون والالتزام',
  platformLink: 'أدائي لدى المنصة',
  integration: 'التكامل ومصادر البيانات',
  douai: 'مساعد DOU AI',
  settings: 'الإعدادات',
};

const VIEW_LABELS_EN = {
  commandCenter: 'Command Center',
  riders: 'Drivers & Workforce',
  rider360: 'Driver 360',
  shifts: 'Shifts & Attendance',
  needsAttention: 'Needs Attention',
  capacity: 'Capacity Planning',
  reports: 'Reports & Analytics',
  payroll: 'Payroll & Settlements',
  vendors: 'Vendors & Compliance',
  platformLink: 'My Standing with the Platform',
  integration: 'Integration & Data Sources',
  douai: 'DOU AI Assistant',
  settings: 'Settings',
};

const VIEW_LABELS = VIEW_LABELS_AR;

const VIEW_ICONS = {
  commandCenter: '▦',
  riders: '◉',
  rider360: '👤',
  shifts: '◷',
  needsAttention: '⚠',
  capacity: '◫',
  reports: '📊',
  payroll: '💰',
  vendors: '🤝',
  platformLink: '🔗',
  integration: '🔌',
  douai: '✨',
  settings: '⚙',
};

const VIEW_GROUPS_AR = [
  { group: 'الرئيسية', views: ['commandCenter'] },
  { group: 'القوى العاملة', views: ['riders'] },
  { group: 'العمليات', views: ['shifts', 'capacity'] },
  { group: 'الأداء والامتثال', views: ['needsAttention', 'reports'] },
  { group: 'شبكة المورّدين', views: ['vendors', 'platformLink'] },
  { group: 'التكامل', views: ['integration'] },
  { group: 'المالية', views: ['payroll'] },
  { group: 'المساعد الذكي', views: ['douai'] },
  { group: 'الحساب', views: ['settings'] },
];

const VIEW_GROUPS_EN = [
  { group: 'MAIN', views: ['commandCenter'] },
  { group: 'WORKFORCE', views: ['riders'] },
  { group: 'OPERATIONS', views: ['shifts', 'capacity'] },
  { group: 'PERFORMANCE & COMPLIANCE', views: ['needsAttention', 'reports'] },
  { group: 'VENDOR NETWORK', views: ['vendors', 'platformLink'] },
  { group: 'INTEGRATION', views: ['integration'] },
  { group: 'FINANCE', views: ['payroll'] },
  { group: 'AI ASSISTANT', views: ['douai'] },
  { group: 'ACCOUNT', views: ['settings'] },
];

const VIEW_GROUPS = VIEW_GROUPS_AR;

export const CONTEXTUAL_PROMPTS_AR = {
  commandCenter: [
    'ملخص الأداء التشغيلي اليوم',
    'ما الذي يحتاج انتباهي اليوم؟',
    'كم عدد السائقين الغائبين اليوم؟',
    'السائقون تحت المستهدف',
  ],
  riders: [
    'من هم السائقون الأكثر جاهزية؟',
    'السائقون الذين تنتهي وثائقهم قريباً',
    'السائقون الموقوفون عن العمل',
  ],
  shifts: [
    'نسبة الحضور لورديات اليوم',
    'الورديات التي تعاني من نقص في السائقين',
    'طلبات الإجازات المعلقة',
  ],
  needsAttention: [
    'ما هي الحالات الحرجة التي تتطلب تدخلاً فورياً؟',
    'ملخص الوثائق المنتهية',
    'السائقون المتغيبون بدون إذن',
  ],
  capacity: [
    'توقعات السعة المطلوبة للأسبوع القادم',
    'هل يوجد عجز في أي وردية؟',
    'صحة المشغلين وشركات التشغيل',
  ],
  reports: [
    'تقرير الأداء الأسبوعي',
    'مقارنة أداء الفروع',
    'تحليل ساعات الذروة',
  ],
  payroll: [
    'تقرير الرواتب',
    'السائقون تحت المستهدف',
    'إجمالي الخصومات والسلف لهذا الشهر',
    'مستحقات عقود مشغلي 3PL',
  ],
  douai: [
    'ملخص شامل للأسطول',
    'توصيات لتحسين الكفاءة التشغيلية',
  ],
};

export const CONTEXTUAL_PROMPTS_EN = {
  commandCenter: [
    "Today's operational performance summary",
    'What needs my attention today?',
    'How many drivers are absent today?',
    'Drivers below target',
  ],
  riders: [
    'Who are the most ready drivers?',
    'Drivers whose documents expire soon',
    'Suspended drivers',
  ],
  shifts: [
    'Attendance rate for today\'s shifts',
    'Shifts facing driver shortage',
    'Pending leave requests',
  ],
  needsAttention: [
    'Critical cases requiring immediate action',
    'Expired documents summary',
    'Drivers absent without permission',
  ],
  capacity: [
    'Capacity forecast for next week',
    'Is there any shift deficit?',
    '3PL Operator and partner health',
  ],
  reports: [
    'Weekly performance report',
    'Branch performance comparison',
    'Peak hours analysis',
  ],
  payroll: [
    'Payroll summary report',
    'Drivers below target',
    'Total deductions and advances this month',
    '3PL Operator contract settlements',
  ],
  douai: [
    'Comprehensive fleet summary',
    'Recommendations for operational efficiency',
  ],
};

export function getViewLabel(view) {
  const isAr = getLang() === 'ar';
  const labels = isAr ? VIEW_LABELS_AR : VIEW_LABELS_EN;
  return labels[view] || view;
}

export const CONTEXTUAL_PROMPTS = CONTEXTUAL_PROMPTS_AR;

export function registerViewLoaders(loaders) {
  viewLoaders = loaders;
}

export function renderShell() {
  const root = document.getElementById('app');
  root.innerHTML = '';

  const sidebar = renderSidebar();
  const topBar = renderTopBar();
  const content = el('main', { class: 'content-area', id: 'content-area' });
  const aiDrawer = renderAIDrawer();
  const backdrop = el('div', {
    class: 'sidebar-backdrop',
    id: 'sidebar-backdrop',
    onclick: () => {
      const sb = document.getElementById('app-sidebar');
      const ov = document.getElementById('sidebar-backdrop');
      if (sb) sb.classList.remove('open');
      if (ov) ov.classList.remove('active');
    }
  });

  const layout = el('div', { class: 'fleet-app' }, [
    sidebar,
    backdrop,
    el('div', { class: 'main-area' }, [topBar, content]),
    aiDrawer,
  ]);

  root.append(layout);

  // Set up global navigation
  window.go = go;
  window.openAIDrawer = openAIDrawer;
  window.closeAIDrawer = closeAIDrawer;
  window.openRider360 = (id) => { window.__rider360InitialId = id; go('rider360'); };

  // Load initial view
  go(currentView);
}

function renderSidebar() {
  const isAr = getLang() === 'ar';
  const nav = el('nav', { class: 'side-nav' });
  const groups = isAr ? VIEW_GROUPS_AR : VIEW_GROUPS_EN;
  const labels = isAr ? VIEW_LABELS_AR : VIEW_LABELS_EN;

  // Which screens exist is a server decision, carried in tenant.capabilities.
  // A screen the account cannot use is absent, not disabled: a payroll screen
  // on a delivery platform would either sit empty or imply a financial
  // decision the platform does not make -- its vendors pay the riders.
  const REQUIRES = {
    payroll: 'RIDER_PAYROLL',
    vendors: 'MANAGE_OPERATORS',
    platformLink: 'VENDOR_PORTAL',
    integration: 'PERFORMANCE_API_INGESTION',
  };
  // Settings carries user management and the subscription, so it is a role
  // decision rather than a capability one. The backend enforces the same set;
  // this only keeps the nav honest about what the user can reach.
  const ROLE_ONLY = {
    settings: ['COMPANY', 'COMPANY_ADMIN'],
  };
  const currentRole = appStore.get().role || localStorage.getItem('dou_role_v2') || '';
  const permitted = (v) =>
    (!REQUIRES[v] || can(REQUIRES[v])) &&
    (!ROLE_ONLY[v] || ROLE_ONLY[v].includes(currentRole));

  groups.forEach((g) => {
    const views = g.views.filter(permitted);
    if (!views.length) return;
    nav.append(el('div', { class: 'nav-group' }, g.group));
    views.forEach((v) => {
      nav.append(el('button', {
        class: `nav-item ${v === currentView ? 'active' : ''}`,
        'data-view': v,
        onclick: () => go(v)
      }, [
        el('i', { text: VIEW_ICONS[v] }),
        el('span', { text: labels[v] || v })
      ]));
    });
  });

  return el('aside', { class: 'sidebar', id: 'app-sidebar' }, [
    el('div', { class: 'sidebar-brand', style: 'padding:18px 16px 14px 16px;display:flex;align-items:center;gap:10px;border-bottom:1px solid rgba(255,255,255,0.08)' }, [
      el('div', { style: 'width:32px;height:32px;border-radius:8px;background:linear-gradient(135deg, #ff8a55, #ff5a13);display:grid;place-items:center;color:#fff;font-weight:800;font-size:14px;' }, '↗'),
      el('div', {}, [
        el('b', { style: 'font-size:16px;color:#fff;letter-spacing:-0.5px;' }, 'DOU'),
        el('span', { style: 'font-size:10px;color:#88a0c4;display:block;letter-spacing:1px;font-weight:600' }, 'FLEET OS V2'),
      ])
    ]),
    nav,
    renderUserCard()
  ]);
}

function renderUserCard() {
  const isAr = getLang() === 'ar';
  const { user, tenant } = appStore.get();
  return el('div', { class: 'user-card' }, [
    el('div', { class: 'user-card-top' }, [
      el('div', { class: 'user-photo' }, '✓'),
      el('div', {}, [
        el('b', { text: user?.name || (isAr ? 'مدير الشركة' : 'Company Admin') }),
        el('small', { text: tenant?.name || (isAr ? 'شركة ديمو اللوجستية' : 'Demo Logistics') }),
      ])
    ]),
    el('button', { class: 'btn btn-ghost btn-small btn-full', onclick: () => { api.logout(); location.reload(); } }, isAr ? '🚪 تسجيل الخروج' : '🚪 Log Out'),
  ]);
}

function renderTopBar() {
  const isAr = getLang() === 'ar';
  const topActions = [];
  const isPlat = isDeliveryPlatform();

  // The operating model is decided when the account is created and arrives in
  // /fleet/me. There is deliberately no switcher: a mode the browser can change
  // is not a mode, and it showed accounts a product they had not bought.
  topActions.push(el('span', {
    class: 'badge badge-gray',
    style: 'font-size:11.5px;font-weight:700;padding:5px 12px;border-radius:20px',
    title: isAr ? 'نوع الحساب يُحدَّد عند إنشائه من لوحة إدارة DOU' : 'Account type is set at creation from the DOU admin console'
  }, isPlat
    ? (isAr ? '🌐 منصة توصيل' : '🌐 Delivery Platform')
    : (isAr ? '🏢 شركة أساطيل' : '🏢 Fleet Partner')));

  // 2. Operator Dropdown if in Platform Mode
  if (isPlat) {
    const activeOp = appStore.get().activeOperatorId || '';
    const ops = appStore.get().operators || [];
    const opSelect = el('select', {
      id: 'topbar-operator-select',
      class: 'input-select-operator',
      style: 'background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:6px 12px;font-size:13px;font-weight:600;cursor:pointer',
      onchange: (e) => {
        const val = e.target.value ? Number(e.target.value) : null;
        appStore.set({ activeOperatorId: val });
        const content = document.getElementById('content-area');
        if (content && viewLoaders[currentView]) viewLoaders[currentView](content);
      }
    }, [
      el('option', { value: '' }, isAr ? '🌐 كل شركات التشغيل (المنصة)' : '🌐 All 3PL Operating Partners'),
      ...ops.map(o => el('option', { value: String(o.operator_tenant_id), selected: String(o.operator_tenant_id) === String(activeOp) }, `🏢 ${o.name || o.operator_name || (isAr ? 'مشغل #' + o.operator_tenant_id : 'Operator #' + o.operator_tenant_id)}`))
    ]);
    topActions.push(opSelect);

    if (!ops.length) {
      api.get('/enterprise/operators').then((list) => {
        if (Array.isArray(list) && list.length) {
          appStore.set({ operators: list });
          const sel = document.getElementById('topbar-operator-select');
          if (sel) {
            sel.innerHTML = `<option value="">🌐 ${isAr ? 'كل شركات التشغيل (المنصة)' : 'All 3PL Operating Partners'}</option>`;
            list.forEach(o => {
              const opt = document.createElement('option');
              opt.value = String(o.operator_tenant_id);
              opt.textContent = `🏢 ${o.name || o.operator_name || (isAr ? 'مشغل #' + o.operator_tenant_id : 'Operator #' + o.operator_tenant_id)}`;
              if (String(o.operator_tenant_id) === String(appStore.get().activeOperatorId)) opt.selected = true;
              sel.appendChild(opt);
            });
          }
        }
      }).catch(() => {});
    }
  }

  // 3. Language Switcher Button (AR / EN)
  const currentLang = getLang();
  const nextLangLabel = currentLang === 'ar' ? 'English (EN)' : 'العربية (AR)';
  const langToggleBtn = el('button', {
    class: 'btn btn-ghost btn-small',
    id: 'btn-toggle-lang',
    style: 'font-weight:700;font-size:12px;border:1px solid var(--border);border-radius:20px;padding:5px 12px;cursor:pointer',
    title: currentLang === 'ar' ? 'Switch to English' : 'التحويل للغة العربية',
    onclick: () => {
      toggleLang();
    }
  }, `🌐 ${nextLangLabel}`);
  topActions.push(langToggleBtn);

  // 4. AI & Notifications
  topActions.push(
    el('button', {
      class: 'btn btn-ai',
      id: 'btn-open-ai-drawer',
      onclick: () => openAIDrawer()
    }, [
      el('span', { text: '✨' }),
      el('span', { text: isAr ? 'مساعد DOU' : 'DOU Assistant' })
    ]),
    el('button', {
      class: 'btn btn-ghost btn-small',
      style: 'position:relative;padding:8px 12px',
      onclick: () => openNotificationsModal()
    }, [
      el('span', { text: '🔔' }),
      el('span', { id: 'notif-count', class: 'notif-count', text: '' })
    ])
  );

  const hamburgerBtn = el('button', {
    class: 'btn btn-ghost btn-hamburger',
    id: 'btn-mobile-menu',
    'aria-label': 'Toggle Navigation',
    onclick: () => {
      const sb = document.getElementById('app-sidebar');
      const ov = document.getElementById('sidebar-backdrop');
      if (sb) sb.classList.toggle('open');
      if (ov) ov.classList.toggle('active');
    }
  }, '☰');

  return el('header', { class: 'top-bar' }, [
    el('div', { class: 'breadcrumb', style: 'display:flex;align-items:center;gap:10px' }, [
      hamburgerBtn,
      el('span', { style: 'color:var(--muted)' }, 'DOU Fleet OS / '),
      el('b', { id: 'crumb', text: getViewLabel(currentView) })
    ]),
    el('div', { class: 'top-actions' }, topActions),
  ]);
}

export function go(view) {
  if (!viewLoaders[view]) {
    console.warn(`View loader for "${view}" not registered.`);
    return;
  }
  currentView = view;

  // Close mobile sidebar on navigation
  const sb = document.getElementById('app-sidebar');
  const ov = document.getElementById('sidebar-backdrop');
  if (sb) sb.classList.remove('open');
  if (ov) ov.classList.remove('active');

  // Update nav active state
  document.querySelectorAll('.nav-item').forEach((b) => {
    b.classList.toggle('active', b.dataset.view === view);
  });

  // Update breadcrumb
  const crumb = document.getElementById('crumb');
  if (crumb) crumb.textContent = getViewLabel(view);

  // Render view
  const content = document.getElementById('content-area');
  if (content) {
    content.innerHTML = '';
    viewLoaders[view](content);
  }

  // Update contextual AI drawer
  updateAIDrawerContext(view);
}

// ─────────────────────────────────────────
// Contextual AI Assistant Drawer
// ─────────────────────────────────────────

function renderAIDrawer() {
  const messages = el('div', { class: 'ai-drawer-messages', id: 'ai-drawer-messages' });
  const prompts = el('div', { class: 'ai-drawer-prompts', id: 'ai-drawer-prompts-wrap' });
  const isAr = getLang() === 'ar';

  const input = el('input', {
    type: 'text',
    id: 'ai-drawer-input',
    placeholder: isAr ? 'اطرح سؤالاً عن أداء الأسطول، الحضور، الرواتب...' : 'Ask a question about fleet performance, attendance, payroll...',
    onkeydown: (e) => {
      if (e.key === 'Enter') sendAIMessage();
    }
  });

  const sendBtn = el('button', {
    class: 'btn btn-primary btn-small',
    onclick: () => sendAIMessage()
  }, isAr ? 'إرسال' : 'Send');

  const drawer = el('div', { class: 'ai-drawer', id: 'ai-drawer' }, [
    el('div', { class: 'ai-drawer-header' }, [
      el('div', {}, [
        el('div', { style: 'display:flex;align-items:center;gap:6px;' }, [
          el('span', { text: '✨' }),
          el('b', { text: isAr ? 'مساعد DOU الذكي' : 'DOU Smart AI Assistant' }),
          el('span', { class: 'badge badge-green', style: 'font-size:10px;' }, isAr ? 'متصل بالبيانات' : 'Live Connected'),
        ]),
        el('small', { id: 'ai-drawer-context', style: 'color:var(--muted);font-size:11px;' }, `${isAr ? 'السياق:' : 'Context:'} ${getViewLabel(currentView)}`),
      ]),
      el('button', { class: 'btn-close', onclick: () => closeAIDrawer() }, '✕'),
    ]),
    prompts,
    messages,
    el('div', { class: 'ai-drawer-footer' }, [input, sendBtn]),
  ]);

  return drawer;
}

export function openAIDrawer(initialPrompt = '') {
  const drawer = document.getElementById('ai-drawer');
  if (drawer) {
    drawer.classList.add('open');
    updateAIDrawerContext(currentView);
    if (initialPrompt) {
      const input = document.getElementById('ai-drawer-input');
      if (input) {
        input.value = initialPrompt;
        sendAIMessage();
      }
    }
  }
}

export function closeAIDrawer() {
  const drawer = document.getElementById('ai-drawer');
  if (drawer) drawer.classList.remove('open');
}

export function getContextualPrompts(view) {
  const isAr = getLang() === 'ar';
  const dict = isAr ? CONTEXTUAL_PROMPTS_AR : CONTEXTUAL_PROMPTS_EN;
  return dict[view] || dict.commandCenter || [];
}

function updateAIDrawerContext(view) {
  const label = document.getElementById('ai-drawer-context') || document.getElementById('ai-drawer-context-label');
  const isAr = getLang() === 'ar';
  if (label) label.textContent = `${isAr ? '📍 السياق الحالي: ' : '📍 Current Context: '}${getViewLabel(view)}`;

  const promptsContainer = document.getElementById('ai-drawer-prompts-wrap') || document.getElementById('ai-drawer-prompts');
  if (promptsContainer) {
    promptsContainer.innerHTML = '';
    const viewPrompts = getContextualPrompts(view);
    viewPrompts.forEach((p) => {
      promptsContainer.append(el('button', {
        class: 'ai-prompt-chip ai-chip',
        onclick: () => {
          const input = document.getElementById('ai-drawer-input');
          if (input) {
            input.value = p;
            sendAIMessage();
          }
        }
      }, p));
    });
  }
}

async function sendAIMessage() {
  const isAr = getLang() === 'ar';
  const input = document.getElementById('ai-drawer-input');
  const msgs = document.getElementById('ai-drawer-messages') || document.getElementById('ai-drawer-msgs');
  if (!input || !msgs) return;

  const query = input.value.trim();
  if (!query) return;

  msgs.append(el('div', { class: 'ai-bubble user ai-msg' }, [
    el('div', { class: 'ai-bubble-text', text: query }),
  ]));
  input.value = '';

  const loadingBubble = el('div', { class: 'ai-bubble assistant ai-msg' }, [
    el('div', { class: 'ai-bubble-text', style: 'color:var(--muted);' }, isAr ? 'جاري تحليل البيانات التشغيلية...' : 'Analyzing operational data...'),
  ]);
  msgs.append(loadingBubble);
  msgs.scrollTop = msgs.scrollHeight;

  try {
    const res = await api.post('/ai/chat', {
      question: query,
      context: { current_view: currentView, role: appStore.get().role }
    });

    loadingBubble.innerHTML = '';
    loadingBubble.append(
      el('div', { class: 'ai-bubble-text', text: res.answer || res.response || (isAr ? 'تم تحليل البيانات.' : 'Data analysis completed.') }),
      el('div', { class: 'ai-bubble-meta' }, [
        el('span', { text: `${isAr ? 'المصدر: ' : 'Source: '}${res.source || 'DOU AI'}` }),
        res.latency_ms ? el('span', { text: `${isAr ? ' · زمن الاستجابة: ' : ' · Latency: '}${res.latency_ms}ms` }) : null,
      ].filter(Boolean))
    );
  } catch (err) {
    loadingBubble.innerHTML = '';
    loadingBubble.append(el('div', { class: 'ai-bubble-text', style: 'color:var(--red);', text: (isAr ? 'تعذر الاتصال بالمساعد: ' : 'Failed to connect to AI Assistant: ') + err.message }));
  }

  msgs.scrollTop = msgs.scrollHeight;
}

