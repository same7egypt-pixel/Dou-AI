// DOU AI screen — Deterministic Conversational BI (no LLM hallucinations)
import { api } from '../../shared/api/client.js';
import { el, loadingState, emptyState, errorState, escapeHtml, badge } from '../../shared/components/ui.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

let conversationId = null;

export async function loadDouAI(container) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'ذكاء العمليات والأساطيل' : 'Operations & Fleet Intelligence'),
      el('h1', { text: isAr ? '✨ مساعد DOU AI' : '✨ DOU AI Assistant' })
    ]),
    el('div', { class: 'header-actions' }, [
      el('button', { class: 'btn btn-ghost', onclick: () => { conversationId = null; loadDouAI(container); } }, isAr ? '+ محادثة جديدة' : '+ New Conversation'),
    ]),
  ]));

  const layout = el('div', { class: 'ai-shell' }, [
    el('div', { class: 'ai-panel' }, [
      el('div', { class: 'ai-head' }, [
        el('div', {}, [
          el('h2', { text: isAr ? 'مساعد العمليات الميدانية والتحليلات' : 'Field Operations & Analytics Assistant' }),
          el('p', { text: isAr ? 'استفسر لحظياً عن الحضور، الورديات، أداء السائقين، الاستثناءات المفتوحة، ومسير الرواتب.' : 'Query real-time attendance, shifts, driver performance, open exceptions, and payroll.' })
        ]),
        badge(isAr ? 'بيانات موثقة 100%' : '100% Verified Data', 'green'),
      ]),
      el('div', { class: 'ai-messages', id: 'ai-messages' }, [
        el('div', { class: 'ai-empty' }, [
          el('div', { style: 'font-size:36px;margin-bottom:10px' }, '✨'),
          el('b', { text: isAr ? 'كيف يمكنني مساعدتك في إدارة أسطولك اليوم؟' : 'How can I assist you with your fleet operations today?' }),
          el('span', { text: isAr ? 'جميع المؤشرات والجداول يتم استخراجها فورياً وبشكل محكم من بيانات DOU المصرح بها.' : 'All metrics and tables are generated deterministically from authorized DOU system data.' })
        ])
      ]),
      el('div', { class: 'ai-compose' }, [
        el('textarea', {
          id: 'ai-input',
          placeholder: isAr ? 'اكتب سؤالك التشغيلي (مثال: من هم السائقون الغائبون اليوم؟ أو ملخص الأداء هذا الأسبوع)...' : 'Type your operational query (e.g. Who is absent today? or Weekly performance summary)...',
          onkeydown: (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAI(); } }
        }),
        el('button', { class: 'btn btn-blue', id: 'ai-send', onclick: () => sendAI() }, isAr ? 'إرسال' : 'Send'),
      ]),
    ]),
    el('aside', { class: 'ai-side' }, [
      el('div', { class: 'card' }, [
        el('h3', { text: isAr ? '⚡ استفسارات سريعة مدعومة' : '⚡ Supported Quick Queries' }),
        el('div', { class: 'ai-prompts' }, [
          el('span', { style: 'font-size:11px;font-weight:700;color:var(--muted);margin-top:6px;display:block' }, isAr ? 'الاستثناءات والجاهزية:' : 'Exceptions & Readiness:'),
          el('button', { class: 'ai-prompt', onclick: () => askPrompt(isAr ? 'ما الذي يحتاج انتباهي اليوم؟' : 'What needs my attention today?') }, isAr ? '⚠️ ما الذي يحتاج انتباهي اليوم؟' : '⚠️ What needs my attention today?'),
          el('button', { class: 'ai-prompt', onclick: () => askPrompt(isAr ? 'كم عدد السائقين غير الجاهزين للعمل؟' : 'How many drivers are not ready for work?') }, isAr ? '🚫 السائقون غير الجاهزين للعمل' : '🚫 Drivers not operationally ready'),

          el('span', { style: 'font-size:11px;font-weight:700;color:var(--muted);margin-top:10px;display:block' }, isAr ? 'الحضور والورديات:' : 'Attendance & Shifts:'),
          el('button', { class: 'ai-prompt', onclick: () => askPrompt(isAr ? 'من هم السائقون الغائبون اليوم؟' : 'Who are the absent drivers today?') }, isAr ? '⏱️ السائقون الغائبون اليوم' : '⏱️ Absent drivers today'),
          el('button', { class: 'ai-prompt', onclick: () => askPrompt(isAr ? 'اتجاه الحضور آخر 7 أيام' : 'Attendance trend over last 7 days') }, isAr ? '📈 اتجاه الحضور آخر 7 أيام' : '📈 7-day attendance trend'),

          el('span', { style: 'font-size:11px;font-weight:700;color:var(--muted);margin-top:10px;display:block' }, isAr ? 'الأداء والمالية:' : 'Performance & Finance:'),
          el('button', { class: 'ai-prompt', onclick: () => askPrompt(isAr ? 'السائقون تحت المستهدف' : 'Drivers below target') }, isAr ? '🎯 السائقون تحت المستهدف' : '🎯 Drivers below target'),
          el('button', { class: 'ai-prompt', onclick: () => askPrompt(isAr ? 'تقرير الرواتب' : 'Payroll report') }, isAr ? '💰 ملخص الرواتب والخصومات' : '💰 Payroll & deductions summary'),
        ])
      ]),
      el('div', { class: 'card' }, [
        el('h3', { text: isAr ? 'حالة محرك الذكاء' : 'AI Engine Status' }),
        el('p', { id: 'ai-status', style: 'font-size:11.5px;color:var(--muted)' }, isAr ? 'جاهز للاستعلام' : 'Ready for queries')
      ]),
    ]),
  ]);

  container.append(layout);
  checkAIStatus();
}

async function checkAIStatus() {
  const isAr = getLang() === 'ar';
  try {
    const s = await api.get('/ai/status');
    const statusEl = document.getElementById('ai-status');
    if (statusEl) {
      if (s.available) {
        statusEl.textContent = isAr ? '● محرك التحليلات الحية متصل ومجهز' : '● Live analytics engine connected & ready';
      } else {
        statusEl.textContent = isAr ? '● تحليلات DOU المصرح بها جاهزة' : '● Authorized DOU deterministic engine ready';
      }
    }
  } catch (e) {
    const statusEl = document.getElementById('ai-status');
    if (statusEl) statusEl.textContent = isAr ? 'حالة الخدمة غير متاحة' : 'Service status unavailable';
  }
}

function askPrompt(text) {
  document.getElementById('ai-input').value = text;
  sendAI();
}

async function sendAI() {
  const isAr = getLang() === 'ar';
  const input = document.getElementById('ai-input');
  const btn = document.getElementById('ai-send');
  const question = input.value.trim();
  if (!question || btn.disabled) return;
  input.value = '';
  btn.disabled = true;
  btn.textContent = '...';

  const box = document.getElementById('ai-messages');
  box.querySelector('.ai-empty')?.remove();
  box.insertAdjacentHTML('beforeend', `<div class="ai-msg user">${escapeHtml(question)}</div>`);
  const loading = el('div', { class: 'ai-msg assistant' }, isAr ? 'DOU AI يسترجع ويحلل بيانات الأسطول...' : 'DOU AI is analyzing fleet operational data...');
  box.append(loading);
  box.scrollTop = box.scrollHeight;

  try {
    const data = await api.post('/ai/chat', { question, conversation_id: conversationId, context: { current_view: 'douai' } });
    conversationId = data.conversation_id;
    loading.remove();
    renderAIResponse(data);
  } catch (e) {
    loading.innerHTML = (isAr ? 'تعذر إكمال الطلب: ' : 'Failed to process request: ') + escapeHtml(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = isAr ? 'إرسال' : 'Send';
  }
}

function renderAIResponse(data) {
  const isAr = getLang() === 'ar';
  const box = document.getElementById('ai-messages');
  let html = `<div class="ai-msg assistant"><div>${escapeHtml(data.answer)}</div>`;
  if (data.kpis?.length) {
    html += `<div class="ai-kpis">${data.kpis.map((k) => `<div class="ai-kpi"><b>${escapeHtml(k.value)}</b><span>${escapeHtml(k.label)}</span></div>`).join('')}</div>`;
  }
  if (data.table?.rows?.length) {
    const cols = data.table.columns || [];
    html += `<div class="table-wrap" style="margin-top:10px"><table><thead><tr>${cols.map((c) => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead><tbody>${data.table.rows.slice(0, 20).map((r) => `<tr>${cols.map((c) => `<td>${escapeHtml(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  const sourceLabel = isAr ? 'المصدر: ' : 'Source: ';
  const freshnessLabel = isAr ? ' · الحداثة: ' : ' · Freshness: ';
  const latencyLabel = isAr ? ' · زمن الاستجابة: ' : ' · Latency: ';
  html += `<div class="ai-meta">${sourceLabel}${escapeHtml(data.source)}${freshnessLabel}${escapeHtml(data.freshness)}${latencyLabel}${escapeHtml(data.latency_ms)}ms</div></div>`;
  box.insertAdjacentHTML('beforeend', html);
  box.scrollTop = box.scrollHeight;
}
