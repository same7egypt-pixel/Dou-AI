#!/usr/bin/env python3
"""DOU Demo Seed Data — يملأ قاعدة البيانات ببيانات تجريبية واقعية
حتى تظهر كل لوحات التحكم والواجهات ممتلئة مباشرة بعد أول تشغيل.

الاستخدام:  python3 seed.py
يعمل على SQLite (افتراضي) أو Postgres (لو ضبطت DATABASE_URL).
آمن لإعادة التشغيل: يحذف المعطيات الحالية ويعيد إنشاءها.
"""
import os
import sys
from datetime import datetime, timedelta

# نبدأ بـ dou-server كمسار العمل
BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

from app.database import Base, engine, SessionLocal
from app.routers.auth import hash_password
from app.models.entities import (
    Attendance, Channel, Courier, CourierTask, CourierTaskStatus, CourierType,
    Country, DeliveryMethod, Fleet, GeoCity, GeoCountry, GeoDistrict,
    Merchant, Order, OrderItem, OrderStatus, Product, Shift, ShiftStatus,
    ShippingCompany, Staff, Tenant, User, UserRole,
)

# ====== إعدادات ======
SA = Country.SA
EG = Country.EG

MERCHANTS = [
    # (الاسم، الدولة، الحي، المدينة، الطريقة، ثيم، lat, lng)
    ("مقهى بن القهوة", SA, "حي الملقا", "الرياض", DeliveryMethod.PLATFORM_COURIER, "default", 24.7494, 46.6359),
    ("مطعم الضيافة", SA, "حي العليا", "الرياض", DeliveryMethod.PLATFORM_COURIER, "dark-royal", 24.7007, 46.6770),
    ("بقالة النور", SA, "حي النرجس", "الرياض", DeliveryMethod.SHIPPING_COMPANY, "default", 24.7900, 46.7100),
    ("دار العود للعطور", SA, "حي الملقا", "الرياض", DeliveryMethod.SHIPPING_COMPANY, "gold", 24.7450, 46.6400),
    ("متجر الشتاء للملابس", SA, "حي النرجس", "الرياض", DeliveryMethod.SHIPPING_COMPANY, "default", 24.7850, 46.7200),
    ("مقهى الروائع", EG, "المعادي", "القاهرة", DeliveryMethod.PLATFORM_COURIER, "default", 29.9660, 31.2500),
    ("مطعم لؤلؤة الشام", EG, "المنيل", "القاهرة", DeliveryMethod.PLATFORM_COURIER, "dark-royal", 30.0560, 31.2320),
    ("بقالة شارع الجيزة", EG, "الدقي", "الجيزة", DeliveryMethod.SHIPPING_COMPANY, "default", 30.0430, 31.2100),
    ("عطارة الإسكندرية", EG, "سموحة", "الإسكندرية", DeliveryMethod.SHIPPING_COMPANY, "gold", 31.2230, 29.9470),
]

PRODUCTS = {
    # مقهى بن القهوة
    1: [("كابتشينو", 16.0, "قهوة"), ("لاتيه", 17.0, "قهوة"), ("إسبريسو", 12.0, "قهوة"),
        ("تشيز كيك", 24.0, "حلويات"), ("كرواسون", 10.0, "مخبوزات"), ("حليب بالكراميل", 19.0, "قهوة")],
    # مطعم الضيافة
    2: [("برجر لحم", 34.0, "مأكولات"), ("برجر دجاج", 29.0, "مأكولات"), ("بطاطس", 12.0, "مأكولات"), ("مقبلات مشكلة", 22.0, "مأكولات")],
    # بقالة النور
    3: [("حليب كامل الدسم", 7.0, "بقالة"), ("خبز توست", 5.0, "بقالة"), ("مياه معدن 1.5L", 2.5, "بقالة"), ("أرز بسمتي 5ك", 35.0, "بقالة")],
    # دار العود
    4: [("عود كمبودي 12م", 120.0, "عطور"), ("بخور معمول", 45.0, "عطور"), ("دهن عود 3م", 200.0, "عطور")],
    # متجر الشتاء
    5: [("قميص شتوي", 89.0, "ملابس"), ("بلوفر صوف", 129.0, "ملابس"), ("قبعة وبشت", 45.0, "ملابس")],
    # مقهى الروائع (مصر)
    6: [("موكا", 75.0, "قهوة"), ("منجا سموذي", 90.0, "قهوة"), ("كريب نوتيلا", 70.0, "حلويات")],
    # لؤلؤة الشام
    7: [("منسف", 120.0, "مأكولات"), ("كبسة دجاج", 95.0, "مأكولات"), ("حمص", 25.0, "مقبلات")],
    # بقالة الجيزة
    8: [("جبنة رومي", 130.0, "بقالة"), ("شاي", 40.0, "بقالة"), ("سكر", 30.0, "بقالة"), ("زيت", 80.0, "بقالة")],
    # عطارة الإسكندرية
    9: [("زعتر وخلطة", 45.0, "عطار"), ("حبة سوداء", 30.0, "عطار"), ("جنزبيل يابس", 35.0, "عطار")],
}

COURIERS = [
    # (الاسم، الهاتف، النوع، الدولة، المدينة، lat, lng, النقاط، المعدل)
    ("أحمد الشمري", "0551112233", CourierType.COMPANY, SA, 24.7494, 46.6359, 4.9, 98),
    ("محمد العتيبي", "0554445566", CourierType.FREELANCER, SA, 24.7500, 46.6400, 4.7, 96),
    ("خالد القحطاني", "0557778899", CourierType.FREELANCER, SA, 24.7300, 46.6100, 4.5, 95),
    ("سعود الحربي", "0559993344", CourierType.COMPANY, SA, 24.7600, 46.6600, 4.8, 97),
    ("عبدالله المطيري", "0551239876", CourierType.FREELANCER, SA, 24.7200, 46.6000, 4.6, 94),
    ("كريم فتحي", "01012345678", CourierType.FREELANCER, EG, 30.0400, 31.2300, 4.7, 95),
    ("مصطفى حسن", "01098765432", CourierType.FREELANCER, EG, 30.0200, 31.2100, 4.5, 93),
]

CUSTOMER_NAMES = ["سارة أحمد", "نورة سالم", "عمر خالد", "سلمى حسن", "ريم عبدالله", "فهد العتيبي", "منى فوزي", "ياسر محمود"]
ADDRESSES = ["شارع الأمير سلطان", "حي النرجس", "شارع التخصصي", "حي العليا", "طريق الملك عبدالله", "المعادي", "الدقي", "سموحة"]

def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    now = datetime.utcnow()

    if db.query(Merchant).count() > 0:
        print("ℹ️  البيانات موجودة بالفعل في قاعدة البيانات — تم تخطي الملء.")
        print("    لو تريد البدء من جديد: احذف dou.db (SQLite) أو فعّل drop_all.")
        return

    print("🌱 قاعدة البيانات فاضية — أبدأ بالملء بالبيانات التجريبية...")
    if os.path.exists(os.path.join(BASE, "dou.db")):
        pass  # ملف جديد لا يحتاج حذفاً لأن create_all فاتح الجداول

    # ===== Tenants / Fleets =====
    tenant_dou = Tenant(name="DOU Platform", country=SA, is_dou_internal=True, created_at=now)
    tenant_fleet = Tenant(name="دو فليت الرياض", country=SA, contact_email="fleet@dou.sa", created_at=now)
    tenant_eg = Tenant(name="دو مصر", country=EG, contact_email="egypt@dou.com", created_at=now)
    db.add_all([tenant_dou, tenant_fleet, tenant_eg])
    db.commit()

    fleet_riyadh = Fleet(tenant_id=tenant_fleet.id, name="أسطول شمال الرياض", zone="شمال الرياض", created_at=now)
    fleet_cairo = Fleet(tenant_id=tenant_eg.id, name="أسطول القاهرة", zone="القاهرة", created_at=now)
    db.add_all([fleet_riyadh, fleet_cairo])
    db.commit()

    # ===== Couriers =====
    courier_rows = []
    for i, (cname, phone, ctype, country, lat, lng, score, acc) in enumerate(COURIERS):
        fleet = fleet_riyadh.id if country == SA else fleet_cairo.id
        courier = Courier(
            tenant_id=tenant_fleet.id if country == SA else tenant_eg.id,
            fleet_id=fleet,
            name=cname, phone=phone, courier_type=ctype, country=country,
            lat=lat, lng=lng, is_online=True, is_available=True, current_load=i % 2,
            acceptance_rate=acc, on_time_rate=96, completion_rate=98,
            score=score, documents_valid=True, shift_active=True, created_at=now,
        )
        db.add(courier)
        courier_rows.append(courier)
    db.commit()

    # ===== Merchants + Products =====
    merchant_rows = []
    for i, (mname, country, district, city, method, theme, lat, lng) in enumerate(MERCHANTS, start=1):
        slug = {
            "مقهى بن القهوة": "bin-coffee", "مطعم الضيافة": "diyafa-rest", "بقالة النور": "noor-market",
            "دار العود للعطور": "dar-oud", "متجر الشتاء للملابس": "winter-wear", "مقهى الروائع": "rowaeaa-cafe",
            "مطعم لؤلؤة الشام": "lolo-al-sham", "بقالة شارع الجيزة": "giza-bakala", "عطارة الإسكندرية": "iskandaria",
        }[mname]
        merchant = Merchant(
            name=mname, country=country, lat=lat, lng=lng, district=district, city=city,
            phone="0112" + f"{100000+i*1234:06d}", theme=theme,
            delivery_method=method, slug=slug, created_at=now,
        )
        db.add(merchant)
        merchant_rows.append(merchant)
    db.commit()

    product_rows = []
    for mid, items in PRODUCTS.items():
        for pname, price, cat in items:
            product = Product(
                merchant_id=mid, name=pname, description="",
                price=price, currency="SAR" if mid <= 5 else "EGP",
                is_available=True, category=cat, created_at=now,
            )
            db.add(product)
            product_rows.append(product)
    db.commit()

    # ===== Shifts =====
    db.add_all([
        Shift(tenant_id=tenant_fleet.id, fleet_id=fleet_riyadh.id, name="وردية الفترة الصباحية",
              zone="شمال الرياض", start_time="08:00", end_time="16:00", required_couriers=3, status=ShiftStatus.ACTIVE),
        Shift(tenant_id=tenant_fleet.id, fleet_id=fleet_riyadh.id, name="وردية مسائية",
              zone="الملقا والعليا", start_time="16:00", end_time="23:00", required_couriers=2, status=ShiftStatus.SCHEDULED),
        Shift(tenant_id=tenant_eg.id, fleet_id=fleet_cairo.id, name="وردية القاهرة",
              zone="المعادي والمنيل", start_time="09:00", end_time="21:00", required_couriers=2, status=ShiftStatus.ACTIVE),
    ])
    db.commit()

    # ===== Orders (موزعة على 30 يوم) =====
    statuses = [
        OrderStatus.DELIVERED, OrderStatus.DELIVERED, OrderStatus.COMPLETED, OrderStatus.DELIVERED,
        OrderStatus.IN_TRANSIT, OrderStatus.ASSIGNED, OrderStatus.READY, OrderStatus.ACCEPTED,
        OrderStatus.PLACED, OrderStatus.CANCELLED, OrderStatus.DELIVERED, OrderStatus.DELIVERED,
    ]
    order_rows = []
    for day in range(1, 31):
        for idx in range(1, 5):
            mid = ((day + idx) % len(merchant_rows))
            merchant = merchant_rows[mid]
            status = statuses[(day + idx) % len(statuses)]
            is_eg = merchant.country == EG

            subtotal = 20.0 + (day * idx * 7) % 200
            delivery_fee = 15.0 if is_eg else 8.0
            total = round(subtotal + delivery_fee, 2)
            cust_idx = (day + idx) % len(CUSTOMER_NAMES)
            order = Order(
                customer_name=CUSTOMER_NAMES[cust_idx],
                customer_phone="0559" + f"{100000+day*idx:06d}" if not is_eg else "0105" + f"{000000+day*idx*11:06d}",
                customer_lat=merchant.lat + 0.03, customer_lng=merchant.lng + 0.02,
                customer_address=ADDRESSES[cust_idx],
                merchant_id=merchant.id,
                delivery_method=merchant.delivery_method,
                status=status,
                subtotal=round(subtotal, 2), delivery_fee=delivery_fee, total=total,
                distance_km=round(2.0 + (day % 8), 1),
                courier_id=courier_rows[day % len(courier_rows)].id if merchant.delivery_method != DeliveryMethod.SHIPPING_COMPANY else None,
                created_at=now - timedelta(days=30 - day, hours=idx * 4),
            )
            db.add(order)
            order_rows.append(order)
    db.commit()

    # ===== Order Items =====
    for o in order_rows:
        prod = product_rows[(o.id % len(product_rows) - 1)]
        qty = 1 + (o.id % 3)
        db.add(OrderItem(order_id=o.id, product_id=prod.id, name=prod.name, quantity=qty, unit_price=prod.price))
    db.commit()

    # ===== Courier Tasks =====
    for o in order_rows[:60]:
        if o.courier_id and o.status in (OrderStatus.DELIVERED, OrderStatus.COMPLETED, OrderStatus.IN_TRANSIT, OrderStatus.ASSIGNED):
            st = (CourierTaskStatus.DELIVERED if o.status in (OrderStatus.DELIVERED, OrderStatus.COMPLETED)
                  else CourierTaskStatus.ACCEPTED if o.status == OrderStatus.ASSIGNED
                  else CourierTaskStatus.IN_TRANSIT)
            db.add(CourierTask(
                order_id=o.id, courier_id=o.courier_id, status=st,
                offered_at=o.created_at,
                accepted_at=o.created_at + timedelta(minutes=2) if st != CourierTaskStatus.ACCEPTED else None,
                delivered_at=o.created_at + timedelta(minutes=42) if st == CourierTaskStatus.DELIVERED else None,
            ))
    # مهام جديدة صادرة للمندوب الأول ليظهر له "طلبات جديدة" في التطبيق
    offered = 0
    for o in order_rows[60:]:
        if o.status == OrderStatus.PLACED and o.merchant.country == SA and offered < 3:
            db.add(CourierTask(order_id=o.id, courier_id=courier_rows[0].id,
                               status=CourierTaskStatus.OFFERED, offered_at=now))
            offered += 1
    db.commit()

    # ===== Attendance =====
    for c in courier_rows[:5]:
        db.add(Attendance(courier_id=c.id, check_in=now - timedelta(hours=6), check_in_lat=c.lat, check_in_lng=c.lng, is_late=False))
    db.commit()

    # ===== Shipping Companies =====
    db.add_all([
        ShippingCompany(name="سمسا إكسبرس", code="SMSA", country=SA, base_url="https://smsa.example", is_active=True),
        ShippingCompany(name="أرامكس", code="ARAMEX", country=SA, base_url="https://aramex.example", is_active=True),
        ShippingCompany(name="بوسطة بجسبي", code="BOSTA", country=EG, base_url="https://bosta.example", is_active=True),
    ])
    db.commit()

    # ===== Geo: دول → مدن → مناطق =====
    geo_sa = GeoCountry(name="السعودية", code="SA", flag="🇸🇦", active=True)
    geo_eg = GeoCountry(name="مصر", code="EG", flag="🇪🇬", active=True)
    db.add_all([geo_sa, geo_eg])
    db.commit()

    cities_sa = [
        ("الرياض", ["حي الملقا", "حي النرجس", "حي العليا", "حي الياسمين", "حي المونسية"]),
        ("جدة", ["حي الروضة", "حي السلامة", "حي الشاطئ"]),
        ("الدمام", ["حي الفيصلية", "حي الشاطئ"]),
    ]
    cities_eg = [
        ("القاهرة", ["المعادي", "المنيل", "الدقي", "مصر الجديدة", "الزمالك"]),
        ("الجيزة", ["الهرم", "الدقي"]),
        ("الإسكندرية", ["سموحة", "المنتزه", "سان ستيفانو"]),
    ]
    for cname, districts in cities_sa:
        city = GeoCity(country_id=geo_sa.id, name=cname, active=True)
        db.add(city)
        db.flush()
        for dname in districts:
            db.add(GeoDistrict(city_id=city.id, name=dname, active=True))
    for cname, districts in cities_eg:
        city = GeoCity(country_id=geo_eg.id, name=cname, active=True)
        db.add(city)
        db.flush()
        for dname in districts:
            db.add(GeoDistrict(city_id=city.id, name=dname, active=True))
    db.commit()

    # ===== Channels (قنوات البيع) =====
    db.add_all([
        Channel(name="DOU App", icon="📱", type="OWN", commission=0, is_active=True, orders_share=70, status="active"),
        Channel(name="Jahez", icon="🍔", type="PARTNER", commission=12, is_active=True, orders_share=18, status="active"),
        Channel(name="HungerStation", icon="🚀", type="PARTNER", commission=10, is_active=True, orders_share=8, status="active"),
        Channel(name="Instagram", icon="📷", type="SOCIAL", commission=0, is_active=True, orders_share=3, status="active"),
        Channel(name="WhatsApp", icon="💬", type="SOCIAL", commission=0, is_active=True, orders_share=1, status="active"),
    ])
    db.commit()

    # ===== Staff (فريق التشغيل) =====
    db.add_all([
        Staff(name="سارة الأحمد", email="sara@dou.sa", role="مدير المنصة", access="full", region="الرياض", status="active"),
        Staff(name="خالد العليان", email="khaled@dou.sa", role="مدير التشغيل", access="full", region="الرياض", status="active"),
        Staff(name="ليلى محمود", email="leila@dou.sa", role="محاسبة", access="finance", region="جدة", status="active"),
        Staff(name="أحمد يوسف", email="ahmed@dou.sa", role="دعم التشغيل", access="limited", region="الدمام", status="active"),
        Staff(name="منى حسن", email="mona@dou.com", role="دعم مصر", access="limited", region="القاهرة", status="inactive"),
    ])
    db.commit()

    # ===== Users (دخول تجريبي) =====
    users = [
        ("966501112233", "مقهى بن القهوة", UserRole.MERCHANT, merchant_rows[0].id),
        ("966551112233", "أحمد الشمري", UserRole.COURIER, courier_rows[0].id),
        ("966500000000", "Ops Cloud", UserRole.DOU_OPS, None),
        ("966581112233", "فريق الأسطول", UserRole.COMPANY, None),
        ("966512345678", "مشرف المنصة", UserRole.DOU_ADMIN, None),
    ]
    for phone, name, role, ref_id in users:
        u = User(phone=phone, name=name, password_hash=hash_password("dou123456"),
                 role=role, country=SA, is_active=True, created_at=now)
        if role == UserRole.MERCHANT:
            u.merchant_id = ref_id
        elif role == UserRole.COURIER:
            u.courier_id = ref_id
        elif role == UserRole.COMPANY:
            u.tenant_id = tenant_fleet.id
        db.add(u)
    db.commit()

    n_orders = db.query(Order).count()
    n_merchants = len(merchant_rows)
    n_couriers = len(courier_rows)
    n_products = len(product_rows)
    print("\n✅ ملء البيانات اكتمل:")
    print(f"   • تجار: {n_merchants} · منتجات: {n_products} · مناديب: {n_couriers} · طلبات: {n_orders}")
    print("   • دخول تجريبي (الكل بكلمة المرور): dou123456")
    print("        تاجر:   966501112233")
    print("        مندوب:  966551112233")
    print("        Ops:    966500000000")
    print("        Fleet:  966581112233")
    print("        Admin:  966512345678")

if __name__ == "__main__":
    main()