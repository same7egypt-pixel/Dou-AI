// Shared notifications helper
import { api } from '../api/client.js';
import { el, modal, emptyState, badge } from './ui.js';

export async function refreshNotificationCount() {
  try {
    const data = await api.get('/notifications?unread_only=true');
    const count = data?.unread_count || 0;
    const el = document.getElementById('notif-count');
    if (el) { el.textContent = count > 99 ? '99+' : count; el.style.display = count ? 'inline-block' : 'none'; }
  } catch (_e) { /* ignore */ }
}

export async function openNotificationsModal() {
  try {
    const data = await api.get('/notifications');
    const list = data?.notifications || [];
    const content = el('div', { class: 'notification-modal-content', style: 'max-height:400px;overflow-y:auto' }, []);
    if (!list.length) {
      content.append(emptyState('لا توجد إشعارات.'));
    } else {
      const items = list.map((n) => {
        const isUnread = !n.read_at;
        return el('div', { class: `card notif-card ${isUnread ? 'unread' : ''}`, style: 'margin-bottom:8px;padding:12px;border:1px solid var(--border)' }, [
          el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:4px' }, [
            badge(n.severity || 'INFO', n.severity === 'CRITICAL' ? 'red' : n.severity === 'WARNING' ? 'amber' : 'blue'),
            el('small', { style: 'color:var(--text-muted)' }, n.created_at ? new Date(n.created_at).toLocaleTimeString('en-GB') : ''),
          ]),
          el('b', { text: n.title }),
          el('p', { style: 'margin:4px 0;font-size:13px;color:var(--text-sub)' }, n.message),
          isUnread ? el('button', {
            class: 'btn btn-ghost btn-small',
            onclick: async (e) => {
              const btn = e.currentTarget || e.target;
              btn.disabled = true;
              try {
                await api.post(`/notifications/${n.id}/read`);
                const card = btn.closest('.notif-card');
                if (card) card.classList.remove('unread');
                btn.remove();
                refreshNotificationCount();
              } catch (err) {
                btn.disabled = false;
                console.error('Failed to mark notification read:', err);
              }
            }
          }, 'تحديد كمقروء') : null
        ]);
      });
      content.append(...items);
    }
    modal('مركز الإشعارات والتنبيهات', content);
  } catch (e) {
    modal('الإشعارات', emptyState('تعذر تحميل الإشعارات: ' + e.message));
  }
}

