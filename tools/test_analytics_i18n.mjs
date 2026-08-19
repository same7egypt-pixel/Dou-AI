import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {URL, URLSearchParams} from 'node:url';

const source = fs.readFileSync('/home/ubuntu/dou-server/static/i18n.js', 'utf8');
const storage = new Map([['dou_lang', 'en'], ['dou_currency', 'SAR']]);
const context = {
  console, URL, URLSearchParams,
  localStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, String(value))},
  location: {href: 'http://localhost/static/fleet.html?lang=en'},
  document: {title: 'DOU', documentElement: {lang: '', dir: ''}, body: null, addEventListener: () => {}},
  window: {alert: () => {}, confirm: () => true, prompt: () => ''},
  MutationObserver: class {}, NodeFilter: {SHOW_TEXT: 4},
};
context.window.window = context.window;
vm.createContext(context);
vm.runInContext(source, context);
const t = context.window.douT;
assert.equal(t('التحليلات والتقارير'), 'Analytics & Reports');
assert.equal(t('الفترة المالية مغلقة — الأرقام تقرأ من اللقطات النهائية.'), 'Financial period closed — values are read from final snapshots.');
assert.equal(t('الإيراد مقابل التكلفة والهامش حسب المشروع'), 'Revenue vs Cost vs Margin by Project');
assert.equal(t('محققو التارجت · إيراد العميل · هامش التشغيل'), 'Target Achievers · Client Revenue · Operational Margin');
assert.equal(t('سليم · يحتاج انتباه · حقق التارجت'), 'OK · Needs Attention · Target Achieved');
console.log('PASS: analytics labels, financial state, KPI labels, and dynamic segmentation translate through existing i18n');
