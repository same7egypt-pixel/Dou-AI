// Reusable UI components — DOU Fleet OS V2 Design System
import { t } from '../i18n/i18n.js';

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k === 'text') node.textContent = v;
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  });
  (Array.isArray(children) ? children : [children]).forEach((c) => {
    if (c == null) return;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  });
  return node;
}

export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function loadingState(message = null) {
  return el('div', { class: 'state-loading' }, [
    el('div', { class: 'spinner' }),
    el('p', { text: message || t('جاري التحميل...') }),
  ]);
}

export function emptyState(message = null, action = null) {
  const children = [
    el('div', { class: 'state-empty-icon' }, '📭'),
    el('p', { text: message || t('لا توجد بيانات') }),
  ];
  if (action) children.push(action);
  return el('div', { class: 'state-empty' }, children);
}

export function errorState(message = null, retry = null) {
  const children = [
    el('div', { class: 'state-error-icon' }, '⚠️'),
    el('p', { text: message || t('حدث خطأ') }),
  ];
  if (retry) children.push(el('button', { class: 'btn btn-ghost btn-small', style: 'margin-top:12px', onclick: retry }, t('إعادة المحاولة')));
  return el('div', { class: 'state-error' }, children);
}

export function successState(message = null) {
  return el('div', { class: 'state-success' }, [
    el('div', { class: 'state-success-icon' }, '✅'),
    el('p', { text: message || t('تم بنجاح') }),
  ]);
}

export function badge(text, color = 'gray') {
  return el('span', { class: `badge badge-${color}`, text: t(text) });
}

export function metricCard(value, label, color = 'blue', onClick = null, subtext = null) {
  const isClickable = typeof onClick === 'function';
  const card = el('div', {
    class: `metric ${color} ${isClickable ? 'clickable' : ''}`,
    ...(isClickable ? { onclick: onClick, role: 'button', tabindex: '0' } : {})
  }, [
    el('b', { text: String(value ?? '—') }),
    el('span', { text: label }),
    subtext ? el('span', { class: 'metric-sub', text: subtext }) : null,
  ]);
  if (isClickable) {
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onClick();
      }
    });
  }
  return card;
}

export function table(columns, rows, opts = {}) {
  const thead = el('thead', {}, [el('tr', {}, columns.map((c) => el('th', { text: c.label || c.key })))]);
  const tbody = el('tbody', {}, rows.map((row) => el('tr', {}, columns.map((c) => {
    const val = row[c.key];
    const content = c.render ? c.render(val, row) : escapeHtml(val);
    return el('td', {}, [content]);
  }))));
  return el('div', { class: 'table-wrap' }, [el('table', {}, [thead, tbody])]);
}

export function modal(title, content, onClose) {
  const overlay = el('div', { class: 'modal-overlay open' }, [
    el('div', { class: 'modal-box' }, [
      el('div', { class: 'modal-head' }, [
        el('h3', { text: title }),
        el('button', { class: 'btn-close', onclick: () => { overlay.remove(); onClose && onClose(); } }, '✕'),
      ]),
      el('div', { class: 'modal-body' }, [content]),
    ]),
  ]);
  document.body.append(overlay);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) { overlay.remove(); onClose && onClose(); } });
  return overlay;
}

export function confirmModal({ title, message, impactText, onConfirm, confirmLabel = 'تأكيد الإجراء', isDestructive = false, onClose = null }) {
  const body = el('div', {}, [
    el('p', { style: 'font-size:13px;color:var(--ink2);margin-bottom:12px' }, message),
    impactText ? el('div', { class: 'confirm-impact' }, [
      el('b', { style: 'display:block;margin-bottom:4px' }, '⚠️ الأثر التشغيلي:'),
      el('span', { text: impactText })
    ]) : null,
    el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:20px' }, [
      el('button', { class: 'btn btn-ghost', onclick: () => { overlay.remove(); onClose && onClose(); } }, 'إلغاء'),
      el('button', { class: `btn ${isDestructive ? 'btn-red' : 'btn-blue'}`, onclick: async () => {
        overlay.remove();
        if (onConfirm) await onConfirm();
      } }, confirmLabel),
    ])
  ]);
  const overlay = modal(title, body, onClose);
  return overlay;
}

export function aiPromptBar(prompts = [], onSelect = null) {
  if (!prompts.length) return null;
  const isAr = localStorage.getItem('dou_lang') !== 'en';
  return el('div', { class: 'ai-prompt-bar' }, [
    el('span', { class: 'ai-prompt-label' }, isAr ? '✨ استفسار سريع:' : '✨ Quick Query:'),
    el('div', { class: 'ai-chips-wrap' }, prompts.map((p) => el('button', {
      class: 'ai-chip',
      onclick: () => onSelect && onSelect(p)
    }, p)))
  ]);
}

export function priorityActionCard({ title, description, severity = 'medium', count = null, actionLabel = 'فتح الإجراء', onAction = null }) {
  const isAr = localStorage.getItem('dou_lang') !== 'en';
  const pClass = severity === 'high' ? 'p-high' : severity === 'medium' ? 'p-medium' : 'p-low';
  const badgeColor = severity === 'high' ? 'red' : severity === 'medium' ? 'amber' : 'blue';
  const sevLabel = isAr 
    ? (severity === 'high' ? 'عالي الأولوية' : severity === 'medium' ? 'متوسط' : 'معلوماتي')
    : (severity === 'high' ? 'High Priority' : severity === 'medium' ? 'Medium' : 'Info');
  const countLabel = count !== null ? (isAr ? `${count} حالات` : `${count} cases`) : null;

  return el('div', { class: `priority-action-card ${pClass}` }, [
    el('div', { class: 'priority-action-info' }, [
      el('div', { style: 'display:flex;align-items:center;gap:8px;margin-bottom:4px' }, [
        badge(sevLabel, badgeColor),
        count !== null ? el('span', { class: 'badge badge-gray', text: countLabel }) : null,
      ]),
      el('div', { class: 'priority-action-title', text: title }),
      description ? el('div', { class: 'priority-action-desc', text: description }) : null,
    ]),
    onAction ? el('button', { class: 'btn btn-ghost btn-small', onclick: onAction }, actionLabel) : null,
  ]);
}

export function formRow(children) {
  return el('div', { class: 'form-row' }, children);
}

export function inputField(id, label, attrs = {}) {
  return el('div', {}, [
    el('label', { for: id, text: label }),
    el('input', { id, name: id, ...attrs }),
  ]);
}

export function selectField(id, label, options = [], value = '') {
  return el('div', {}, [
    el('label', { for: id, text: label }),
    el('select', { id, name: id }, [
      ...options.map((o) => el('option', { value: o.value, ...(o.value === value ? { selected: 'selected' } : {}) }, o.label)),
    ]),
  ]);
}

export function button(label, onclick, variant = 'primary', attrs = {}) {
  return el('button', { class: `btn btn-${variant}`, onclick, ...attrs }, label);
}

export function searchableSelect({
  id = '',
  name = '',
  placeholder = '🔍 ابحث بالاسم، الجوال، أو الرقم...',
  options = [],
  value = '',
  onChange = null,
  style = '',
  disabled = false
}) {
  let currentOptions = options.map((o) => (typeof o === 'object' ? o : { value: String(o), label: String(o) }));
  let selectedValue = value !== null && value !== undefined ? String(value) : '';
  let highlightedIndex = -1;

  const wrap = el('div', { class: 'searchable-select-wrap', style });
  const hiddenInput = el('input', { type: 'hidden', id, name: name || id, value: selectedValue });

  const box = el('div', { class: 'searchable-select-box' });
  const icon = el('span', { class: 'searchable-select-icon' }, '🔍');
  const searchInput = el('input', {
    type: 'text',
    class: 'searchable-select-input',
    placeholder,
    autocomplete: 'off',
    ...(disabled ? { disabled: 'disabled' } : {})
  });
  const clearBtn = el('button', {
    type: 'button',
    class: 'searchable-select-clear',
    style: selectedValue ? 'display:block' : 'display:none',
    onclick: (e) => {
      e.stopPropagation();
      selectOption('', '');
    }
  }, '✕');
  const chevron = el('span', { class: 'searchable-select-chevron' }, '▼');

  box.append(icon, searchInput, clearBtn, chevron);

  const dropdown = el('div', { class: 'searchable-select-dropdown' });
  wrap.append(hiddenInput, box, dropdown);

  function normalizeText(txt) {
    return String(txt || '')
      .toLowerCase()
      .replace(/[أإآ]/g, 'ا')
      .replace(/ة/g, 'ه')
      .replace(/ى/g, 'ي')
      .replace(/[\u064B-\u065F]/g, '')
      .trim();
  }

  function getSelectedOption() {
    return currentOptions.find((o) => String(o.value) === String(selectedValue));
  }

  function updateDisplay() {
    const sel = getSelectedOption();
    if (sel) {
      searchInput.value = sel.label;
      clearBtn.style.display = 'block';
    } else {
      searchInput.value = '';
      clearBtn.style.display = 'none';
    }
    hiddenInput.value = selectedValue;
  }

  function renderDropdown(filterText = '') {
    dropdown.innerHTML = '';
    highlightedIndex = -1;
    const query = normalizeText(filterText);

    const filtered = currentOptions.filter((o) => {
      if (!query) return true;
      const matchLabel = normalizeText(o.label).includes(query);
      const matchSub = normalizeText(o.sublabel).includes(query);
      const matchVal = normalizeText(o.value).includes(query);
      return matchLabel || matchSub || matchVal;
    });

    if (!filtered.length) {
      dropdown.append(el('div', { class: 'searchable-select-empty' }, `لا توجد نتائج مطابقة لـ "${filterText}"`));
      return;
    }

    filtered.forEach((opt, idx) => {
      const isSelected = String(opt.value) === String(selectedValue);
      const optEl = el('div', {
        class: `searchable-select-option ${isSelected ? 'selected' : ''}`,
        'data-index': idx,
        onclick: (e) => {
          e.stopPropagation();
          selectOption(opt.value, opt.label, opt);
        }
      }, [
        el('div', { style: 'display:flex;flex-direction:column;gap:2px;text-align:right' }, [
          el('div', { style: 'font-weight:600;font-size:13px' }, opt.label),
          opt.sublabel ? el('div', { style: 'font-size:11px;color:var(--muted)' }, opt.sublabel) : null
        ]),
        opt.badge ? el('span', { class: `badge badge-${opt.badgeColor || 'gray'}`, style: 'font-size:10px' }, opt.badge) : (isSelected ? el('span', { style: 'color:#16a34a;font-size:14px' }, '✓') : null)
      ]);
      dropdown.append(optEl);
    });
  }

  function openDropdown() {
    if (disabled) return;
    wrap.classList.add('open');
    renderDropdown(searchInput.value && !getSelectedOption() ? searchInput.value : '');
    searchInput.select();
  }

  function closeDropdown() {
    wrap.classList.remove('open');
    updateDisplay();
  }

  function selectOption(val, label, optObj = null) {
    selectedValue = String(val);
    updateDisplay();
    closeDropdown();
    hiddenInput.dispatchEvent(new Event('change', { bubbles: true }));
    if (typeof onChange === 'function') {
      onChange(selectedValue, optObj || getSelectedOption());
    }
  }

  searchInput.addEventListener('focus', () => {
    openDropdown();
  });

  searchInput.addEventListener('input', () => {
    wrap.classList.add('open');
    renderDropdown(searchInput.value);
  });

  searchInput.addEventListener('keydown', (e) => {
    const items = dropdown.querySelectorAll('.searchable-select-option');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (!wrap.classList.contains('open')) openDropdown();
      if (items.length) {
        highlightedIndex = (highlightedIndex + 1) % items.length;
        items.forEach((item, idx) => item.classList.toggle('highlighted', idx === highlightedIndex));
        items[highlightedIndex]?.scrollIntoView({ block: 'nearest' });
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (items.length) {
        highlightedIndex = (highlightedIndex - 1 + items.length) % items.length;
        items.forEach((item, idx) => item.classList.toggle('highlighted', idx === highlightedIndex));
        items[highlightedIndex]?.scrollIntoView({ block: 'nearest' });
      }
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (highlightedIndex >= 0 && items[highlightedIndex]) {
        items[highlightedIndex].click();
      } else if (items.length === 1) {
        items[0].click();
      }
    } else if (e.key === 'Escape') {
      closeDropdown();
    }
  });

  const onDocClick = (e) => {
    if (!wrap.isConnected) {
      document.removeEventListener('click', onDocClick);
      return;
    }
    if (!wrap.contains(e.target)) {
      closeDropdown();
    }
  };
  document.addEventListener('click', onDocClick);

  updateDisplay();

  wrap.setValue = (val) => {
    selectedValue = String(val);
    updateDisplay();
  };
  wrap.setOptions = (newOpts) => {
    currentOptions = newOpts.map((o) => (typeof o === 'object' ? o : { value: String(o), label: String(o) }));
    updateDisplay();
    if (wrap.classList.contains('open')) renderDropdown(searchInput.value);
  };
  wrap.getValue = () => selectedValue;

  return wrap;
}
