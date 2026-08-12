import enum
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, DateTime, Date, ForeignKey,
    Enum, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from ..database import Base


class Country(str, enum.Enum):
    SA = "SA"
    EG = "EG"


class UserRole(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    MERCHANT = "MERCHANT"
    COURIER = "COURIER"
    COMPANY = "COMPANY"        # مسؤول شركة لوجستية
    SUPERVISOR = "SUPERVISOR"  # مشرف على مجموعة مناديب داخل الشركة
    DOU_OPS = "DOU_OPS"        # فريق Dou الداخلي
    DOU_ADMIN = "DOU_ADMIN"    # مدير المنصة


class ShiftStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliveryMethod(str, enum.Enum):
    SELF = "SELF"                    # وصل بنفسك — مندوب التاجر
    PLATFORM_COURIER = "PLATFORM"    # وصل عن طريقنا — مناديب شركات / فريلانسر
    SHIPPING_COMPANY = "SHIPPING"    # شركة شحن (سمسا/بوسطه/أرامكس) عبر API


class OrderStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    ACCEPTED = "ACCEPTED"
    PREPARING = "PREPARING"
    READY = "READY"
    ASSIGNED = "ASSIGNED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class CourierTaskStatus(str, enum.Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    AT_MERCHANT = "AT_MERCHANT"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"


class CourierType(str, enum.Enum):
    COMPANY = "COMPANY"      # مندوب شركة لوجستية (Saudi)
    FREELANCER = "FREELANCER"  # فريلانسر (Egypt)


class Tenant(Base):
    """شركة لوجستية أو كيان يعمل على المنصة (multi-tenant)."""
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    country = Column(Enum(Country), nullable=False)
    contact_email = Column(String(120))
    contact_phone = Column(String(40))
    is_dou_internal = Column(Boolean, default=False)  # فريق Dou ops
    plan = Column(String(20), default="PRO")          # TRIAL / PRO / ENTERPRISE
    monthly_fee = Column(Float, default=0)            # رسوم الاشتراك الشهري
    billing_day = Column(Integer, default=1)          # يوم الفوترة بالشهر
    due_date = Column(DateTime)                       # تاريخ استحقاق الفاتورة القادم
    subscription_status = Column(String(20), default="ACTIVE")  # ACTIVE / OVERDUE / SUSPENDED
    last_paid_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    fleets = relationship("Fleet", back_populates="tenant")
    couriers = relationship("Courier", back_populates="tenant")


class Fleet(Base):
    """أسطول/مجموعة مناديب تابعة لشركة أو منطقة."""
    __tablename__ = "fleets"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(120), nullable=False)
    zone = Column(String(120))           # مثلاً: شمال الرياض
    is_ondemand_pool = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="fleets")
    couriers = relationship("Courier", back_populates="fleet")


class Courier(Base):
    """مندوب شركة لوجستية أو فريلانسر."""
    __tablename__ = "couriers"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    fleet_id = Column(Integer, ForeignKey("fleets.id"))
    name = Column(String(120), nullable=False)
    phone = Column(String(40), unique=True, nullable=False)
    courier_type = Column(Enum(CourierType), nullable=False)
    country = Column(Enum(Country), nullable=False)
    lat = Column(Float)                  # GPS لحظي
    lng = Column(Float)
    is_online = Column(Boolean, default=False)
    is_available = Column(Boolean, default=True)
    current_load = Column(Integer, default=0)   # عدد الطلبات الحية
    acceptance_rate = Column(Float, default=100.0)
    on_time_rate = Column(Float, default=100.0)
    completion_rate = Column(Float, default=100.0)
    score = Column(Float, default=5.0)
    documents_valid = Column(Boolean, default=True)  # مستندات سارية
    shift_active = Column(Boolean, default=False)
    # ===== حقول HR =====
    base_salary = Column(Float, default=0.0)         # راتب ثابت شهري (ر.س)
    per_delivery_rate = Column(Float, default=6.0)   # أجر كل توصيلة
    bonus_target = Column(Float, default=0.0)        # نسبة/مبلغ البونص الشهري
    employment_status = Column(String(20), default="ACTIVE")  # ACTIVE / SUSPENDED / TERMINATED
    hired_at = Column(DateTime, default=datetime.utcnow)      # تاريخ التعيين
    bank_iban = Column(String(34))                   # IBAN لتحويل الراتب
    supervisor_id = Column(Integer, ForeignKey("users.id"))  # المشرف المسؤول عن المندوب
    platform = Column(String(60))                    # المنصة/المشروع الرئيسي (هنقرستيشن/جاهز/...)
    platform_courier_id = Column(String(60))         # كود/ID المندوب داخل المنصة الخارجية
    iqama_expiry = Column(Date)                      # موعد انتهاء الإقامة
    license_expiry = Column(Date)                    # موعد انتهاء رخصة القيادة
    vehicle_license_expiry = Column(Date)            # موعد انتهاء رخصة المركبة (بايك/سيارة)
    vehicle_type = Column(String(60))                # نوع المركبة (بايك/سيارة/سكوتر)
    vehicle_plate = Column(String(40))               # رقم المركبة
    zone = Column(String(120))                       # منطقة/أحياء عمل المندوب
    photo_url = Column(String(300))                  # صورة المندوب
    is_on_leave = Column(Boolean, default=False)     # في إجازة اليوم
    shift_started_at = Column(DateTime)              # بداية الوردية الحية
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="couriers")
    fleet = relationship("Fleet", back_populates="couriers")
    supervisor = relationship("User", foreign_keys=[supervisor_id])


class Merchant(Base):
    """تاجر (مطعم / متجر) — عميل الجزء الثاني."""
    __tablename__ = "merchants"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    country = Column(Enum(Country), nullable=False)
    lat = Column(Float)
    lng = Column(Float)
    district = Column(String(120))       # حي / منطقة
    city = Column(String(120))
    phone = Column(String(40))
    theme = Column(String(40), default="default")   # ثيم جاهز للمتجر
    delivery_method = Column(Enum(DeliveryMethod), default=DeliveryMethod.PLATFORM_COURIER)
    slug = Column(String(80), unique=True)         # dou.sa/matarim
    category = Column(String(60))                  # تصنيف المتجر (مطعم/عطور/ملابس…)
    is_active = Column(Boolean, default=True)      # مفعّل/موقوف
    created_at = Column(DateTime, default=datetime.utcnow)


class Product(Base):
    """منتج/صنف في كتالوج التاجر."""
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(Text)
    price = Column(Float, nullable=False)
    currency = Column(String(8), default="SAR")
    is_available = Column(Boolean, default=True)
    category = Column(String(60))
    created_at = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    """طلب عميل."""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    customer_name = Column(String(120))
    customer_phone = Column(String(40))
    customer_lat = Column(Float)
    customer_lng = Column(Float)
    customer_address = Column(String(200))
    merchant_id = Column(Integer, ForeignKey("merchants.id"), nullable=False)
    delivery_method = Column(Enum(DeliveryMethod), nullable=False)
    status = Column(Enum(OrderStatus), default=OrderStatus.PLACED)
    subtotal = Column(Float, default=0.0)
    delivery_fee = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    distance_km = Column(Float, default=0.0)       # مسافة التوصيل
    courier_id = Column(Integer, ForeignKey("couriers.id"))
    shipping_ref = Column(String(80))              # رقم شحنة سمسا/أرامكس
    shipping_company = Column(String(40))
    created_at = Column(DateTime, default=datetime.utcnow)

    items = relationship("OrderItem", back_populates="order")
    courier = relationship("Courier")
    merchant = relationship("Merchant")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"))
    name = Column(String(120))
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, default=0.0)

    order = relationship("Order", back_populates="items")


class CourierTask(Base):
    """مهمة توصيل لدى مندوب."""
    __tablename__ = "courier_tasks"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    status = Column(Enum(CourierTaskStatus), default=CourierTaskStatus.OFFERED)
    offered_at = Column(DateTime, default=datetime.utcnow)
    accepted_at = Column(DateTime)
    delivered_at = Column(DateTime)
    rejection_reason = Column(String(120))


class User(Base):
    """مستخدم المنصة — تاجر / مندوب / شركة / فريق Dou / عميل."""
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("phone", "role", name="uq_user_phone_role"),)

    id = Column(Integer, primary_key=True)
    phone = Column(String(40), nullable=False)
    name = Column(String(120))
    password_hash = Column(String(200), nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    merchant_id = Column(Integer, ForeignKey("merchants.id"))
    courier_id = Column(Integer, ForeignKey("couriers.id"))
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    country = Column(Enum(Country))
    is_active = Column(Boolean, default=True)
    token_version = Column(Integer, default=0)   # يزداد عند تسجيل الخروج الجماعي = تبطل كل التوكنات
    created_at = Column(DateTime, default=datetime.utcnow)


class Shift(Base):
    """وردية مندوب — تبني تخطيط التغطية."""
    __tablename__ = "shifts"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    fleet_id = Column(Integer, ForeignKey("fleets.id"))
    name = Column(String(120))                 # مثلاً: وردية مساء شمال الرياض
    zone = Column(String(120))
    start_time = Column(String(8))             # "10:00"
    end_time = Column(String(8))               # "18:00"
    required_couriers = Column(Integer, default=0)
    status = Column(Enum(ShiftStatus), default=ShiftStatus.SCHEDULED)


class Attendance(Base):
    """حضور/انصراف GPS للمندوب."""
    __tablename__ = "attendances"

    id = Column(Integer, primary_key=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    shift_id = Column(Integer, ForeignKey("shifts.id"))
    check_in = Column(DateTime, default=datetime.utcnow)
    check_out = Column(DateTime)
    check_in_lat = Column(Float)
    check_in_lng = Column(Float)
    check_out_lat = Column(Float)
    check_out_lng = Column(Float)
    is_late = Column(Boolean, default=False)


class ShippingCompany(Base):
    """شركة شحن مرتبطة عبر API (سمسا/بوسطه/أرامكس)."""
    __tablename__ = "shipping_companies"

    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    code = Column(String(40), unique=True, nullable=False)   # SMSA / BOSTA / ARAMEX
    country = Column(Enum(Country), nullable=False)
    base_url = Column(String(200))
    api_key_encrypted = Column(String(200))   # تشفير في الإنتاج
    is_active = Column(Boolean, default=True)


class ShippingLabel(Base):
    """شحنة أُنشئت لدى شركة شحن."""
    __tablename__ = "shipping_labels"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("shipping_companies.id"), nullable=False)
    tracking_number = Column(String(80))
    status = Column(String(40), default="CREATED")
    created_at = Column(DateTime, default=datetime.utcnow)


class GeoCountry(Base):
    """دولة تشغيل — تحتوي مدناً ومناطق."""
    __tablename__ = "geo_countries"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    code = Column(String(8), nullable=False)
    flag = Column(String(16), default="🌍")
    active = Column(Boolean, default=True)

    cities = relationship("GeoCity", back_populates="country",
                          cascade="all, delete-orphan", order_by="GeoCity.id")


class GeoCity(Base):
    """مدينة ضمن دولة."""
    __tablename__ = "geo_cities"

    id = Column(Integer, primary_key=True)
    country_id = Column(Integer, ForeignKey("geo_countries.id"), nullable=False)
    name = Column(String(120), nullable=False)
    active = Column(Boolean, default=True)

    country = relationship("GeoCountry", back_populates="cities")
    districts = relationship("GeoDistrict", back_populates="city",
                             cascade="all, delete-orphan", order_by="GeoDistrict.id")


class GeoDistrict(Base):
    """حي/منطقة ضمن مدينة."""
    __tablename__ = "geo_districts"

    id = Column(Integer, primary_key=True)
    city_id = Column(Integer, ForeignKey("geo_cities.id"), nullable=False)
    name = Column(String(120), nullable=False)
    active = Column(Boolean, default=True)

    city = relationship("GeoCity", back_populates="districts")


class Contract(Base):
    """عقد توظيف/تعاقد مع مندوب أو أسطول — يحدد الأجر ومدته."""
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    fleet_id = Column(Integer, ForeignKey("fleets.id"))
    name = Column(String(120), nullable=False)
    contract_type = Column(String(20), default="FIXED")   # FIXED / PER_DELIVERY
    duration_months = Column(Integer, default=12)
    couriers_count = Column(Integer, default=0)
    base_salary = Column(Float, default=0.0)
    per_delivery_rate = Column(Float, default=6.0)
    status = Column(String(20), default="ACTIVE")          # ACTIVE / EXPIRED
    end_date = Column(DateTime)                            # تاريخ انتهاء العقد
    created_at = Column(DateTime, default=datetime.utcnow)


class SupportTicket(Base):
    """تذكرة دعم — يرفعها المندوب ويرد عليها فريق الشركة/المنصة."""
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    courier_id = Column(Integer, ForeignKey("couriers.id"))
    subject = Column(String(160))
    message = Column(Text)
    status = Column(String(20), default="OPEN")   # OPEN / REPLIED / CLOSED
    reply = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class AppSetting(Base):
    """إعدادات تشغيل/أسعار عامة (قواعد النظام، أسعار التوصيل…)."""
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    key = Column(String(80), nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Channel(Base):
    """قناة بيع على المنصة (Own / Social / Partner)."""
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    icon = Column(String(16), default="🔌")
    type = Column(String(20), default="PARTNER")     # OWN / SOCIAL / PARTNER
    commission = Column(Float, default=0.0)          # عمولة المنصة %
    is_active = Column(Boolean, default=True)
    orders_share = Column(Float, default=0.0)        # % من الطلبات
    status = Column(String(20), default="active")


class Staff(Base):
    """موظف/فريق تشغيل في المنصة."""
    __tablename__ = "staff"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(120))
    role = Column(String(60))
    access = Column(String(20), default="limited")   # full / finance / limited
    region = Column(String(60))
    status = Column(String(20), default="active")


class Project(Base):
    """مشروع/منصة/عميل خارجي — المندوب يسجل فيه أوردراته اليومية."""
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_project_tenant_name"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(120), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DailyLog(Base):
    """سجل يومي للمندوب: تاريخ + مشروع + عدد أوردرات."""
    __tablename__ = "daily_logs"
    __table_args__ = (UniqueConstraint("courier_id", "log_date", "project_id", name="uq_daily_courier_date_project"),)

    id = Column(Integer, primary_key=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    project_id = Column(Integer, ForeignKey("projects.id"))
    log_date = Column(Date, nullable=False)
    orders_count = Column(Integer, default=0)
    notes = Column(String(300))
    created_at = Column(DateTime, default=datetime.utcnow)


class BonusPlan(Base):
    """خطة بونص للمندوب على مشروع معين: تارجت + مكافأة + سعر الطلب الزائد."""
    __tablename__ = "bonus_plans"
    __table_args__ = (UniqueConstraint("courier_id", "project_id", name="uq_bonus_courier_project"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    target_orders = Column(Integer, default=0)        # 460
    bonus_amount = Column(Float, default=0.0)         # 2000 ر.س
    over_target_rate = Column(Float, default=0.0)     # 5 ر.س/طلب زائد
    created_at = Column(DateTime, default=datetime.utcnow)


class LeaveRequest(Base):
    """طلب إجازة من مندوب — موافقة المشرف ثم الأدمن."""
    __tablename__ = "leave_requests"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    from_date = Column(Date, nullable=False)
    to_date = Column(Date, nullable=False)
    reason = Column(String(300))
    status = Column(String(20), default="PENDING")   # PENDING / SUPERVISOR_APPROVED / APPROVED / REJECTED
    supervisor_id = Column(Integer, ForeignKey("users.id"))    # المشرف الذي راجع
    admin_id = Column(Integer, ForeignKey("users.id"))         # الأدمن الذي وافق أخيراً
    supervisor_comment = Column(String(300))
    admin_comment = Column(String(300))
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    """سجل تعديلات: مين غيّر إيه وإمتى."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    actor_id = Column(Integer, ForeignKey("users.id"))
    actor_name = Column(String(120))
    actor_role = Column(String(30))
    action = Column(String(160))                      # "حدّث إقامة محمد"
    entity = Column(String(40))                       # courier / leave / doc
    entity_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class BroadcastMessage(Base):
    """رسالة فورية من الأدمن/المشرف لمناديب مجموعة."""
    __tablename__ = "broadcast_messages"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    sender_id = Column(Integer, ForeignKey("users.id"))
    sender_name = Column(String(120))
    sender_role = Column(String(30))
    courier_id = Column(Integer, ForeignKey("couriers.id"))  # None = لكل المناديب
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class PerformanceNote(Base):
    """ملاحظة أداء نصية من المشرف على مندوب."""
    __tablename__ = "performance_notes"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"))
    author_name = Column(String(120))
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class CourierRating(Base):
    """تقييم شهري (1-5) للمندوب من مشرفه."""
    __tablename__ = "courier_ratings"
    __table_args__ = (UniqueConstraint("courier_id", "month", name="uq_rating_courier_month"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"))
    month = Column(String(7), nullable=False)         # "2026-08"
    score = Column(Float, default=0)                  # 1-5
    comment = Column(String(300))
    created_at = Column(DateTime, default=datetime.utcnow)
