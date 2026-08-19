import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {URL, URLSearchParams} from 'node:url';

const source = fs.readFileSync('/home/ubuntu/dou-server/static/i18n.js', 'utf8');
const storage = new Map([['dou_lang', 'en'], ['dou_currency', 'SAR']]);
const context = {
  console,
  URL,
  URLSearchParams,
  localStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, String(value))},
  location: {href: 'http://localhost/static/courier.html?lang=en'},
  document: {
    title: 'DOU',
    documentElement: {lang: '', dir: ''},
    body: null,
    addEventListener: () => {},
  },
  window: {alert: () => {}, confirm: () => true, prompt: () => ''},
  MutationObserver: class {},
  NodeFilter: {SHOW_TEXT: 4},
};
context.window.window = context.window;
vm.createContext(context);
vm.runInContext(source, context);
const translate = context.window.douT;
assert.equal(translate('بونص الشهر: 0 ر.س · صافي تقديري: 100 ر.س'), 'Monthly Bonus: 0 SAR · Estimated Net Pay: 100 SAR');
assert.equal(translate('اختر ملف CSV أولاً'), 'Choose a CSV file first');
assert.equal(translate('أخطاء المعاينة'), 'Preview Errors');
console.log('PASS: rider dynamic labels and touched import feedback translate through the existing English dictionary');
