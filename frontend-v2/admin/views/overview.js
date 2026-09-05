// Super Admin — Overview
import { api } from '../../shared/api/client.js';
import { appStore } from '../../shared/state/store.js';
import { el, loadingState, errorState, metricCard, money } from '../../shared/components/ui.js';
import { t, getLang } from '../../shared/i18n/i18n.js';

export async function loadOverview(container) {
  const isAr = getLang() === 'ar';
  container.innerHTML = '';
  container.append(el('div', { class: 'header' }, [
    el('div', {}, [
      el('div', { class: 'kicker' }, isAr ? 'لوحة قيادة المنصة التنفيذية' : 'Executive Platform Dashboard'),
      el('h1', { text: isAr ? 'لوحة القيادة والمؤشرات الموحدة' : 'Unified Executive Dashboard' })
    ]),
    el('button', { class: 'btn btn-ghost', onclick: () => loadOverview(container) }, isAr ? '↻ تحديث' : '↻ Refresh')
  ]));

  const body = el('div', {}, [loadingState(isAr ? 'جاري تجميع المؤشرات المالية والتشغيلية الموحدة...' : 'Loading unified metrics...')]);
  container.append(body);

  try {
    const country = appStore.get().selectedCountry;
    const url = '/admin/dashboard' + (country ? `?country=${encodeURIComponent(country)}` : '');
    const data = await api.get(url);
    const currency = country === 'EG' ? 'EGP' : 'SAR';

    body.innerHTML = '';

    // Requirement 2: Unified DOU Monthly Revenue with itemized SaaS Subscriptions + Flex Net Margin
    const totalRev = Number(data.monthly_revenue || 0);
    const subRev = Number(data.subscription_revenue || 0);
    const flexRev = Number(data.flex_margin_revenue || 0);

    const cards = el('div', { class: 'cards' }, [
      metricCard(
        money(totalRev, currency),
        isAr ? 'إجمالي إيراد DOU الموحد للشهر' : 'Total Unified DOU Revenue',
        'green',
        null,
        isAr ? 'اشتراكات المنصة SaaS + هوامش ورديات الفليكس' : 'SaaS Subscriptions + Flex Net Margins'
      ),
      metricCard(
        money(subRev, currency),
        isAr ? 'اشتراكات شركات اللوجستيات (SaaS)' : 'Logistics SaaS Subscriptions',
        'blue',
        null,
        isAr ? 'المحصلة فعلياً هذا الشهر' : 'Collected this month'
      ),
      metricCard(
        money(flexRev, currency),
        isAr ? 'هوامش ورديات الفليكس (Net Margin)' : 'Flex Shifts Net Margin',
        'trend',
        null,
        isAr ? 'صافي أرباح DOU من عقود المطاعم' : 'DOU Margin from Restaurant Contracts'
      ),
      metricCard(
        `${data.active_tenants || 0} / ${data.total_tenants || 0}`,
        isAr ? 'شركات لوجستية نشطة' : 'Active Logistics Companies',
        'purple',
        null,
        isAr ? 'الشركات النشطة من إجمالي المشتركين' : 'Active vs Total Tenants'
      ),
      metricCard(
        data.total_riders || 0,
        isAr ? 'إجمالي المناديب بالمنظومة' : 'Total System Couriers',
        'amber',
        null,
        isAr ? 'مناديب الشركات المسجلين' : 'Registered Fleet Riders'
      ),
    ]);
    body.append(cards);
  } catch (e) {
    body.replaceWith(errorState(isAr ? 'تعذر تحميل لوحة القيادة: ' + e.message : 'Failed to load dashboard: ' + e.message));
  }
}
