# دليل نشر منصة DOU أونلاين (بدون معارف برمجية)

رحلة النشر من 3 محطات: **GitHub** (مستودع الكود) ← **Neon** (قاعدة بيانات مجانية) ← **Render** (تشغيل السيرفر). كلها مجانية.

---

## المحطة 1: رفع الكود على GitHub (مرة واحدة)

> نرفع ملفات السيرفر — الاسم `dou-server` — حتى يقرأها Render.

### أ) أنشئ حساب GitHub (لو ما عندك)
1. ادخل **github.com** ← سجّل مجاناً.
2. فعل البريد، ثم اعمل ريبو جديد:
   - اضغط **+** (أعلى يمين) ← **New repository**
   - الاسم: `dou-server` — عام (**Public**)
   - فعّل "Add a README file" (اختيارياً يسهّل).
   - **Don't initialize with .gitignore** (عندنا جاهز) ← **Create repository**

### ب) اربط الكود المحلي بالريبو
افتح **الترمينال** على ماك (Terminal)، وانسخ الأوامر التالية واحدة واحدة (بعد كل أمر اضغط Enter):

```
cd "/Users/sameh/Documents/Default Project/dou-server"
git init
git add -A
git commit -m "DOU platform deploy"
git branch -M main
git remote add origin https://github.com/اسمك/dou-server.git
git push -u origin main
```

> ⚠️ استبدل `اسمك` باسم مستخدمك في GitHub في السطر الخمسة.
> أول مرة ستطلب منك المتصفح تسجيل الدخول — اعمل Sign in وخلاص.

بعد ما يخلص من "Everything up-to-date" → روح GitHub وشيك إن الملفات ظهرت عنده.

---

## المحطة 2: قاعدة بيانات مجانية في Neon

> السيرفر يحتاج قاعدة بيانات تحفظ الطلبات والمناديب. Neon يعطينا Postgres مجاني 3 دقائق عملهم.

1. ادخل **neon.tech** ← Sign up (يصلح بحساب Google أو GitHub).
2. بعد الدخول: اضغط **Create a project**:
   - الاسم: `dou-db`
   - Regional: اسحب إلى **Singapore** (أقرب).
   - **Add region** ← من الأحسن `singapore-1` ← **Create project**
3. سيعطيك **Connection string** (رابط اتصال) تشبه هذا الشكل:

```
postgresql://neondb_owner:كلمة-سرية@ep-....us-east-2.aws.neon.tech/dou-db?sslmode=require
```

4. **انسخه واحفظه في ملف Notes** — سنحتاجه في المحطة الثالثة.
   > ⚠️ لا تنسخه لأي أحد، هو مفتاح قاعدة بياناتك.

---

## المحطة 3: تشغيل السيرفر على Render

> Render يشغّل الكود ويعطيه رابطاً عاماً مثل `https://dou-platform.onrender.com`.

1. ادخل **render.com** ← **Sign up** (حساب GitHub أفضل).
2. بعد الدخول: اضغط **New → Blueprint** (عندك ملف `render.yaml` جاهز).
3. اختار الملف: ابحث عن **dou-server** ← Connect.
4. سيقرأ Render الملف ويطلب تأكيد ← **Apply Blueprint**.
5. انتظر البناء (Build) — اول نشره يأخذ 5–10 دقائق، وأنت رايح تجهز الخطوة 6.
6. **اربط قاعدة البيانات Neon** (بعد ما يصير الخدمة تنصلح):
   - من لوحة Render: خدمتك `dou-platform` ← **Environment**
   - عند `DATABASE_URL` اضغط **Edit** ← الصق الرابط اللي حفظته من Neon ← Save.
   - عند `SECRET_KEY` اضغط **Edit** ← اضغط زر ‏:recycle: لتوليد قيمة عشوائية ← Save.
7. **عد التشغيل**: من أعلى: `Manual Deploy` → **Deploy latest commit** (حتى يبدأ بـ Postgres). انتظر (دقيقة).

✅ **تم النشر!** ستحصل على رابط:
`https://dou-platform.onrender.com` (اسحبه عندك — هذا رابط الحقيقي).

---

## المحطة 4: التحقق

افتح الروابط من أي متصفح (الجوال أو الكمبيوتر):

| الصفحة | الرابط |
|---|---|
| البوابة الرئيسية | `https://dou-platform.onrender.com/` |
| فحص الصحة | `https://dou-platform.onrender.com/health` ← يجب يعرض `{"status":"ok"}` |
| تجربة العتاد (Demo) | `https://dou-platform.onrender.com/static/dou-demo.html` |
| نسخة Fleet التسويقية | `https://dou-platform.onrender.com/static/dou-fleet.html` |

### جرب دخول اللوحات (كلمة المرور للكل:)
| اللوحة | المتصفح |
|---|---|
| لوحة التاجر | `Merchant: 966501112233` |
| لوحة الشركة Fleet | `Fleet: 966581112233` |
| تطبيق السواقين | `Courier: 966551112233` |
| لوحة العمليات | `Ops: 966500000000` |
| لوحة الأدمن | `Admin: 966512345678` |

> كل الحسابات كلمة المرور: **dou123456**

---

## ملاحظات مهمة (شيخوخة Render المجاني)
- الخدمة المجانية تنام بعد 15 دقيقة من عدم الاستخدام — أول فتح بعد النوم يأخذ ~50 ثانية (طبيعي).
- قاعدة البيانات مجانية دائماً في Neon، لكن **ترقية السيرفر** (من Free إلى 7$/شهر تقريباً) تزيل النوم وترفع الأداء — تقدر لاحقاً من Render: Instance Type → Starter.
- أي تعديل جديد على الكود: بضغطة في الترمينال

```
cd "/Users/sameh/Documents/Default Project/dou-server"
git add -A && git commit -m "update" && git push
```

Render يتحدّث تلقائياً (autoDeploy مفعّل). خلاص!

---

## لو واجهت مشكلة؟
- الحالة `Deploy failed` → افتح `Events`/`Logs` في Render وانسخ أول سطر خطأ (سيساعدنا).
- البيانات الصفحات تلعب كاملة وديمو → لا مشكلة.
- الـ demo يعمل محلياً بدون سيرفر، والبرتنس الصفحات تأخذ بيانات حقيقية من API.

**رابط مفيد بعد النشر:** الواجهات الحية `https://dou-platform.onrender.com/docs` (Swagger) — بس كون الخدمة مجانية قد تحتاج انتظار حتى تستيقظ.