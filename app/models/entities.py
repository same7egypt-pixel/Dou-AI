import enum
from datetime import datetime, date, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    Text,
    DateTime,
    Date,
    ForeignKey,
    Enum,
    UniqueConstraint,
    Index,
    CheckConstraint,
    Numeric,
)
from sqlalchemy.orm import relationship
from ..database import Base


def utcnow():
    """UTC as a naive datetime for compatibility with existing DB columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Country(str, enum.Enum):
    SA = "SA"
    EG = "EG"


class UserRole(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    MERCHANT = "MERCHANT"
    COURIER = "COURIER"
    COMPANY = "COMPANY"  # مسؤول شركة لوجستية
    COMPANY_ADMIN = "COMPANY_ADMIN"  # مدير نظام داخل الشركة
    OPERATIONS = "OPERATIONS"  # مدير تشغيل
    HR = "HR"  # موارد بشرية
    ACCOUNTANT = "ACCOUNTANT"  # محاسب / رواتب
    VIEWER = "VIEWER"  # مشاهدة فقط
    PROJECT_MANAGER = "PROJECT_MANAGER"
    SUPERVISOR = "SUPERVISOR"  # مشرف على مجموعة مناديب داخل الشركة
    DOU_OPS = "DOU_OPS"  # فريق Dou الداخلي
    DOU_ADMIN = "DOU_ADMIN"  # مدير المنصة


class CustomerType(str, enum.Enum):
    """نوع العميل — يحدد نموذج التشغيل."""

    LOGISTICS_OPERATOR = "LOGISTICS_OPERATOR"  # شركة لوجستية تدير مناديبها مباشرة
    DELIVERY_PLATFORM = "DELIVERY_PLATFORM"  # منصة تدير شركات لوجستية/موردين


class Capability(str, enum.Enum):
    """قدرات العميل — تحدد السلوك المتاح."""

    MANAGE_OPERATORS = "MANAGE_OPERATORS"
    MANAGE_SUPERVISORS = "MANAGE_SUPERVISORS"
    MANAGE_RIDERS = "MANAGE_RIDERS"
    RIDER_PAYROLL = "RIDER_PAYROLL"
    OPERATOR_SETTLEMENTS = "OPERATOR_SETTLEMENTS"
    DOU_SHIFT_MANAGEMENT = "DOU_SHIFT_MANAGEMENT"
    EXTERNAL_SHIFT_SOURCE = "EXTERNAL_SHIFT_SOURCE"
    MANUAL_PERFORMANCE_IMPORT = "MANUAL_PERFORMANCE_IMPORT"
    PERFORMANCE_API_INGESTION = "PERFORMANCE_API_INGESTION"
    ORDER_API_INGESTION = "ORDER_API_INGESTION"


class ShiftStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliveryMethod(str, enum.Enum):
    SELF = "SELF"  # وصل بنفسك — مندوب التاجر
    PLATFORM_COURIER = "PLATFORM"  # وصل عن طريقنا — مناديب شركات / فريلانسر
    SHIPPING_COMPANY = "SHIPPING"  # شركة شحن (سمسا/بوسطه/أرامكس) عبر API


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
    COMPANY = "COMPANY"  # مندوب شركة لوجستية (Saudi)
    FREELANCER = "FREELANCER"  # فريلانسر (Egypt)


class Tenant(Base):
    """شركة لوجستية أو كيان يعمل على المنصة (multi-tenant)."""

    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    country = Column(Enum(Country), nullable=False)
    market_code = Column(String(2), default="SA")
    default_language = Column(String(5), default="ar")
    currency = Column(String(3), default="SAR")
    timezone = Column(String(60), default="Asia/Riyadh")
    contact_email = Column(String(120))
    contact_phone = Column(String(40))
    is_dou_internal = Column(Boolean, default=False)  # فريق Dou ops
    plan = Column(String(20), default="PRO")  # TRIAL / PRO / ENTERPRISE
    monthly_fee = Column(Float, default=0.0)  # رسوم الاشتراك الشهري
    billing_day = Column(Integer, default=1)  # يوم الفوترة بالشهر
    due_date = Column(DateTime)  # تاريخ استحقاق الفاتورة القادم
    subscription_status = Column(
        String(20), default="ACTIVE"
    )  # ACTIVE / OVERDUE / SUSPENDED
    last_paid_at = Column(DateTime)
    last_activity_at = Column(DateTime)
    # W10.5: Customer type and capabilities
    customer_type = Column(
        String(30), default="LOGISTICS_OPERATOR"
    )  # LOGISTICS_OPERATOR / DELIVERY_PLATFORM
    capabilities = Column(Text, default="[]")  # JSON list of Capability values
    created_at = Column(DateTime, default=utcnow)

    fleets = relationship("Fleet", back_populates="tenant")
    couriers = relationship("Courier", back_populates="tenant")


class Fleet(Base):
    """أسطول/مجموعة مناديب تابعة لشركة أو منطقة."""

    __tablename__ = "fleets"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(120), nullable=False)
    zone = Column(String(120))  # مثلاً: شمال الرياض
    is_ondemand_pool = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

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
    lat = Column(Float)  # GPS لحظي
    lng = Column(Float)
    is_online = Column(Boolean, default=False)
    is_available = Column(Boolean, default=True)
    current_load = Column(Integer, default=0)  # عدد الطلبات الحية
    acceptance_rate = Column(Float, default=100.0)
    on_time_rate = Column(Float, default=100.0)
    completion_rate = Column(Float, default=100.0)
    score = Column(Float, default=5.0)
    documents_valid = Column(Boolean, default=True)  # مستندات سارية
    shift_active = Column(Boolean, default=False)
    # ===== حقول HR =====
    base_salary = Column(Float, default=0.0)  # راتب ثابت شهري (ر.س)
    per_delivery_rate = Column(Float, default=6.0)  # أجر كل توصيلة
    bonus_target = Column(Float, default=0.0)  # نسبة/مبلغ البونص الشهري
    employment_status = Column(
        String(20), default="ACTIVE"
    )  # ACTIVE / SUSPENDED / TERMINATED
    hired_at = Column(DateTime, default=utcnow)  # تاريخ التعيين
    bank_iban = Column(String(34))  # IBAN لتحويل الراتب
    nationality = Column(String(60))  # جنسية المندوب
    iqama_number = Column(String(40))
    emergency_name = Column(String(120))
    emergency_phone = Column(String(40))
    passport_number = Column(String(40))
    passport_expiry = Column(Date)
    insurance_expiry = Column(Date)
    inspection_expiry = Column(Date)
    work_permit_expiry = Column(Date)
    supervisor_id = Column(Integer, ForeignKey("users.id"))  # المشرف المسؤول عن المندوب
    primary_project_id = Column(Integer, ForeignKey("projects.id"))  # المشروع الأساسي
    contract_id = Column(Integer, ForeignKey("contracts.id"))
    contract_branch_id = Column(Integer, ForeignKey("contract_branches.id"))
    city_id = Column(Integer, ForeignKey("geo_cities.id"))  # المدينة التشغيلية المعتمدة
    work_city = Column(
        String(120)
    )  # عرض/بيانات قديمة؛ تُشتق من city_id أو الفرع عند توفرهما
    platform = Column(String(60))  # المنصة/المشروع الرئيسي (هنقرستيشن/جاهز/...)
    platform_courier_id = Column(String(60))  # كود/ID المندوب داخل المنصة الخارجية
    iqama_expiry = Column(Date)  # موعد انتهاء الإقامة
    license_expiry = Column(Date)  # موعد انتهاء رخصة القيادة
    vehicle_license_expiry = Column(Date)  # موعد انتهاء رخصة المركبة (بايك/سيارة)
    vehicle_type = Column(String(60))  # نوع المركبة (بايك/سيارة/سكوتر)
    vehicle_plate = Column(String(40))  # رقم المركبة
    zone = Column(String(120))  # منطقة/أحياء عمل المندوب
    photo_url = Column(String(300))  # صورة المندوب
    is_on_leave = Column(Boolean, default=False)  # في إجازة اليوم
    shift_started_at = Column(DateTime)  # بداية الوردية الحية
    shift_preference = Column(String(120))  # الوردية المعتمدة/المطلوبة
    created_at = Column(DateTime, default=utcnow)

    tenant = relationship("Tenant", back_populates="couriers")
    fleet = relationship("Fleet", back_populates="couriers")
    supervisor = relationship("User", foreign_keys=[supervisor_id])
    primary_project = relationship("Project", foreign_keys=[primary_project_id])


class Merchant(Base):
    """تاجر (مطعم / متجر) — عميل الجزء الثاني."""

    __tablename__ = "merchants"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    country = Column(Enum(Country), nullable=False)
    lat = Column(Float)
    lng = Column(Float)
    district = Column(String(120))  # حي / منطقة
    city = Column(String(120))
    phone = Column(String(40))
    theme = Column(String(40), default="default")  # ثيم جاهز للمتجر
    delivery_method = Column(
        Enum(DeliveryMethod), default=DeliveryMethod.PLATFORM_COURIER
    )
    slug = Column(String(80), unique=True)  # dou.sa/matarim
    category = Column(String(60))  # تصنيف المتجر (مطعم/عطور/ملابس…)
    is_active = Column(Boolean, default=True)  # مفعّل/موقوف
    created_at = Column(DateTime, default=utcnow)


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
    created_at = Column(DateTime, default=utcnow)


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
    distance_km = Column(Float, default=0.0)  # مسافة التوصيل
    courier_id = Column(Integer, ForeignKey("couriers.id"))
    shipping_ref = Column(String(80))  # رقم شحنة سمسا/أرامكس
    shipping_company = Column(String(40))
    created_at = Column(DateTime, default=utcnow)

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
    offered_at = Column(DateTime, default=utcnow)
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
    token_version = Column(
        Integer, default=0
    )  # يزداد عند تسجيل الخروج الجماعي = تبطل كل التوكنات
    last_login_at = Column(DateTime)
    custom_permissions = Column(Text)  # JSON permissions override
    managed_project_ids = Column(Text)  # JSON list for project managers
    created_at = Column(DateTime, default=utcnow)


class Shift(Base):
    """وردية مندوب — تبني تخطيط التغطية."""

    __tablename__ = "shifts"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    fleet_id = Column(Integer, ForeignKey("fleets.id"))
    name = Column(String(120))  # مثلاً: وردية مساء شمال الرياض
    zone = Column(String(120))
    start_time = Column(String(8))  # "10:00"
    end_time = Column(String(8))  # "18:00"
    required_couriers = Column(Integer, default=0)
    courier_ids = Column(Text)  # JSON: المناديب المسندون لهذه الوردية المتكررة
    status = Column(Enum(ShiftStatus), default=ShiftStatus.SCHEDULED)


class Attendance(Base):
    """حضور/انصراف GPS للمندوب."""

    __tablename__ = "attendances"

    id = Column(Integer, primary_key=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    shift_id = Column(Integer, ForeignKey("shifts.id"))
    check_in = Column(DateTime, default=utcnow)
    check_out = Column(DateTime)
    check_in_lat = Column(Float)
    check_in_lng = Column(Float)
    check_out_lat = Column(Float)
    check_out_lng = Column(Float)
    is_late = Column(Boolean, default=False)


class ShiftTemplate(Base):
    """قالب وردية متكرر — يُستخدم لإنشاء تواريخ ورديات يومية/أسبوعية."""

    __tablename__ = "shift_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_shift_template_tenant_code"),
        Index("ix_shift_template_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    code = Column(String(40), nullable=False)
    name_ar = Column(String(120), nullable=False)
    name_en = Column(String(120))
    zone = Column(String(120))
    start_time = Column(String(8), nullable=False)  # "10:00"
    end_time = Column(String(8), nullable=False)  # "18:00"
    required_couriers = Column(Integer, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class ShiftOccurrence(Base):
    """حدوث وردية محدد بتاريخ — نسخة فعلية من القالب في يوم معين."""

    __tablename__ = "shift_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "shift_template_id", "occurrence_date", name="uq_shift_occurrence_date"
        ),
        Index("ix_shift_occurrence_tenant_date", "tenant_id", "occurrence_date"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    shift_template_id = Column(
        Integer, ForeignKey("shift_templates.id"), nullable=False, index=True
    )
    occurrence_date = Column(Date, nullable=False)
    start_datetime = Column(DateTime, nullable=False)
    end_datetime = Column(DateTime, nullable=False)
    required_couriers = Column(Integer, default=0)
    status = Column(
        String(20), default="SCHEDULED"
    )  # SCHEDULED / ACTIVE / COMPLETED / CANCELLED
    created_at = Column(DateTime, default=utcnow, nullable=False)


class WorkSession(Base):
    """سجل جلسة عمل/استراحة للمندوب خلال وردية."""

    __tablename__ = "work_sessions"
    __table_args__ = (
        Index("ix_work_session_tenant_courier", "tenant_id", "courier_id"),
        Index("ix_work_session_shift", "shift_occurrence_id"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    shift_occurrence_id = Column(
        Integer, ForeignKey("shift_occurrences.id"), index=True
    )
    session_type = Column(String(20), nullable=False)  # WORK / BREAK
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime)
    duration_minutes = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class AttendanceCorrectionRequest(Base):
    """طلب تصحيح حضور من السائق أو المشرف — يُتخذ قرار فيه من الشركة."""

    __tablename__ = "attendance_correction_requests"
    __table_args__ = (
        Index("ix_attendance_correction_tenant_status", "tenant_id", "status"),
        Index("ix_attendance_correction_courier", "courier_id"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    attendance_id = Column(Integer, ForeignKey("attendances.id"))
    requested_check_in = Column(DateTime)
    requested_check_out = Column(DateTime)
    reason = Column(String(300), nullable=False)
    status = Column(String(20), default="PENDING")  # PENDING / APPROVED / REJECTED
    requested_by = Column(Integer, ForeignKey("users.id"))
    decided_by = Column(Integer, ForeignKey("users.id"))
    decided_at = Column(DateTime)
    decision_note = Column(String(300))
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Overtime(Base):
    """ساعات إضافية معتمدة للمندوب."""

    __tablename__ = "overtimes"
    __table_args__ = (
        Index("ix_overtime_tenant_courier", "tenant_id", "courier_id"),
        Index("ix_overtime_tenant_date", "tenant_id", "overtime_date"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    shift_occurrence_id = Column(
        Integer, ForeignKey("shift_occurrences.id"), index=True
    )
    overtime_date = Column(Date, nullable=False)
    requested_minutes = Column(Integer, nullable=False)
    approved_minutes = Column(Integer, default=0)
    status = Column(String(20), default="PENDING")  # PENDING / APPROVED / REJECTED
    requested_by = Column(Integer, ForeignKey("users.id"))
    approved_by = Column(Integer, ForeignKey("users.id"))
    approved_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class ShippingCompany(Base):
    """شركة شحن مرتبطة عبر API (سمسا/بوسطه/أرامكس)."""

    __tablename__ = "shipping_companies"

    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    code = Column(String(40), unique=True, nullable=False)  # SMSA / BOSTA / ARAMEX
    country = Column(Enum(Country), nullable=False)
    base_url = Column(String(200))
    api_key_encrypted = Column(String(200))  # تشفير في الإنتاج
    is_active = Column(Boolean, default=True)


class ShippingLabel(Base):
    """شحنة أُنشئت لدى شركة شحن."""

    __tablename__ = "shipping_labels"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("shipping_companies.id"), nullable=False)
    tracking_number = Column(String(80))
    status = Column(String(40), default="CREATED")
    created_at = Column(DateTime, default=utcnow)


class GeoCountry(Base):
    """دولة تشغيل — تحتوي مدناً ومناطق."""

    __tablename__ = "geo_countries"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    code = Column(String(8), nullable=False)
    flag = Column(String(16), default="🌍")
    active = Column(Boolean, default=True)

    cities = relationship(
        "GeoCity",
        back_populates="country",
        cascade="all, delete-orphan",
        order_by="GeoCity.id",
    )


class GeoCity(Base):
    """مدينة ضمن دولة."""

    __tablename__ = "geo_cities"

    id = Column(Integer, primary_key=True)
    country_id = Column(Integer, ForeignKey("geo_countries.id"), nullable=False)
    name = Column(String(120), nullable=False)
    active = Column(Boolean, default=True)

    country = relationship("GeoCountry", back_populates="cities")
    districts = relationship(
        "GeoDistrict",
        back_populates="city",
        cascade="all, delete-orphan",
        order_by="GeoDistrict.id",
    )


class TenantOperatingCity(Base):
    """تفعيل مدينة مرجعية ضمن نطاق شركة محددة؛ مصدر حقيقة التشغيل للمدينة."""

    __tablename__ = "tenant_operating_cities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "geo_city_id", name="uq_tenant_operating_city"),
        Index("ix_tenant_operating_city_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    geo_city_id = Column(
        Integer, ForeignKey("geo_cities.id"), nullable=False, index=True
    )
    display_name = Column(String(120))  # تسمية الشركة للمدينة؛ لا تغيّر المرجع العالمي
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class OperatingZone(Base):
    """Tenant-owned operating zone within an activated city."""

    __tablename__ = "operating_zones"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_operating_zone_tenant_code"),
        Index("ix_operating_zone_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    operating_city_id = Column(
        Integer, ForeignKey("tenant_operating_cities.id"), nullable=False, index=True
    )
    code = Column(String(40), nullable=False)
    name_ar = Column(String(120), nullable=False)
    name_en = Column(String(120))
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class WorkforceTeam(Base):
    """Effective workforce grouping owned by one tenant and optional zone."""

    __tablename__ = "workforce_teams"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_workforce_team_tenant_code"),
        Index("ix_workforce_team_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    zone_id = Column(Integer, ForeignKey("operating_zones.id"), index=True)
    code = Column(String(40), nullable=False)
    name_ar = Column(String(120), nullable=False)
    name_en = Column(String(120))
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class TeamMembership(Base):
    """Effective-dated rider membership preserving all transfer history."""

    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint(
            "team_id", "courier_id", "effective_from", name="uq_team_membership_start"
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_team_membership_dates",
        ),
        Index("ix_team_membership_tenant_courier", "tenant_id", "courier_id"),
        Index(
            "ix_team_membership_team_dates", "team_id", "effective_from", "effective_to"
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    team_id = Column(
        Integer, ForeignKey("workforce_teams.id"), nullable=False, index=True
    )
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    is_primary = Column(Boolean, default=True, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=utcnow, nullable=False)


class TeamSupervisorAssignment(Base):
    """Effective-dated source of supervisor scope for a workforce team."""

    __tablename__ = "team_supervisor_assignments"
    __table_args__ = (
        UniqueConstraint(
            "team_id",
            "supervisor_id",
            "effective_from",
            name="uq_team_supervisor_start",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_team_supervisor_dates",
        ),
        Index("ix_team_supervisor_tenant_user", "tenant_id", "supervisor_id"),
        Index(
            "ix_team_supervisor_team_dates", "team_id", "effective_from", "effective_to"
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    team_id = Column(
        Integer, ForeignKey("workforce_teams.id"), nullable=False, index=True
    )
    supervisor_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Vehicle(Base):
    """Tenant-owned fleet asset with separate operational/compliance state."""

    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "market_code",
            "plate_normalized",
            name="uq_vehicle_tenant_market_plate",
        ),
        Index("ix_vehicle_tenant_operational", "tenant_id", "operational_status"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    market_code = Column(String(2), nullable=False)
    plate_number = Column(String(40), nullable=False)
    plate_normalized = Column(String(40), nullable=False)
    vehicle_type = Column(String(30), nullable=False)
    make = Column(String(60))
    model = Column(String(60))
    model_year = Column(Integer)
    operational_status = Column(String(30), default="ACTIVE", nullable=False)
    compliance_status = Column(String(30), default="MISSING", nullable=False)
    is_exclusive = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class VehicleDocument(Base):
    """Compliance metadata; binary storage is handled by the KYC pipeline."""

    __tablename__ = "vehicle_documents"
    __table_args__ = (
        Index("ix_vehicle_document_tenant_vehicle", "tenant_id", "vehicle_id"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False, index=True)
    document_type = Column(String(40), nullable=False)
    document_number = Column(String(80))
    expiry_date = Column(Date)
    status = Column(String(20), default="VALID", nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=utcnow, nullable=False)


class RiderVehicleAssignment(Base):
    """Effective-dated vehicle assignment preserving transfer history."""

    __tablename__ = "rider_vehicle_assignments"
    __table_args__ = (
        UniqueConstraint(
            "vehicle_id", "courier_id", "effective_from", name="uq_rider_vehicle_start"
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_rider_vehicle_dates",
        ),
        Index("ix_rider_vehicle_tenant_rider", "tenant_id", "courier_id"),
        Index(
            "ix_rider_vehicle_vehicle_dates",
            "vehicle_id",
            "effective_from",
            "effective_to",
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False, index=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    is_primary = Column(Boolean, default=True, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=utcnow, nullable=False)


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
    project_id = Column(Integer, ForeignKey("projects.id"))
    scope_type = Column(
        String(20), default="PROJECT"
    )  # COURIER / PROJECT / MANUAL / COMMERCIAL / LEGACY
    courier_ids = Column(Text)  # JSON list for direct/manual assignment
    name = Column(String(120), nullable=False)
    client_name = Column(String(120))  # العميل/المنصة التجارية
    client_rate_per_order = Column(Float)  # سعر الطلب من العميل، لا يمثل أجر المندوب
    client_rate_effective_from = Column(Date)  # تاريخ نفاذ السعر التجاري
    contract_type = Column(String(20), default="FIXED")  # FIXED / PER_DELIVERY
    duration_months = Column(Integer, default=12)
    couriers_count = Column(Integer, default=0)
    base_salary = Column(Float, default=0.0)
    per_delivery_rate = Column(Float, default=6.0)
    status = Column(String(20), default="ACTIVE")  # ACTIVE / EXPIRED
    start_date = Column(DateTime)  # تاريخ بداية العقد
    end_date = Column(DateTime)  # تاريخ انتهاء العقد
    created_at = Column(DateTime, default=utcnow)


class ContractBranch(Base):
    """فرع تشغيلي داخل عقد تجاري: مدينة + مشروع + مشرف مسؤول + إحداثيات الحضور."""

    __tablename__ = "contract_branches"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    city_id = Column(Integer, ForeignKey("geo_cities.id"))
    city = Column(String(120), nullable=False)  # حقل عرض/تراث يُرحّل بأمان إلى city_id
    project_id = Column(Integer, ForeignKey("projects.id"))
    supervisor_id = Column(Integer, ForeignKey("users.id"))
    branch_name = Column(String(120))
    latitude = Column(Float)
    longitude = Column(Float)
    geofence_radius_meters = Column(Integer, default=150)
    dedicated_riders_target = Column(Integer, default=3)
    monthly_rate_per_rider = Column(Float, default=4500.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)


class ClientInvoice(Base):
    """فاتورة مطالبة مالية للعميل التجاري (مطعم/منصة) مع احتساب هوامش الربح."""

    __tablename__ = "client_invoices"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "invoice_number", name="uq_client_invoice_number"
        ),
        Index("ix_client_invoices_tenant_month", "tenant_id", "billing_month"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    contract_id = Column(
        Integer, ForeignKey("contracts.id"), nullable=False, index=True
    )
    invoice_number = Column(String(60), nullable=False)
    billing_month = Column(String(7), nullable=False)  # "2026-08"
    client_name = Column(String(120), nullable=False)
    total_riders_supplied = Column(Integer, default=0)
    total_shifts_served = Column(Integer, default=0)
    total_amount_billed = Column(Float, default=0.0)  # قيمة الفاتورة الصادرة للعميل
    total_courier_payroll_cost = Column(
        Float, default=0.0
    )  # إجمالي تكلفة رواتب المناديب المخصصين
    net_gross_profit = Column(
        Float, default=0.0
    )  # صافي الربح من العقد (المطالبة - التكلفة)
    profit_margin_pct = Column(Float, default=0.0)  # نسبة هامش الربح %
    status = Column(String(20), default="ISSUED")  # DRAFT / ISSUED / PAID / CANCELLED
    issue_date = Column(Date, default=date.today)
    due_date = Column(Date)
    paid_at = Column(DateTime)
    notes = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ClientInvoiceItem(Base):
    """بند تفصيلي في فاتورة العميل: فرع + سائق + الأجر اليومي/الشهري + الإضافي."""

    __tablename__ = "client_invoice_items"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    invoice_id = Column(
        Integer, ForeignKey("client_invoices.id"), nullable=False, index=True
    )
    contract_branch_id = Column(
        Integer, ForeignKey("contract_branches.id"), nullable=True
    )
    branch_name = Column(String(120))
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=True)
    courier_name = Column(String(120))
    days_worked = Column(Integer, default=30)
    monthly_rate = Column(Float, default=0.0)
    overtime_amount = Column(Float, default=0.0)
    total_line_amount = Column(Float, default=0.0)
    courier_cost_share = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utcnow)


class SupportTicket(Base):
    """تذكرة دعم — يرفعها المندوب ويرد عليها فريق الشركة/المنصة."""

    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    courier_id = Column(Integer, ForeignKey("couriers.id"))
    subject = Column(String(160))
    message = Column(Text)
    status = Column(String(20), default="OPEN")  # OPEN / REPLIED / CLOSED
    reply = Column(Text)
    created_at = Column(DateTime, default=utcnow)


class AppSetting(Base):
    """إعدادات تشغيل/أسعار عامة (قواعد النظام، أسعار التوصيل…)."""

    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    key = Column(String(80), nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Channel(Base):
    """قناة بيع على المنصة (Own / Social / Partner)."""

    __tablename__ = "channels"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    icon = Column(String(16), default="🔌")
    type = Column(String(20), default="PARTNER")  # OWN / SOCIAL / PARTNER
    commission = Column(Float, default=0.0)  # عمولة المنصة %
    is_active = Column(Boolean, default=True)
    orders_share = Column(Float, default=0.0)  # % من الطلبات
    status = Column(String(20), default="active")


class Staff(Base):
    """موظف/فريق تشغيل في المنصة."""

    __tablename__ = "staff"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(120))
    role = Column(String(60))
    access = Column(String(20), default="limited")  # full / finance / limited
    region = Column(String(60))
    status = Column(String(20), default="active")


class Project(Base):
    """مشروع/منصة/عميل خارجي — المندوب يسجل فيه أوردراته اليومية."""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_project_tenant_name"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String(120), nullable=False)
    manager_id = Column(Integer, ForeignKey("users.id"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)


class DailyLog(Base):
    """سجل يومي للمندوب: تاريخ + مشروع + عدد أوردرات."""

    __tablename__ = "daily_logs"
    __table_args__ = (
        UniqueConstraint(
            "courier_id", "log_date", "project_id", name="uq_daily_courier_date_project"
        ),
        Index(
            "ix_daily_logs_tenant_date_project", "tenant_id", "log_date", "project_id"
        ),
    )

    id = Column(Integer, primary_key=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    project_id = Column(Integer, ForeignKey("projects.id"))
    log_date = Column(Date, nullable=False)
    orders_count = Column(Integer, default=0)
    source_type = Column(
        String(30), default="MANUAL"
    )  # MANUAL / FILE_IMPORT / FUTURE_API
    source_batch_id = Column(Integer, ForeignKey("operational_import_batches.id"))
    source_row_key = Column(String(180))
    notes = Column(String(300))
    created_at = Column(DateTime, default=utcnow)


class PlatformDeliveryFact(Base):
    """حقائق وسجلات تشغيل المنصات الخام (19 عمود) الواردة عبر API أو ملف CSV."""

    __tablename__ = "platform_delivery_facts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "contract_name",
            "created_date",
            name="uq_platform_delivery_tenant_contract_date",
        ),
        Index("ix_platform_delivery_facts_tenant_date", "tenant_id", "created_date"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    created_date = Column(Date, nullable=False)
    city_name = Column(String(100), default="Riyadh")
    contract_name = Column(String(100), nullable=False)
    riders_count = Column(Integer, default=0)
    shifts_done = Column(Integer, default=0)
    planned_hours = Column(Float, default=0.0)
    actual_working_hours = Column(Float, default=0.0)
    break_hours = Column(Float, default=0.0)
    acceptance_rate = Column(Float, default=1.0)
    contact_rate = Column(Float, default=0.0)
    no_shows = Column(Integer, default=0)
    notified_deliveries = Column(Integer, default=0)
    completed_deliveries = Column(Integer, default=0)
    accepted_deliveries = Column(Integer, default=0)
    stacked_deliveries = Column(Integer, default=0)
    declined_deliveries = Column(Integer, default=0)
    cancelled_deliveries = Column(Integer, default=0)
    deduction_deliveries = Column(Integer, default=0)
    not_accepted_deliveries = Column(Integer, default=0)
    source_type = Column(String(30), default="API")
    created_at = Column(DateTime, default=utcnow)


class ContractBranchSupervisor(Base):
    """إسناد متعدد للمشرفين على نفس فرع العقد."""

    __tablename__ = "contract_branch_supervisors"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    contract_branch_id = Column(
        Integer, ForeignKey("contract_branches.id"), nullable=False
    )
    supervisor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)


class BonusPlan(Base):
    """خطة بونص لعقد/مشروع (تُطبق على كل مندوبيه) أو لفرع أو لمندوب محدد.
    تدعم: (1) خطة التارجت المركبة مع سعر ما دون المستهدف، (2) خطة سعر الطلب المباشر."""

    __tablename__ = "bonus_plans"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    contract_branch_id = Column(
        Integer, ForeignKey("contract_branches.id"), nullable=True
    )
    plan_type = Column(
        String(50), default="TARGET_TIER"
    )  # 'TARGET_TIER' | 'FLAT_PER_ORDER'
    target_orders = Column(Integer, default=0)  # تارجت الطلبات (مثال: 200)
    bonus_amount = Column(
        Float, default=0.0
    )  # حافز تحقيق التارجت المقطوع (مثال: 500 ر.س)
    over_target_rate = Column(
        Float, default=0.0
    )  # أجر الطلب الإضافي فوق التارجت (مثال: 3 ر.س)
    below_target_rate = Column(
        Float, default=0.0
    )  # أجر الطلب عند عدم تحقيق التارجت (مثال: 12 ر.س)
    flat_order_rate = Column(
        Float, default=0.0
    )  # أجر الطلب المباشر للخطة الثابتة (مثال: 15 ر.س)
    is_active = Column(Boolean, default=True, nullable=False)
    effective_from = Column(Date, default=date.today)
    effective_to = Column(Date)
    created_at = Column(DateTime, default=utcnow)


class LeaveRequest(Base):
    """طلب إجازة من مندوب — موافقة المشرف ثم الأدمن."""

    __tablename__ = "leave_requests"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    leave_type_id = Column(Integer, ForeignKey("leave_types.id"))
    from_date = Column(Date, nullable=False)
    to_date = Column(Date, nullable=False)
    reason = Column(String(300))
    status = Column(
        String(20), default="PENDING"
    )  # PENDING / SUPERVISOR_APPROVED / APPROVED / REJECTED
    supervisor_id = Column(Integer, ForeignKey("users.id"))
    admin_id = Column(Integer, ForeignKey("users.id"))
    supervisor_comment = Column(String(300))
    admin_comment = Column(String(300))
    created_at = Column(DateTime, default=utcnow)


class LeaveType(Base):
    """نوع إجازة — سنوية، مرضية، طارئة، إلخ."""

    __tablename__ = "leave_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_leave_type_tenant_code"),
        Index("ix_leave_type_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    code = Column(String(40), nullable=False)
    name_ar = Column(String(120), nullable=False)
    name_en = Column(String(120))
    description_ar = Column(String(300))
    description_en = Column(String(300))
    is_paid = Column(Boolean, default=True, nullable=False)
    max_days_per_year = Column(Integer)
    requires_document = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class LeavePolicy(Base):
    """سياسة إجازة للشركة — قواعد الاستحقاق والتراكم."""

    __tablename__ = "leave_policies"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "leave_type_id", name="uq_leave_policy_tenant_type"
        ),
        Index("ix_leave_policy_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    leave_type_id = Column(
        Integer, ForeignKey("leave_types.id"), nullable=False, index=True
    )
    entitlement_days = Column(Integer, default=0)
    carryover_limit = Column(Integer, default=0)
    max_consecutive_days = Column(Integer)
    min_days_notice = Column(Integer, default=0)
    accrual_frequency = Column(String(20), default="YEARLY")  # YEARLY / MONTHLY
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class LeaveEntitlement(Base):
    """رصيد إجازة المندوب — المتاح والمستخدم."""

    __tablename__ = "leave_entitlements"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "courier_id",
            "leave_type_id",
            "year",
            name="uq_leave_entitlement",
        ),
        Index("ix_leave_entitlement_tenant_courier", "tenant_id", "courier_id"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    leave_type_id = Column(
        Integer, ForeignKey("leave_types.id"), nullable=False, index=True
    )
    year = Column(Integer, nullable=False)
    entitled_days = Column(Integer, default=0)
    carried_over_days = Column(Integer, default=0)
    used_days = Column(Integer, default=0)
    pending_days = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class SupervisorAssignmentRequest(Base):
    """طلب من المشرف لضم سائق لمجموعته، ولا يُنفذ إلا بعد موافقة إدارة الشركة."""

    __tablename__ = "supervisor_assignment_requests"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    supervisor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    status = Column(String(20), default="PENDING")
    note = Column(String(300))
    reviewed_by = Column(Integer, ForeignKey("users.id"))
    reviewed_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow)


class AuditLog(Base):
    """سجل تعديلات: مين غيّر إيه وإمتى."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    actor_id = Column(Integer, ForeignKey("users.id"))
    actor_name = Column(String(120))
    actor_role = Column(String(30))
    action = Column(String(160))  # "حدّث إقامة محمد"
    entity = Column(String(40))  # courier / leave / doc
    entity_id = Column(Integer)
    created_at = Column(DateTime, default=utcnow)


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
    created_at = Column(DateTime, default=utcnow)


class PerformanceNote(Base):
    """ملاحظة أداء نصية من المشرف على مندوب."""

    __tablename__ = "performance_notes"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"))
    author_name = Column(String(120))
    note = Column(Text)
    created_at = Column(DateTime, default=utcnow)


class CourierRating(Base):
    """تقييم شهري (1-5) للمندوب من مشرفه."""

    __tablename__ = "courier_ratings"
    __table_args__ = (
        UniqueConstraint("courier_id", "month", name="uq_rating_courier_month"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"))
    month = Column(String(7), nullable=False)  # "2026-08"
    score = Column(Float, default=0)  # 1-5
    comment = Column(String(300))
    created_at = Column(DateTime, default=utcnow)


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    id = Column(Integer, primary_key=True)
    code = Column(String(30), unique=True, nullable=False)
    name = Column(String(80), nullable=False)
    name_en = Column(String(80))
    monthly_price = Column(Float, default=0)
    monthly_price_usd = Column(Float, default=0)
    max_couriers = Column(Integer, default=0)
    features_ar = Column(Text)
    features_en = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"))
    actor_name = Column(String(120))
    action = Column(Text, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"))
    entity = Column(String(50))
    entity_id = Column(Integer)
    created_at = Column(DateTime, default=utcnow)


class SubscriptionPayment(Base):
    """دفعة اشتراك مسجلة يدويًا أو إلكترونيًا مع مرجع قابل للمراجعة."""

    __tablename__ = "subscription_payments"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="SAR")
    payment_method = Column(String(30), default="CASH")
    paid_at = Column(DateTime, nullable=False, default=utcnow)
    period_months = Column(Integer, default=1)
    reference = Column(String(100))
    receipt_number = Column(String(60), unique=True, nullable=False)
    notes = Column(Text)
    recorded_by_id = Column(Integer, ForeignKey("users.id"))
    recorded_by_name = Column(String(120))
    created_at = Column(DateTime, default=utcnow)


class ProjectTransfer(Base):
    __tablename__ = "project_transfers"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    from_project_id = Column(Integer, ForeignKey("projects.id"))
    to_project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    changed_by = Column(Integer, ForeignKey("users.id"))
    note = Column(String(300))
    created_at = Column(DateTime, default=utcnow)


class PayrollPeriod(Base):
    """فترة رواتب شهرية: المسودة تحسب من المصادر الحية، والنهائية تُثبت لقطات المندوبين."""

    __tablename__ = "payroll_periods"
    __table_args__ = (
        UniqueConstraint("tenant_id", "month", name="uq_payroll_period_tenant_month"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    month = Column(String(7), nullable=False)
    status = Column(String(20), default="DRAFT", nullable=False)  # DRAFT / FINALIZED
    finalized_by = Column(Integer, ForeignKey("users.id"))
    finalized_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow)


class PayrollSnapshot(Base):
    """لقطة مبلغ مندوب ضمن فترة نهائية؛ تمنع تعديل إعدادات اليوم من تغيير التاريخ."""

    __tablename__ = "payroll_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "payroll_period_id", "courier_id", name="uq_payroll_snapshot_period_courier"
        ),
        Index(
            "ix_payroll_snapshot_tenant_period_branch",
            "tenant_id",
            "payroll_period_id",
            "contract_branch_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    payroll_period_id = Column(
        Integer, ForeignKey("payroll_periods.id"), nullable=False, index=True
    )
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    contract_branch_id = Column(Integer, ForeignKey("contract_branches.id"))
    base_salary = Column(Float, default=0)
    delivery_pay = Column(Float, default=0)
    bonus_pay = Column(Float, default=0)
    additions = Column(Float, default=0)
    deductions = Column(Float, default=0)
    net_pay = Column(Float, default=0)
    calculation_data = Column(Text)  # JSON للمراجعة والتتبع
    created_at = Column(DateTime, default=utcnow)


class OperationalFinancialSnapshot(Base):
    """لقطة الإيراد التجاري والتكلفة المباشرة والهامش التشغيلي لفرع ضمن فترة نهائية."""

    __tablename__ = "operational_financial_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "payroll_period_id",
            "contract_branch_id",
            name="uq_financial_snapshot_period_branch",
        ),
        Index(
            "ix_financial_snapshot_tenant_period_project",
            "tenant_id",
            "payroll_period_id",
            "project_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    payroll_period_id = Column(
        Integer, ForeignKey("payroll_periods.id"), nullable=False, index=True
    )
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    contract_branch_id = Column(
        Integer, ForeignKey("contract_branches.id"), nullable=False, index=True
    )
    project_id = Column(Integer, ForeignKey("projects.id"))
    eligible_orders = Column(Integer, default=0)
    client_rate_per_order = Column(Float, default=0)
    client_revenue = Column(Float, default=0)
    direct_rider_cost = Column(Float, default=0)
    operational_margin = Column(Float, default=0)
    calculation_data = Column(Text)
    created_at = Column(DateTime, default=utcnow)


class OperationalImportBatch(Base):
    """دفعة استيراد تشغيلية قابلة للمراجعة؛ تخزن المعاينة والنتيجة دون إنشاء بيانات جزئية."""

    __tablename__ = "operational_import_batches"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "import_type",
            "fingerprint",
            name="uq_operational_import_fingerprint",
        ),
        Index(
            "ix_operational_import_tenant_type_status",
            "tenant_id",
            "import_type",
            "status",
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    import_type = Column(String(30), nullable=False)  # RIDERS / PERFORMANCE
    status = Column(
        String(20), nullable=False, default="PREVIEW"
    )  # PREVIEW / COMMITTED / FAILED
    file_name = Column(String(200))
    fingerprint = Column(String(64), nullable=False)
    source_label = Column(String(80))  # FILE_IMPORT / MANUAL
    total_rows = Column(Integer, default=0)
    valid_rows = Column(Integer, default=0)
    invalid_rows = Column(Integer, default=0)
    warning_rows = Column(Integer, default=0)
    payload_json = Column(Text)  # only normalized valid rows and row-level issues
    result_json = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"))
    confirmed_by = Column(Integer, ForeignKey("users.id"))
    confirmed_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow)


class SourcePlatform(Base):
    """منصة مصدر — منصة توصيل خارجية أو نظام داخلي."""

    __tablename__ = "source_platforms"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_source_platform_tenant_code"),
        Index("ix_source_platform_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    code = Column(String(40), nullable=False)
    name_ar = Column(String(120), nullable=False)
    name_en = Column(String(120))
    description = Column(String(300))
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class PlatformOperator(Base):
    """مشغّل مُعامِل — علاقة منصة بمشغّل (شركة فرعية أو مقاول)."""

    __tablename__ = "platform_operators"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_platform_id",
            "operator_tenant_id",
            name="uq_platform_operator",
        ),
        Index("ix_platform_operator_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    source_platform_id = Column(
        Integer, ForeignKey("source_platforms.id"), nullable=False, index=True
    )
    operator_tenant_id = Column(
        Integer, ForeignKey("tenants.id"), nullable=False, index=True
    )
    relationship_type = Column(
        String(30), default="OPERATOR"
    )  # OPERATOR / FRANCHISE / PARTNER
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class DelegatedScope(Base):
    """نطاق مفوض — صلاحيات المفوض للمشغّل بدون تجاوز حدود الشركة."""

    __tablename__ = "delegated_scopes"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "platform_operator_id",
            "scope_type",
            "scope_id",
            name="uq_delegated_scope",
        ),
        Index(
            "ix_delegated_scope_tenant_operator", "tenant_id", "platform_operator_id"
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    platform_operator_id = Column(
        Integer, ForeignKey("platform_operators.id"), nullable=False, index=True
    )
    scope_type = Column(String(20), nullable=False)  # PROJECT / BRANCH / TEAM / ZONE
    scope_id = Column(Integer, nullable=False)
    permissions = Column(Text)  # JSON list of delegated permissions
    valid_from = Column(Date, nullable=False)
    valid_to = Column(Date)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class PartnerCredential(Base):
    """اعتماد الشريك — مفاتيح API ونطاقات محددة."""

    __tablename__ = "partner_credentials"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "partner_name", "key_prefix", name="uq_partner_credential"
        ),
        Index("ix_partner_credential_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    partner_name = Column(String(120), nullable=False)
    key_prefix = Column(String(8), nullable=False)
    key_hash = Column(String(128), nullable=False)
    scopes = Column(Text)  # JSON list of allowed scopes
    rate_limit_per_minute = Column(Integer, default=60)
    idempotency_window_seconds = Column(Integer, default=300)
    expires_at = Column(DateTime)
    last_rotated_at = Column(DateTime)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class WebhookEndpoint(Base):
    """نقطة نهاية الـWebhook — للاستقبال والإرسال الموقع."""

    __tablename__ = "webhook_endpoints"
    __table_args__ = (
        UniqueConstraint("tenant_id", "url", "event_type", name="uq_webhook_endpoint"),
        Index("ix_webhook_endpoint_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    url = Column(String(300), nullable=False)
    event_type = Column(String(40), nullable=False)
    secret_hash = Column(String(128))
    is_inbound = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class IntegrationAuditLog(Base):
    """سجل تدقيق التكامل — لكل مكالمات API و webhooks."""

    __tablename__ = "integration_audit_logs"
    __table_args__ = (
        Index("ix_integration_audit_tenant_timestamp", "tenant_id", "timestamp"),
        Index("ix_integration_audit_tenant_credential", "tenant_id", "credential_id"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    credential_id = Column(Integer, ForeignKey("partner_credentials.id"))
    webhook_endpoint_id = Column(Integer, ForeignKey("webhook_endpoints.id"))
    direction = Column(String(10), nullable=False)  # INBOUND / OUTBOUND
    event_type = Column(String(40))
    method = Column(String(10))
    url = Column(String(300))
    status_code = Column(Integer)
    request_body = Column(Text)
    response_body = Column(Text)
    idempotency_key = Column(String(180))
    ip_address = Column(String(45))
    timestamp = Column(DateTime, default=utcnow, nullable=False)


class MFASetting(Base):
    """إعدادات المصادقة متعددة العوامل للأدوار الحساسة."""

    __tablename__ = "mfa_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "role", name="uq_mfa_setting"),
        Index("ix_mfa_setting_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    role = Column(String(30), nullable=False)  # COMPANY_ADMIN / HR / DOU_ADMIN
    mfa_required = Column(Boolean, default=False, nullable=False)
    allowed_methods = Column(Text)  # JSON list: TOTP / SMS / EMAIL
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class SecurityAuditLog(Base):
    """سجل تدقيق أمني — لتغييرات الصلاحيات والمصادقة."""

    __tablename__ = "security_audit_logs"
    __table_args__ = (
        Index("ix_security_audit_tenant_timestamp", "tenant_id", "timestamp"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("users.id"))
    actor_role = Column(String(30))
    action = Column(
        String(60), nullable=False
    )  # LOGIN / LOGOUT / MFA_CHANGE / ROLE_CHANGE / CREDENTIAL_ROTATION
    entity_type = Column(String(30))
    entity_id = Column(Integer)
    details = Column(Text)
    ip_address = Column(String(45))
    timestamp = Column(DateTime, default=utcnow, nullable=False)


class DataResidencyRule(Base):
    """قاعدة إقامة البيانات — بعد القرار القانوني/التقني."""

    __tablename__ = "data_residency_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "data_type", name="uq_data_residency_rule"),
        Index("ix_data_residency_rule_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    data_type = Column(
        String(30), nullable=False
    )  # PERSONAL / FINANCIAL / OPERATIONAL / ALL
    required_region = Column(String(20), default="SA")  # SA / EU / US
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class SLASetting(Base):
    """إعدادات اتفاقية مستوى الخدمة."""

    __tablename__ = "sla_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "metric_name", name="uq_sla_setting"),
        Index("ix_sla_setting_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    metric_name = Column(
        String(40), nullable=False
    )  # UPTIME / API_LATENCY / SUPPORT_RESPONSE
    target_value = Column(Float, nullable=False)
    unit = Column(String(20))  # PERCENTAGE / MILLISECONDS / HOURS
    measurement_window = Column(
        String(20), default="MONTHLY"
    )  # DAILY / WEEKLY / MONTHLY
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class TenantConnection(Base):
    """اتصال المنصة بالشركة — إعدادات الاستيراد والتعيين."""

    __tablename__ = "tenant_connections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source_platform_id", name="uq_tenant_connection_platform"
        ),
        Index("ix_tenant_connection_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    source_platform_id = Column(
        Integer, ForeignKey("source_platforms.id"), nullable=False, index=True
    )
    connection_name = Column(String(120), nullable=False)
    import_frequency = Column(
        String(20), default="DAILY"
    )  # REALTIME / HOURLY / DAILY / WEEKLY
    credential_reference = Column(
        String(300)
    )  # Reference to secret storage, not the secret itself
    is_active = Column(Boolean, default=True, nullable=False)
    last_import_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ProjectContractMapping(Base):
    """تعيين المشروع/بالعقد للمنصة — ربط المشاريع بالمنصات."""

    __tablename__ = "project_contract_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_platform_id",
            "project_id",
            name="uq_project_contract_mapping",
        ),
        Index("ix_project_contract_mapping_tenant", "tenant_id"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    source_platform_id = Column(
        Integer, ForeignKey("source_platforms.id"), nullable=False, index=True
    )
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"))
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class RiderIdentityMapping(Base):
    """تعيين هوية السائق من المصدر — ربط معرفات المنصة بسائقي DOU."""

    __tablename__ = "rider_identity_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_platform_id",
            "source_rider_id",
            name="uq_rider_identity_mapping",
        ),
        Index("ix_rider_identity_mapping_tenant_courier", "tenant_id", "courier_id"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    source_platform_id = Column(
        Integer, ForeignKey("source_platforms.id"), nullable=False, index=True
    )
    source_rider_id = Column(String(80), nullable=False)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    match_method = Column(
        String(30), default="MANUAL"
    )  # MANUAL / PHONE / ID_NUMBER / AUTO
    confidence = Column(Float, default=1.0)
    status = Column(String(20), default="ACTIVE")  # ACTIVE / INACTIVE / REVIEW
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class RawImportRow(Base):
    """صف استيراد خام — سجل غير قابل للتعديل من المصدر."""

    __tablename__ = "raw_import_rows"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_platform_id",
            "source_id",
            name="uq_raw_import_row_source",
        ),
        Index("ix_raw_import_row_tenant_batch", "tenant_id", "import_batch_id"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    source_platform_id = Column(
        Integer, ForeignKey("source_platforms.id"), nullable=False, index=True
    )
    import_batch_id = Column(Integer, ForeignKey("operational_import_batches.id"))
    source_id = Column(String(80), nullable=False)
    row_data = Column(Text, nullable=False)  # JSON raw data
    checksum = Column(String(64), nullable=False)
    schema_version = Column(String(20), default="1.0")
    source_timestamp = Column(DateTime)
    import_date = Column(
        Date, default=lambda: datetime.utcnow().date()
    )  # H3 FIX: Explicit UTC date for reconciliation
    status = Column(
        String(20), default="PENDING"
    )  # PENDING / ACCEPTED / REJECTED / NORMALIZED
    validation_issues = Column(Text)  # JSON list of issues
    created_at = Column(DateTime, default=utcnow, nullable=False)


class NormalizedDeliveryFact(Base):
    """حقيقة توصيل معيارية — مستقلة عن Order القديمة."""

    __tablename__ = "normalized_delivery_facts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_platform_id",
            "source_delivery_id",
            name="uq_normalized_delivery_fact",
        ),
        Index("ix_normalized_delivery_fact_tenant_date", "tenant_id", "event_date"),
        Index("ix_normalized_delivery_fact_rider", "courier_id"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    source_platform_id = Column(
        Integer, ForeignKey("source_platforms.id"), nullable=False, index=True
    )
    source_delivery_id = Column(String(80), nullable=False)
    raw_row_id = Column(Integer, ForeignKey("raw_import_rows.id"))
    courier_id = Column(Integer, ForeignKey("couriers.id"), index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    contract_branch_id = Column(Integer, ForeignKey("contract_branches.id"))
    team_id = Column(Integer, ForeignKey("workforce_teams.id"))
    event_type = Column(String(20), nullable=False)  # COMPLETED / CANCELLED / FAILED
    event_date = Column(Date, nullable=False)
    event_timestamp = Column(DateTime)
    distance_km = Column(Float)
    revenue_amount = Column(Float)
    cost_amount = Column(Float)
    currency = Column(String(3), default="SAR")
    provenance = Column(Text)  # JSON lineage to raw row
    idempotency_key = Column(String(180), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class ReconciliationResult(Base):
    """نتيجة المطابقة — مقارنة بين إجماليات المصدر والحقائق المقبولة."""

    __tablename__ = "reconciliation_results"
    __table_args__ = (
        Index(
            "ix_reconciliation_tenant_platform_date",
            "tenant_id",
            "source_platform_id",
            "reconciliation_date",
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    source_platform_id = Column(
        Integer, ForeignKey("source_platforms.id"), nullable=False, index=True
    )
    reconciliation_date = Column(Date, nullable=False)
    source_total_count = Column(Integer, default=0)
    accepted_count = Column(Integer, default=0)
    rejected_count = Column(Integer, default=0)
    duplicate_count = Column(Integer, default=0)
    unmapped_count = Column(Integer, default=0)
    missing_count = Column(Integer, default=0)
    total_revenue_source = Column(Float, default=0)
    total_revenue_accepted = Column(Float, default=0)
    status = Column(String(20), default="PENDING")  # PENDING / COMPLETED / EXCEPTION
    exception_notes = Column(Text)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AttendanceDeductionPolicy(Base):
    """سياسة خصم حضور تابعة للشركة؛ لا تنشئ خصماً ما لم تكن مفعلة ومكتملة."""

    __tablename__ = "attendance_deduction_policies"
    __table_args__ = (
        Index(
            "ix_attendance_policy_tenant_event_active",
            "tenant_id",
            "event_type",
            "is_active",
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    event_type = Column(String(20), nullable=False)  # ABSENCE / LATE / EARLY_LEAVE
    grace_minutes = Column(Integer, default=0)
    calculation_method = Column(
        String(30), nullable=False
    )  # FIXED / PER_MINUTE / PER_HOUR / MANUAL_APPROVAL_ONLY
    amount_rate = Column(Float)  # لا تستخدم مع MANUAL_APPROVAL_ONLY
    maximum_deduction = Column(Float)
    requires_approval = Column(Boolean, default=False, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AttendanceEvent(Base):
    """حدث حضور محفوظ ومراجع، لا يخلق أكثر من تعديل راتب واحد عبر مفتاح التكرار."""

    __tablename__ = "attendance_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_attendance_event_idempotency"
        ),
        Index(
            "ix_attendance_event_tenant_status_date",
            "tenant_id",
            "status",
            "event_date",
        ),
        Index("ix_attendance_event_courier_date", "courier_id", "event_date"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    attendance_id = Column(Integer, ForeignKey("attendances.id"))
    shift_id = Column(Integer, ForeignKey("shifts.id"))
    policy_id = Column(Integer, ForeignKey("attendance_deduction_policies.id"))
    event_type = Column(String(20), nullable=False)  # ABSENCE / LATE / EARLY_LEAVE
    event_date = Column(Date, nullable=False)
    measured_minutes = Column(Integer, default=0)
    status = Column(String(30), nullable=False, default="NO_POLICY")
    deduction_amount = Column(Float, default=0)
    payroll_adjustment_id = Column(Integer, ForeignKey("payroll_adjustments.id"))
    idempotency_key = Column(String(180), nullable=False)
    note = Column(String(300))
    decided_by = Column(Integer, ForeignKey("users.id"))
    decided_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class PayrollAdjustment(Base):
    __tablename__ = "payroll_adjustments"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    month = Column(String(7), nullable=False)
    kind = Column(
        String(30), nullable=False
    )  # ABSENCE/LATE/EARLY_LEAVE/ADVANCE/DEDUCTION/VIOLATION/OVERTIME
    amount = Column(Float, default=0)
    note = Column(String(300))
    source_type = Column(
        String(40)
    )  # ATTENDANCE_EVENT / MANUAL / EMPLOYEE_REQUEST / PAYROLL_CORRECTION
    source_id = Column(Integer)
    idempotency_key = Column(String(180))
    status = Column(String(20), nullable=False, default="APPROVED")  # APPROVED / VOID
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=utcnow)


class KPIDefinition(Base):
    """تعريف KPI — نسخة محددة مع مدخلات ومخرجات."""

    __tablename__ = "kpi_definitions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "code", "version", name="uq_kpi_definition_version"
        ),
        Index("ix_kpi_definition_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    code = Column(String(40), nullable=False)
    name_ar = Column(String(120), nullable=False)
    name_en = Column(String(120))
    description = Column(String(300))
    category = Column(
        String(30), default="OPERATIONS"
    )  # OPERATIONS / FINANCIAL / WORKFORCE / COMPLIANCE
    numerator_expression = Column(Text, nullable=False)
    denominator_expression = Column(Text)
    unit = Column(String(20), default="COUNT")  # COUNT / PERCENTAGE / CURRENCY / RATIO
    source_trust_level = Column(String(20), default="MEDIUM")  # HIGH / MEDIUM / LOW
    version = Column(String(20), default="1.0")
    is_active = Column(Boolean, default=True, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class KPIResult(Base):
    """نتيجة KPI محسوبة — نسخة محددة مع القيمة."""

    __tablename__ = "kpi_results"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "kpi_definition_id",
            "scope_type",
            "scope_id",
            "period",
            name="uq_kpi_result",
        ),
        Index("ix_kpi_result_tenant_period", "tenant_id", "period"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    kpi_definition_id = Column(
        Integer, ForeignKey("kpi_definitions.id"), nullable=False, index=True
    )
    scope_type = Column(
        String(20), nullable=False
    )  # TENANT / PROJECT / BRANCH / TEAM / RIDER
    scope_id = Column(Integer, nullable=False)
    period = Column(String(7), nullable=False)  # YYYY-MM
    numerator_value = Column(Float, default=0)
    denominator_value = Column(Float, default=0)
    result_value = Column(Float, default=0)
    calculation_version = Column(String(20), default="1.0")
    freshness_at = Column(DateTime, default=utcnow, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Target(Base):
    """هدف — حسب المشروع/الفرع/الفريق/السائق."""

    __tablename__ = "targets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "scope_type",
            "scope_id",
            "target_type",
            "period",
            name="uq_target",
        ),
        Index("ix_target_tenant_period", "tenant_id", "period"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    scope_type = Column(
        String(20), nullable=False
    )  # TENANT / PROJECT / BRANCH / TEAM / RIDER
    scope_id = Column(Integer, nullable=False)
    target_type = Column(
        String(30), nullable=False
    )  # ORDERS / REVENUE / DELIVERY_TIME / RATING
    period = Column(String(7), nullable=False)  # YYYY-MM
    target_value = Column(Float, nullable=False)
    actual_value = Column(Float, default=0)
    achievement_percentage = Column(Float, default=0)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class IncentiveRule(Base):
    """قاعدة حافز — نسخة محددة مع أولوية."""

    __tablename__ = "incentive_rules"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "code", "version", name="uq_incentive_rule_version"
        ),
        Index("ix_incentive_rule_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    code = Column(String(40), nullable=False)
    name_ar = Column(String(120), nullable=False)
    name_en = Column(String(120))
    description = Column(String(300))
    rule_type = Column(String(30), default="BONUS")  # BONUS / COMMISSION / MULTIPLIER
    calculation_expression = Column(Text, nullable=False)
    priority = Column(Integer, default=0)
    precedence_policy = Column(
        String(20), default="HIGHEST_WINS"
    )  # HIGHEST_WINS / SUM / FIRST_MATCH
    version = Column(String(20), default="1.0")
    is_active = Column(Boolean, default=True, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class PayrollInputRecord(Base):
    """سجل إدخال راتب — من مصادر متعددة."""

    __tablename__ = "payroll_input_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "courier_id",
            "month",
            "source_type",
            "source_id",
            name="uq_payroll_input",
        ),
        Index("ix_payroll_input_tenant_month", "tenant_id", "month"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    month = Column(String(7), nullable=False)
    source_type = Column(
        String(30), nullable=False
    )  # ATTENDANCE / LEAVE / DELIVERY_FACT / RULE / MANUAL
    source_id = Column(Integer)
    input_type = Column(String(20), nullable=False)  # EARNING / DEDUCTION
    amount = Column(Numeric(18, 2), nullable=False)
    description = Column(String(300))
    status = Column(String(20), default="APPROVED")  # APPROVED / VOID
    reversal_of_id = Column(Integer, ForeignKey("payroll_input_records.id"))
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class DashboardDefinition(Base):
    """تعريف لوحة تحكم — مع ودجات."""

    __tablename__ = "dashboard_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_dashboard_definition"),
        Index("ix_dashboard_definition_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    code = Column(String(40), nullable=False)
    name_ar = Column(String(120), nullable=False)
    name_en = Column(String(120))
    description = Column(String(300))
    category = Column(
        String(30), default="OPERATIONS"
    )  # EXECUTIVE / OPERATIONS / WORKFORCE / FINANCIAL / COMPLIANCE
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class DashboardWidget(Base):
    """ودجت لوحة تحكم — مرتبطة بـ KPI."""

    __tablename__ = "dashboard_widgets"
    __table_args__ = (
        Index("ix_dashboard_widget_dashboard", "dashboard_definition_id"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    dashboard_definition_id = Column(
        Integer, ForeignKey("dashboard_definitions.id"), nullable=False, index=True
    )
    kpi_definition_id = Column(Integer, ForeignKey("kpi_definitions.id"))
    widget_type = Column(String(30), default="METRIC")  # METRIC / CHART / TABLE / GAUGE
    title_ar = Column(String(120), nullable=False)
    title_en = Column(String(120))
    position = Column(Integer, default=0)
    config = Column(Text)  # JSON config
    created_at = Column(DateTime, default=utcnow, nullable=False)


class EmployeeRequest(Base):
    __tablename__ = "employee_requests"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False)
    request_type = Column(
        String(30), nullable=False
    )  # ADVANCE/SHIFT_CHANGE/PROJECT_TRANSFER/MAINTENANCE/INCIDENT
    title = Column(String(160))
    details = Column(Text)
    amount = Column(Float)
    requested_project_id = Column(Integer, ForeignKey("projects.id"))
    status = Column(String(20), default="PENDING")
    reviewed_by = Column(Integer, ForeignKey("users.id"))
    review_note = Column(String(300))
    created_at = Column(DateTime, default=utcnow)
    reviewed_at = Column(DateTime)


class CourierDocumentSubmission(Base):
    """ملف مستند يرفعه السائق ويظل معلقًا لحين مراجعة الشركة."""

    __tablename__ = "courier_document_submissions"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    document_type = Column(String(40), nullable=False)
    filename = Column(String(180), nullable=False)
    mime_type = Column(String(80), nullable=False)
    file_data = Column(Text, nullable=False)
    status = Column(String(20), default="PENDING")
    review_note = Column(String(300))
    reviewed_by = Column(Integer, ForeignKey("users.id"))
    reviewed_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow)


class DocumentType(Base):
    """نوع مستند — هوية، رخصة، تأمين، إلخ."""

    __tablename__ = "document_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_document_type_tenant_code"),
        Index("ix_document_type_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    code = Column(String(40), nullable=False)
    name_ar = Column(String(120), nullable=False)
    name_en = Column(String(120))
    description_ar = Column(String(300))
    description_en = Column(String(300))
    category = Column(String(30), default="RIDER")  # RIDER / VEHICLE / GENERAL
    requires_expiry = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class DocumentRequirement(Base):
    """مصفوفة متطلبات المستندات — ماذا يُطلب من كل سائق/مركبة حسب السوق."""

    __tablename__ = "document_requirements"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "document_type_id",
            "scope",
            "market_code",
            name="uq_document_requirement",
        ),
        Index("ix_document_requirement_tenant_scope", "tenant_id", "scope"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    document_type_id = Column(
        Integer, ForeignKey("document_types.id"), nullable=False, index=True
    )
    scope = Column(String(20), nullable=False)  # RIDER / VEHICLE
    market_code = Column(String(2), default="SA")
    is_mandatory = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Document(Base):
    """مستند مرفوع — metadata only, binary stored externally."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_document_tenant_owner", "tenant_id", "owner_type", "owner_id"),
        Index("ix_document_tenant_type", "tenant_id", "document_type_id"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    document_type_id = Column(
        Integer, ForeignKey("document_types.id"), nullable=False, index=True
    )
    owner_type = Column(String(20), nullable=False)  # RIDER / VEHICLE
    owner_id = Column(Integer, nullable=False)
    filename = Column(String(180), nullable=False)
    mime_type = Column(String(80), nullable=False)
    file_size_bytes = Column(Integer, default=0)
    storage_key = Column(String(300), nullable=False)  # External storage reference
    storage_bucket = Column(String(120), default="dou-documents")
    checksum_sha256 = Column(String(64))
    expiry_date = Column(Date)
    status = Column(
        String(20), default="PENDING"
    )  # PENDING / VALID / EXPIRED / REJECTED
    scan_status = Column(String(20), default="CLEAN")  # CLEAN / SUSPICIOUS / INFECTED
    uploaded_by = Column(Integer, ForeignKey("users.id"))
    reviewed_by = Column(Integer, ForeignKey("users.id"))
    review_note = Column(String(300))
    reviewed_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class KYCStatus(Base):
    """حالة KYC للسائق — بدون ادعاء تحقق خارجي كاذب."""

    __tablename__ = "kyc_statuses"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "courier_id", name="uq_kyc_status_tenant_courier"
        ),
        Index("ix_kyc_status_tenant_status", "tenant_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    status = Column(
        String(20), default="PENDING"
    )  # PENDING / IN_REVIEW / VERIFIED / REJECTED
    missing_documents = Column(Text)  # JSON list of missing document type codes
    notes = Column(String(300))
    verified_by = Column(Integer, ForeignKey("users.id"))
    verified_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class OperationalReadinessState(Base):
    """حالة الجاهزية التشغيلية للسائق — مشتقة من أبعاد منفصلة."""

    __tablename__ = "operational_readiness_states"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "courier_id", name="uq_readiness_state_tenant_courier"
        ),
        Index("ix_readiness_state_tenant_status", "tenant_id", "overall_status"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    overall_status = Column(
        String(20), default="NOT_READY"
    )  # READY / NOT_READY / RESTRICTED
    onboarding_status = Column(
        String(20), default="NEW"
    )  # NEW / INCOMPLETE / READY_FOR_REVIEW / READY_TO_WORK / BLOCKED
    employment_status = Column(
        String(20), default="UNKNOWN"
    )  # ACTIVE / INACTIVE / SUSPENDED / UNKNOWN
    account_status = Column(
        String(20), default="UNKNOWN"
    )  # ACTIVE / INACTIVE / LOCKED / UNKNOWN
    attendance_status = Column(
        String(20), default="UNKNOWN"
    )  # COMPLIANT / NON_COMPLIANT / UNKNOWN
    shift_status = Column(
        String(20), default="UNKNOWN"
    )  # ASSIGNED / UNASSIGNED / UNKNOWN
    availability_status = Column(
        String(20), default="UNKNOWN"
    )  # AVAILABLE / ON_LEAVE / UNAVAILABLE / UNKNOWN
    leave_status = Column(
        String(20), default="UNKNOWN"
    )  # NONE / ON_LEAVE / PENDING / UNKNOWN
    documents_status = Column(
        String(20), default="UNKNOWN"
    )  # VALID / EXPIRING / MISSING / UNKNOWN
    vehicle_compliance_status = Column(
        String(20), default="UNKNOWN"
    )  # COMPLIANT / NON_COMPLIANT / NOT_APPLICABLE / UNKNOWN
    blockers = Column(Text)  # JSON list of blocker reason codes
    computed_at = Column(DateTime, default=utcnow, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ============================================================
# W10.5: OPERATOR DOMAIN
# ============================================================


class ExternalOperatorIdentity(Base):
    """Mapping of external platform operator ID to DOU operator.

    External operator IDs are NOT globally unique.
    The (source_platform_id, external_operator_id) pair is unique within a tenant.
    """

    __tablename__ = "external_operator_identities"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_platform_id",
            "external_operator_id",
            name="uq_external_operator",
        ),
        Index("ix_external_operator_tenant_identity", "tenant_id", "operator_id"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    source_platform_id = Column(
        Integer, ForeignKey("source_platforms.id"), nullable=False, index=True
    )
    external_operator_id = Column(String(80), nullable=False)
    operator_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    status = Column(String(20), default="ACTIVE")  # ACTIVE / INACTIVE / REVIEW
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class RiderAssignment(Base):
    """Effective-dated rider-to-operator assignment history.

    A rider may move between operators/projects over time.
    Historical records preserve which operator owned each period.
    """

    __tablename__ = "rider_assignments"
    __table_args__ = (
        Index("ix_rider_assignment_tenant_rider", "tenant_id", "courier_id"),
        Index("ix_rider_assignment_tenant_operator", "tenant_id", "operator_id"),
        Index("ix_rider_assignment_effective", "effective_from", "effective_to"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    supervisor_id = Column(Integer, ForeignKey("users.id"))
    project_id = Column(Integer, ForeignKey("projects.id"))
    contract_branch_id = Column(Integer, ForeignKey("contract_branches.id"))
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    status = Column(String(20), default="ACTIVE")  # ACTIVE / ENDED / TRANSFERRED
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class OperatorAgreement(Base):
    """Commercial agreement between platform and operator.

    Defines how an operator is compensated for their services.
    Terms are effective-dated to support historical reproducibility.
    """

    __tablename__ = "operator_agreements"
    __table_args__ = (
        Index("ix_operator_agreement_tenant_operator", "tenant_id", "operator_id"),
        Index("ix_operator_agreement_effective", "effective_from", "effective_to"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    compensation_model = Column(
        String(30), nullable=False
    )  # PER_COMPLETED_ORDER / FIXED_PERIOD / TARGET_BASED / HYBRID
    rate = Column(
        Numeric(18, 2), nullable=False, default=0
    )  # rate per order or fixed amount
    currency = Column(String(3), default="SAR")
    eligible_metric = Column(
        String(30), default="COMPLETED_ORDERS"
    )  # COMPLETED_ORDERS / ACCEPTED_ORDERS / DELIVERED_ORDERS
    bonus_threshold = Column(Numeric(18, 2), default=0)
    bonus_rate = Column(Numeric(18, 2), default=0)
    penalty_threshold = Column(Numeric(18, 2), default=0)
    penalty_rate = Column(Numeric(18, 2), default=0)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    status = Column(
        String(20), default="ACTIVE"
    )  # DRAFT / ACTIVE / EXPIRED / TERMINATED
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class CommercialSettlement(Base):
    """Operator commercial settlement.

    This is B2B settlement between platform and operator.
    It is NOT rider payroll - that remains in W9.
    """

    __tablename__ = "commercial_settlements"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "operator_id",
            "period_month",
            name="uq_commercial_settlement_period",
        ),
        Index("ix_commercial_settlement_tenant_status", "tenant_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    agreement_id = Column(Integer, ForeignKey("operator_agreements.id"))
    period_month = Column(String(7), nullable=False)
    eligible_orders = Column(Integer, default=0)
    base_amount = Column(Numeric(18, 2), default=0)
    bonus_amount = Column(Numeric(18, 2), default=0)
    penalty_amount = Column(Numeric(18, 2), default=0)
    manual_adjustment = Column(Numeric(18, 2), default=0)
    adjustment_reason = Column(String(300))
    net_amount = Column(Numeric(18, 2), default=0)
    currency = Column(String(3), default="SAR")
    status = Column(
        String(20), default="DRAFT"
    )  # DRAFT / CALCULATED / NEEDS_REVIEW / APPROVED / VOID
    calculation_data = Column(Text)  # JSON for traceability
    reversal_of_id = Column(Integer, ForeignKey("commercial_settlements.id"))
    created_by = Column(Integer, ForeignKey("users.id"))
    approved_by = Column(Integer, ForeignKey("users.id"))
    approved_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class CommercialSettlementLine(Base):
    """Line items for commercial settlement traceability."""

    __tablename__ = "commercial_settlement_lines"
    __table_args__ = (
        Index("ix_settlement_line_tenant_settlement", "tenant_id", "settlement_id"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    settlement_id = Column(
        Integer, ForeignKey("commercial_settlements.id"), nullable=False, index=True
    )
    line_type = Column(
        String(30), nullable=False
    )  # BASE / BONUS / PENALTY / ADJUSTMENT
    description = Column(String(300))
    quantity = Column(Integer, default=0)
    rate = Column(Numeric(18, 2), default=0)
    amount = Column(Numeric(18, 2), default=0)
    source_reference = Column(String(100))  # agreement rule, SLA reference, etc.
    created_at = Column(DateTime, default=utcnow, nullable=False)


# ============================================================
# BATCH 2+3: CAPACITY, ATTENDANCE CORRECTION, DATA HEALTH
# ============================================================


class CapacityRequirement(Base):
    """Configured required rider capacity for a scope."""

    __tablename__ = "capacity_requirements"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "scope_type",
            "scope_id",
            "shift_id",
            "effective_from",
            name="uq_capacity_requirement",
        ),
        Index("ix_capacity_tenant_scope", "tenant_id", "scope_type", "scope_id"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    scope_type = Column(
        String(20), nullable=False
    )  # BRANCH / PROJECT / OPERATOR / CITY
    scope_id = Column(Integer, nullable=False)
    shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=True, index=True)
    required_riders = Column(Integer, nullable=False, default=0)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AttendanceCorrection(Base):
    """Attendance correction request with review workflow."""

    __tablename__ = "attendance_corrections"
    __table_args__ = (Index("ix_attendance_correction_status", "tenant_id", "status"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    attendance_id = Column(
        Integer, ForeignKey("attendances.id"), nullable=False, index=True
    )
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    requested_at = Column(DateTime, default=utcnow, nullable=False)
    original_check_in = Column(DateTime, nullable=True)
    original_check_out = Column(DateTime, nullable=True)
    corrected_check_in = Column(DateTime, nullable=True)
    corrected_check_out = Column(DateTime, nullable=True)
    reason = Column(String(300), nullable=False)
    status = Column(String(20), default="PENDING")  # PENDING / APPROVED / REJECTED
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_note = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class DataHealthSnapshot(Base):
    """Data health tracking for imports and integrations."""

    __tablename__ = "data_health_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source", name="uq_data_health_source"),
        Index("ix_data_health_tenant_source", "tenant_id", "source"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    source = Column(
        String(40), nullable=False
    )  # RIDERS_IMPORT, PERFORMANCE_IMPORT, etc.
    last_successful_sync = Column(DateTime, nullable=True)
    last_failed_sync = Column(DateTime, nullable=True)
    last_sync_status = Column(String(20), default="UNKNOWN")
    rows_processed = Column(Integer, nullable=True)
    error_message = Column(String(500), nullable=True)
    freshness_seconds = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
