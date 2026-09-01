// Full bilingual i18n module for DOU Fleet OS V2 & Admin V2
const STORAGE_KEY = 'dou_lang';

const DICTIONARY = {
  // Navigation & Views
  'مركز القيادة': 'Command Center',
  'السائقون': 'Drivers & Workforce',
  'ملف السائق 360': 'Driver 360 Profile',
  'الورديات والحضور': 'Shifts & Attendance',
  'يحتاج انتباه': 'Needs Attention',
  'تخطيط السعة': 'Capacity Planning',
  'التقارير والتحليلات': 'Reports & Analytics',
  'الرواتب والعمليات المالية': 'Payroll & Settlements',
  'مساعد DOU AI': 'DOU AI Assistant',
  'مساعد DOU': 'DOU Assistant',
  'الرئيسية': 'Main',
  'القوى العاملة': 'Workforce',
  'العمليات': 'Operations',
  'الأداء والامتثال': 'Performance & Compliance',
  'المالية': 'Finance',
  'المساعد الذكي': 'AI Assistant',

  // Top Bar & Controls
  'نمط: شركة أساطيل لوجستية': 'Mode: Direct Fleet Partner',
  'نمط: منصة توصيل (متعددة 3PL)': 'Mode: Multi-3PL Delivery Platform',
  'تبديل': 'Switch',
  'تحديث البيانات': 'Refresh Data',
  'تسجيل الخروج': 'Log Out',
  'كل شركات التشغيل (المنصة)': 'All Operating Companies (Platform)',
  'تنبيهات': 'Notifications',
  'لا توجد تنبيهات جديدة': 'No new notifications',

  // Common Actions & Buttons
  'حفظ': 'Save',
  'إلغاء': 'Cancel',
  'إغلاق': 'Close',
  'إضافة': 'Add',
  'تعديل': 'Edit',
  'حذف': 'Delete',
  'تصدير': 'Export',
  'تنزيل CSV': 'Download CSV',
  'تنزيل Excel': 'Download Excel',
  'تنزيل لبرنامج Excel': 'Download for Excel',
  'عرض': 'View',
  'تفاصيل': 'Details',
  'بحث': 'Search',
  'تصفية': 'Filter',
  'اعتماد': 'Approve',
  'رفض': 'Reject',
  'إرسال': 'Submit',
  'تطبيق': 'Apply',
  'مسح': 'Clear',
  'إعادة تعيين': 'Reset',
  'عرض الكل': 'View All',
  'عرض اللوحة التفاعلية ←': 'Open Interactive Dashboard →',
  'العودة للوحات Metabase': 'Back to Metabase Dashboards',
  'فتح في نافذة مستقلة ↗': 'Open in New Window ↗',
  'تشغيل الاستعلام الذكي': 'Run Smart Query',

  // Reports & Analytics Sub-tabs
  'كتالوج التقارير الشامل (31 تقرير)': 'Comprehensive Reports Catalog (31 Reports)',
  'لوحات Metabase التفاعلية': 'Metabase Interactive Dashboards',
  'تقارير المنصات والأداء التشغيلي (19 مؤشر)': 'Platform & Operations Reports (19 KPIs)',
  'استعلامات DOU AI الحية': 'Live DOU AI BI Queries',
  'مركز التقارير والتحليلات': 'Reports & Analytics Center',
  'ذكاء الأعمال والتحليلات المتقدمة': 'Business Intelligence & Advanced Analytics',
  'لوحة العمليات التنفيذية': 'Executive Operations Dashboard',
  'لوحة القوى العاملة والجاهزية': 'Workforce & Readiness Dashboard',
  'لوحة الحضور والورديات الميدانية': 'Attendance & Shift Compliance Dashboard',
  'لوحة أداء المناديب وجودة الخدمة': 'Rider Performance & SLA Matrix',
  'لوحة الرواتب والتسويات المالية': 'Payroll & Financial Summary',

  // Statuses & Badges
  'نشط': 'Active',
  'غير نشط': 'Inactive',
  'موقوف': 'Suspended',
  'قيد المراجعة': 'Under Review',
  'جاهز للتشغيل': 'Operationally Ready',
  'معتمد': 'Approved',
  'مرفوض': 'Rejected',
  'معلق': 'Pending',
  'مكتمل': 'Completed',
  'ملغي': 'Cancelled',
  'محدث': 'Updated',
  'حاضر': 'Present',
  'غائب': 'Absent',
  'متأخر': 'Late',
  'في إجازة': 'On Leave',
  'سارية': 'Valid',
  'منتهية': 'Expired',
  'قاربت على الانتهاء': 'Expiring Soon',

  // Table Headers & Fields
  'السائق': 'Driver',
  'الاسم': 'Name',
  'رقم الجوال': 'Mobile Phone',
  'المدينة': 'City',
  'الفرع': 'Branch',
  'المشروع': 'Project',
  'المشرف': 'Supervisor',
  'الحالة': 'Status',
  'الجاهزية': 'Readiness',
  'الوردية': 'Shift',
  'التاريخ': 'Date',
  'الوقت': 'Time',
  'الطلبات': 'Orders',
  'المسافة': 'Distance',
  'المبلغ': 'Amount',
  'الراتب الأساسي': 'Base Salary',
  'البونص': 'Bonus',
  'الحوافز': 'Incentives',
  'الخصومات': 'Deductions',
  'الصافي': 'Net Pay',
  'الإجمالي': 'Total',
  'إجراءات': 'Actions',

  // Login Screen
  'سجل دخول شركتك اللوجستية': 'Sign in to your logistics company',
  'دخول الشركة': 'Company Sign In',
  'رقم الجوال (بمفتاح الدولة)': 'Mobile Number (with country code)',
  'كلمة المرور (8 أحرف)': 'Password (8 characters)',
  'الحسابات الجديدة يفعّلها فريق DOU': 'New accounts are activated by the DOU team',
  'سجل دخول إدارة المنصة': 'Platform Management Sign In',
  'لوحة محمية بفريق DOU — الدخول بـX-Admin-Key أو JWT': 'Protected by DOU team — Login via X-Admin-Key or JWT',

  // Super Admin
  'لوحة القيادة': 'Dashboard',
  'الشركات المشتركة': 'Subscribed Companies',
  'المشغّلون': 'Operators',
  'التحصيل والإيرادات': 'Collections & Revenue',
  'الباقات والأسعار': 'Plans & Pricing',
  'الاستخدام والحدود': 'Usage & Limits',
  'صحة المنصة': 'Platform Health',
  'التكاملات': 'Integrations',
  'ذكاء الأعمال (Metabase)': 'Business Intelligence (Metabase)',
  'سجل إدارة DOU': 'DOU Audit Log',
  'فريق DOU': 'DOU Team',
  'إعدادات النظام': 'System Settings',
  'لوحة قيادة DOU 🚀': 'DOU Command Center 🚀',
  'المحصل هذا الشهر': 'Collected This Month',
  'شركات متأخرة': 'Overdue Companies',
  'شركات نشطة': 'Active Companies',
  'مستخدمو الشركات': 'Company Users',
};

// Reverse mapping for English -> Arabic
const REVERSE_DICTIONARY = {};
Object.entries(DICTIONARY).forEach(([ar, en]) => {
  REVERSE_DICTIONARY[en] = ar;
});

export function getLang() {
  const urlLang = new URLSearchParams(location.search).get('lang');
  if (urlLang === 'ar' || urlLang === 'en') {
    localStorage.setItem(STORAGE_KEY, urlLang);
    return urlLang;
  }
  return localStorage.getItem(STORAGE_KEY) || 'ar';
}

export function initLang() {
  const lang = getLang();
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  document.body?.classList.toggle('lang-en', lang === 'en');
}

export function setLang(lang) {
  if (lang !== 'ar' && lang !== 'en') lang = 'ar';
  localStorage.setItem(STORAGE_KEY, lang);
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  document.body?.classList.toggle('lang-en', lang === 'en');
  
  try {
    const url = new URL(window.location.href);
    url.searchParams.set('lang', lang);
    window.location.replace(url.pathname + url.search + url.hash);
  } catch (e) {
    location.reload();
  }
}

export function toggleLang() {
  const current = getLang();
  const next = current === 'ar' ? 'en' : 'ar';
  setLang(next);
  return next;
}

export function isRTL() {
  return getLang() === 'ar';
}

export function t(key) {
  if (!key) return '';
  const lang = getLang();
  if (lang === 'ar') {
    return REVERSE_DICTIONARY[key] || key;
  }
  return DICTIONARY[key] || key;
}

// Auto-translate helper that can translate an element and its children
export function translateNode(node) {
  if (!node) return;
  const lang = getLang();
  if (node.nodeType === Node.TEXT_NODE) {
    const trimmed = node.nodeValue.trim();
    if (trimmed) {
      if (lang === 'en' && DICTIONARY[trimmed]) {
        node.nodeValue = node.nodeValue.replace(trimmed, DICTIONARY[trimmed]);
      } else if (lang === 'ar' && REVERSE_DICTIONARY[trimmed]) {
        node.nodeValue = node.nodeValue.replace(trimmed, REVERSE_DICTIONARY[trimmed]);
      }
    }
  } else if (node.nodeType === Node.ELEMENT_NODE) {
    if (node.tagName === 'INPUT' || node.tagName === 'TEXTAREA') {
      const ph = node.getAttribute('placeholder');
      if (ph) {
        if (lang === 'en' && DICTIONARY[ph]) node.setAttribute('placeholder', DICTIONARY[ph]);
        else if (lang === 'ar' && REVERSE_DICTIONARY[ph]) node.setAttribute('placeholder', REVERSE_DICTIONARY[ph]);
      }
    }
    node.childNodes.forEach(translateNode);
  }
}

// Initialize on script load
(() => {
  try {
    const param = new URLSearchParams(window.location.search).get('lang');
    if (param === 'ar' || param === 'en') {
      localStorage.setItem(STORAGE_KEY, param);
    }
  } catch (e) {}
  const lang = getLang();
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
})();
