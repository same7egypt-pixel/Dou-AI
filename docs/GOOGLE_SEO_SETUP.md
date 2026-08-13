# Google launch checklist for dou.delivery

## 1. Google Search Console

1. Open https://search.google.com/search-console/ and choose **Domain**.
2. Enter `dou.delivery`.
3. Copy the TXT verification value shown by Google.
4. In GoDaddy DNS, add a TXT record with name `@` and the value from Google.
5. Return to Search Console and select **Verify**.
6. Submit the sitemap: `https://dou.delivery/sitemap.xml`.

Domain verification is preferred because it covers HTTPS, `www`, and any current or future subdomains.

## 2. Google Analytics 4

1. Open https://analytics.google.com/ and create a GA4 property for DOU.
2. Create a Web data stream for `https://dou.delivery`.
3. Copy the Measurement ID beginning with `G-`.
4. In Render, add an environment variable named `GOOGLE_ANALYTICS_ID` with that value.
5. Save and deploy. The website loads Analytics only when a valid `G-` ID exists.

Recommended events to configure later: demo request, client login, Android download, pricing contact and help-center visit.

## 3. Indexing and quality checks

- Request indexing for `/`, `/en`, `/help` and `/help/en`.
- Check Page Indexing, Core Web Vitals and HTTPS reports weekly during the first month.
- Do not index `/app`, `/driver`, `/admin` or private static dashboard URLs.
- Publish one useful logistics article every two weeks in Arabic and English.

## 4. Initial target searches

Arabic: برنامج إدارة السائقين، إدارة مناديب التوصيل، نظام حضور السائقين، متابعة إقامات ورخص السائقين، حساب تارجت المناديب.

English: driver management software, logistics workforce management, courier attendance software, driver compliance tracking, delivery driver target tracking.
