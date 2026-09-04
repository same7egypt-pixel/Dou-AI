from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.entities import Courier, GeoCity, GeoCountry, Tenant, User, UserRole
from app.models.merchant import (
    BookingStatus,
    DedicatedShiftBooking,
    MerchantAccount,
    MerchantBranch,
    ShiftType,
    compute_and_set_margin,
)
from app.routers.admin import require_admin
from app.services.operating_structure import active_tenant_city_ids
from app.utils.security import generate_merchant_api_key, hash_pin

router = APIRouter(prefix="/admin/dedicated", tags=["admin_dedicated"])

_require_superadmin = require_admin


# ─── Schemas ──────────────────────────────────────────────────────────────────

class AdminFlexMetricsOut(BaseModel):
    total_bookings: int
    active_bookings: int
    total_merchants: int
    total_branches: int
    total_riders_assigned: int
    gross_monthly_revenue: float
    total_logistics_payouts: float
    dou_net_margin: float
    margin_percentage: float = 0.0


class AdminBranchOut(BaseModel):
    id: int
    branch_name: str
    city: str
    city_id: Optional[int] = None
    country_id: Optional[int] = None
    district: Optional[str]
    latitude: float
    longitude: float
    geofence_radius_meters: int
    is_active: bool
    active_bookings_count: int


class AdminMerchantOut(BaseModel):
    id: int
    trade_name: str
    vat_number: Optional[str]
    billing_contact_email: str
    billing_contact_phone: str
    payment_terms_days: int
    api_key_prefix: Optional[str]
    is_active: bool
    branches: list[AdminBranchOut]


class CreateMerchantPayload(BaseModel):
    trade_name: Optional[str] = None
    name: Optional[str] = None
    billing_contact_email: Optional[str] = None
    contact_email: Optional[str] = None
    billing_contact_phone: Optional[str] = None
    contact_phone: Optional[str] = None
    vat_number: Optional[str] = None
    commercial_reg: Optional[str] = None
    payment_terms_days: int = 30


class CreateBranchPayload(BaseModel):
    branch_name: Optional[str] = None
    name: Optional[str] = None
    city: str = "الرياض"
    city_id: Optional[int] = None
    country_id: Optional[int] = None
    district: Optional[str] = None
    latitude: float
    longitude: float
    geofence_radius_meters: int = 150
    cashier_pin: str = "2026"


class AdminBookingOut(BaseModel):
    id: int
    merchant_id: int
    merchant_name: str
    branch_id: int
    branch_name: str
    branch_city: str
    tenant_id: int
    tenant_name: str
    rider_id: Optional[int]
    rider_name: Optional[str]
    supervisor_id: Optional[int] = None
    supervisor_name: Optional[str] = None
    shift_type: str
    shift_start_time: str
    shift_end_time: str
    effective_from: date
    effective_until: Optional[date]
    monthly_fee_to_merchant: float
    monthly_payout_to_logistics: float
    dou_margin: float
    status: str


class CreateBookingPayload(BaseModel):
    merchant_branch_id: Optional[int] = None
    branch_id: Optional[int] = None
    logistics_company_tenant_id: Optional[int] = None
    tenant_id: Optional[int] = None
    rider_id: Optional[int] = None
    supervisor_id: Optional[int] = None
    shift_type: ShiftType = ShiftType.full_day_8h
    shift_start_time: Optional[str] = None
    shift_end_time: Optional[str] = None
    effective_from: Optional[date] = None
    start_date: Optional[date] = None
    effective_until: Optional[date] = None
    monthly_fee_to_merchant: float = 7000.0
    monthly_payout_to_logistics: float = 5500.0


class UpdateBookingPayload(BaseModel):
    rider_id: Optional[int] = None
    supervisor_id: Optional[int] = None
    status: Optional[BookingStatus] = None
    monthly_fee_to_merchant: Optional[float] = None
    monthly_payout_to_logistics: Optional[float] = None
    effective_until: Optional[date] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/metrics", response_model=AdminFlexMetricsOut)
def get_admin_flex_metrics(
    country: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(_require_superadmin),
):
    """
    Returns platform-wide commercial overview of dedicated restaurant shifts:
    total contracts, gross billing, logistics payouts, and DOU Net Profit.
    Supports server-side filtering by country code.
    """
    c_id = None
    if country:
        c_code = country.strip().upper()
        gc = db.query(GeoCountry).filter(func.upper(GeoCountry.code) == c_code).first()
        c_id = gc.id if gc else None

    b_query = (
        db.query(DedicatedShiftBooking)
        .join(MerchantBranch, DedicatedShiftBooking.merchant_branch_id == MerchantBranch.id)
    )
    if c_id:
        b_query = b_query.filter(MerchantBranch.country_id == c_id)

    total_bookings = b_query.count()
    active_bookings_rows = (
        b_query.filter(DedicatedShiftBooking.status == BookingStatus.active)
        .all()
    )
    active_bookings = len(active_bookings_rows)

    branch_q = db.query(MerchantBranch).filter(MerchantBranch.is_active.is_(True))
    if c_id:
        branch_q = branch_q.filter(MerchantBranch.country_id == c_id)
    total_branches = branch_q.count()

    merchant_q = db.query(MerchantAccount).filter(MerchantAccount.is_active.is_(True))
    if c_id:
        merchant_ids_in_country = (
            db.query(MerchantBranch.merchant_account_id)
            .filter(MerchantBranch.country_id == c_id)
            .distinct()
        )
        merchant_q = merchant_q.filter(MerchantAccount.id.in_(merchant_ids_in_country))
    total_merchants = merchant_q.count()

    unique_riders = {b.rider_id for b in active_bookings_rows if b.rider_id}

    gross_rev = Decimal("0.00")
    total_payout = Decimal("0.00")
    net_margin = Decimal("0.00")

    for b in active_bookings_rows:
        fee = b.monthly_fee_to_merchant or Decimal("0.00")
        payout = b.monthly_payout_to_logistics or Decimal("0.00")
        margin = b.dou_margin if b.dou_margin is not None else (fee - payout)
        gross_rev += fee
        total_payout += payout
        net_margin += margin

    pct = round(float(net_margin / gross_rev * 100), 1) if gross_rev > 0 else 0.0

    return AdminFlexMetricsOut(
        total_bookings=total_bookings,
        active_bookings=active_bookings,
        total_merchants=total_merchants,
        total_branches=total_branches,
        total_riders_assigned=len(unique_riders),
        gross_monthly_revenue=float(gross_rev),
        total_logistics_payouts=float(total_payout),
        dou_net_margin=float(net_margin),
        margin_percentage=pct,
    )


@router.get("/merchants", response_model=list[AdminMerchantOut])
def list_merchants_admin(
    country: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(_require_superadmin),
):
    """
    Lists all restaurant accounts and their operational branches, optionally filtered by country.
    """
    c_id = None
    if country:
        c_code = country.strip().upper()
        gc = db.query(GeoCountry).filter(func.upper(GeoCountry.code) == c_code).first()
        c_id = gc.id if gc else None

    accounts = (
        db.query(MerchantAccount)
        .order_by(MerchantAccount.id.desc())
        .all()
    )

    results: list[AdminMerchantOut] = []
    for a in accounts:
        branches_out: list[AdminBranchOut] = []
        for br in a.branches:
            if c_id and br.country_id != c_id:
                continue
            active_b_count = (
                db.query(DedicatedShiftBooking)
                .filter(
                    DedicatedShiftBooking.merchant_branch_id == br.id,
                    DedicatedShiftBooking.status == BookingStatus.active,
                )
                .count()
            )
            branches_out.append(
                AdminBranchOut(
                    id=br.id,
                    branch_name=br.branch_name,
                    city=br.city,
                    city_id=br.city_id,
                    country_id=br.country_id,
                    district=br.district,
                    latitude=float(br.latitude),
                    longitude=float(br.longitude),
                    geofence_radius_meters=br.geofence_radius_meters,
                    is_active=bool(br.is_active),
                    active_bookings_count=active_b_count,
                )
            )

        if c_id and not branches_out:
            continue

        results.append(
            AdminMerchantOut(
                id=a.id,
                trade_name=a.trade_name,
                vat_number=a.vat_number,
                billing_contact_email=a.billing_contact_email,
                billing_contact_phone=a.billing_contact_phone,
                payment_terms_days=a.payment_terms_days,
                api_key_prefix=a.api_key_prefix,
                is_active=bool(a.is_active),
                branches=branches_out,
            )
        )

    return results


@router.post("/merchants", status_code=status.HTTP_201_CREATED)
def create_merchant_admin(
    payload: CreateMerchantPayload,
    db: Session = Depends(get_db),
    _: User = Depends(_require_superadmin),
):
    """
    Onboards a new F&B restaurant partner and generates a live API key.
    """
    trade_name = (payload.trade_name or payload.name or "").strip()
    if not trade_name:
        raise HTTPException(status_code=400, detail="اسم المطعم مطلوب.")

    email = (payload.billing_contact_email or payload.contact_email or "billing@dou.delivery").strip()
    phone = (payload.billing_contact_phone or payload.contact_phone or "0500000000").strip()
    vat = (payload.vat_number or payload.commercial_reg or "").strip() or None

    raw_api_key, prefix, key_hash = generate_merchant_api_key()

    account = MerchantAccount(
        trade_name=trade_name,
        billing_contact_email=email,
        billing_contact_phone=phone,
        vat_number=vat,
        payment_terms_days=payload.payment_terms_days,
        api_key_prefix=prefix,
        api_key_hash=key_hash,
        is_active=True,
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    return {
        "ok": True,
        "id": account.id,
        "merchant_id": account.id,
        "trade_name": account.trade_name,
        "api_key": raw_api_key,
        "api_key_prefix": prefix,
        "api_key_raw": raw_api_key,
        "message": f"تم إنشاء حساب المطعم '{account.trade_name}' بنجاح.",
    }


@router.post("/merchants/{account_id}/branches", status_code=status.HTTP_201_CREATED)
def create_branch_admin(
    account_id: int,
    payload: CreateBranchPayload,
    db: Session = Depends(get_db),
    _: User = Depends(_require_superadmin),
):
    """
    Creates a new branch for a restaurant with Geofence coordinates and Cashier PIN.
    """
    account = db.get(MerchantAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="حساب المطعم غير موجود.")

    branch_name = (payload.branch_name or payload.name or "").strip()
    if not branch_name:
        raise HTTPException(status_code=400, detail="اسم الفرع مطلوب.")

    pin = payload.cashier_pin.strip()
    if len(pin) < 4:
        raise HTTPException(status_code=400, detail="رمز الـ PIN يجب ألا يقل عن 4 أرقام.")

    hashed_pin = hash_pin(pin)

    city_str = payload.city.strip() if payload.city else "الرياض"
    city_id = payload.city_id
    country_id = payload.country_id
    if city_id and not country_id:
        geo_city = db.get(GeoCity, city_id)
        if geo_city:
            country_id = geo_city.country_id
            city_str = geo_city.name
    elif not city_id and city_str:
        geo_city = db.query(GeoCity).filter(GeoCity.name.ilike(city_str)).first()
        if geo_city:
            city_id = geo_city.id
            country_id = geo_city.country_id

    branch = MerchantBranch(
        merchant_account_id=account.id,
        branch_name=branch_name,
        city=city_str,
        city_id=city_id,
        country_id=country_id,
        district=payload.district.strip() if payload.district else None,
        latitude=Decimal(str(payload.latitude)),
        longitude=Decimal(str(payload.longitude)),
        geofence_radius_meters=payload.geofence_radius_meters,
        cashier_access_pin=hashed_pin,
        is_active=True,
    )
    db.add(branch)
    db.commit()
    db.refresh(branch)

    return {
        "ok": True,
        "id": branch.id,
        "branch_id": branch.id,
        "branch_name": branch.branch_name,
        "cashier_pin": pin,
        "geofence_radius_meters": branch.geofence_radius_meters,
        "message": f"تم إضافة فرع '{branch.branch_name}' بنجاح.",
    }


@router.get("/bookings", response_model=list[AdminBookingOut])
def list_bookings_admin(
    status_filter: Optional[BookingStatus] = Query(None),
    merchant_id: Optional[int] = Query(None),
    tenant_id: Optional[int] = Query(None),
    country: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(_require_superadmin),
):
    """
    Lists all dedicated shift contracts with live commercial margins, optionally filtered by country.
    """
    q = (
        db.query(DedicatedShiftBooking)
        .join(MerchantBranch, DedicatedShiftBooking.merchant_branch_id == MerchantBranch.id)
    )

    if status_filter:
        q = q.filter(DedicatedShiftBooking.status == status_filter)
    if tenant_id:
        q = q.filter(DedicatedShiftBooking.logistics_company_tenant_id == tenant_id)
    if merchant_id:
        q = q.filter(MerchantBranch.merchant_account_id == merchant_id)
    if country:
        c_code = country.strip().upper()
        gc = db.query(GeoCountry).filter(func.upper(GeoCountry.code) == c_code).first()
        if gc:
            q = q.filter(MerchantBranch.country_id == gc.id)
        else:
            q = q.filter(MerchantBranch.city.ilike(f"%{c_code}%"))

    bookings = q.order_by(DedicatedShiftBooking.id.desc()).all()

    results: list[AdminBookingOut] = []
    for b in bookings:
        branch = db.get(MerchantBranch, b.merchant_branch_id)
        account = db.get(MerchantAccount, branch.merchant_account_id) if branch else None
        tenant = db.get(Tenant, b.logistics_company_tenant_id)
        rider = db.get(Courier, b.rider_id) if b.rider_id else None
        supervisor = db.get(User, b.supervisor_id) if b.supervisor_id else None

        results.append(
            AdminBookingOut(
                id=b.id,
                merchant_id=account.id if account else 0,
                merchant_name=account.trade_name if account else "مطعم",
                branch_id=b.merchant_branch_id,
                branch_name=branch.branch_name if branch else "فرع",
                branch_city=branch.city if branch else "الرياض",
                tenant_id=b.logistics_company_tenant_id,
                tenant_name=tenant.name if tenant else "شركة لوجستية",
                rider_id=b.rider_id,
                rider_name=rider.name if rider else None,
                supervisor_id=b.supervisor_id,
                supervisor_name=supervisor.name if supervisor else None,
                shift_type=b.shift_type.value,
                shift_start_time=b.shift_start_time.strftime("%H:%M"),
                shift_end_time=b.shift_end_time.strftime("%H:%M"),
                effective_from=b.effective_from,
                effective_until=b.effective_until,
                monthly_fee_to_merchant=float(b.monthly_fee_to_merchant),
                monthly_payout_to_logistics=float(b.monthly_payout_to_logistics),
                dou_margin=float(b.dou_margin),
                status=b.status.value,
            )
        )

    return results


@router.post("/bookings", status_code=status.HTTP_201_CREATED)
def create_booking_admin(
    payload: CreateBookingPayload,
    db: Session = Depends(get_db),
    _: User = Depends(_require_superadmin),
):
    """
    Creates a new Dedicated Shift contract and automatically sets DOU net margin.
    """
    target_branch_id = payload.merchant_branch_id or payload.branch_id
    if not target_branch_id:
        raise HTTPException(status_code=400, detail="معرّف الفرع مطلوب.")
    branch = db.get(MerchantBranch, target_branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="الفرع المحدد غير موجود.")

    target_tenant_id = payload.logistics_company_tenant_id or payload.tenant_id
    if not target_tenant_id:
        raise HTTPException(status_code=400, detail="معرّف الشركة اللوجستية مطلوب.")
    tenant = db.get(Tenant, target_tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="الشركة اللوجستية المحددة غير موجودة.")

    # 1. Enforce operating city validation if branch has a designated city_id
    if branch.city_id:
        active_cities = active_tenant_city_ids(db, tenant.id)
        if branch.city_id not in active_cities:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="الشركة اللوجستية لا تخدم مدينة هذا الفرع. يجب تفعيل مدينة التشغيل أولاً للشركة.",
            )

    rider = db.get(Courier, payload.rider_id) if payload.rider_id else None
    if payload.rider_id and (not rider or rider.tenant_id != tenant.id):
        raise HTTPException(
            status_code=400,
            detail="المندوب المحدد غير مسجل لدى هذه الشركة اللوجستية.",
        )
    if not rider:
        rider = (
            db.query(Courier)
            .filter(Courier.tenant_id == tenant.id, Courier.employment_status == "ACTIVE")
            .first()
        )
        if not rider:
            raise HTTPException(status_code=400, detail="لا يوجد مناديب متاحين لدى هذه الشركة اللوجستية للتسكين.")

    if payload.shift_type == ShiftType.peak_3h:
        start_str = payload.shift_start_time or "19:00"
        end_str = payload.shift_end_time or "22:00"
    else:
        start_str = payload.shift_start_time or "12:00"
        end_str = payload.shift_end_time or "20:00"

    try:
        t_start = datetime.strptime(start_str.strip(), "%H:%M").time()
        t_end = datetime.strptime(end_str.strip(), "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="صيغة وقت الوردية غير صالحة. استخدم HH:MM (مثال: 19:00).")

    fee_dec = Decimal(str(payload.monthly_fee_to_merchant))
    payout_dec = Decimal(str(payload.monthly_payout_to_logistics))
    margin_dec = fee_dec - payout_dec
    eff_from = payload.effective_from or payload.start_date or date.today()
    supervisor_id = payload.supervisor_id
    if supervisor_id:
        supervisor = db.get(User, supervisor_id)
        if not supervisor:
            raise HTTPException(status_code=404, detail="المشرف المحدد غير موجود.")
        if supervisor.tenant_id != tenant.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="المشرف المحدد لا ينتمي إلى هذه الشركة اللوجستية.",
            )
        if supervisor.role != UserRole.SUPERVISOR and supervisor.role != "SUPERVISOR":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="المستخدم المحدد ليس له صلاحية مشرف (SUPERVISOR).",
            )

    booking = DedicatedShiftBooking(
        merchant_branch_id=branch.id,
        logistics_company_tenant_id=tenant.id,
        rider_id=rider.id,
        supervisor_id=supervisor_id,
        shift_type=payload.shift_type,
        shift_start_time=t_start,
        shift_end_time=t_end,
        effective_from=eff_from,
        effective_until=payload.effective_until,
        monthly_fee_to_merchant=fee_dec,
        monthly_payout_to_logistics=payout_dec,
        dou_margin=margin_dec,
        status=BookingStatus.active,
    )
    compute_and_set_margin(booking)

    db.add(booking)
    db.commit()
    db.refresh(booking)

    return {
        "ok": True,
        "id": booking.id,
        "booking_id": booking.id,
        "monthly_fee_to_merchant": float(booking.monthly_fee_to_merchant),
        "monthly_payout_to_logistics": float(booking.monthly_payout_to_logistics),
        "dou_margin": float(booking.dou_margin),
        "dou_net_margin": float(booking.dou_margin),
        "message": "تم إنشاء عقد الوردية المخصصة بنجاح.",
    }


@router.patch("/bookings/{booking_id}")
def update_booking_admin(
    booking_id: int,
    payload: UpdateBookingPayload,
    db: Session = Depends(get_db),
    _: User = Depends(_require_superadmin),
):
    """
    Updates booking contract terms (rider, pricing, dates, or active/paused/terminated status).
    """
    booking = db.get(DedicatedShiftBooking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="عقد الوردية غير موجود.")

    if payload.rider_id is not None:
        rider = db.get(Courier, payload.rider_id)
        if not rider or rider.tenant_id != booking.logistics_company_tenant_id:
            raise HTTPException(status_code=400, detail="المندوب غير مسجل لدى نفس الشركة اللوجستية.")
        booking.rider_id = rider.id

    if payload.supervisor_id is not None:
        if payload.supervisor_id == 0:
            booking.supervisor_id = None
        else:
            supervisor = db.get(User, payload.supervisor_id)
            if not supervisor:
                raise HTTPException(status_code=404, detail="المشرف المحدد غير موجود.")
            if supervisor.tenant_id != booking.logistics_company_tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="المشرف المحدد لا ينتمي إلى هذه الشركة اللوجستية.",
                )
            if supervisor.role != UserRole.SUPERVISOR and supervisor.role != "SUPERVISOR":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="المستخدم المحدد ليس له صلاحية مشرف (SUPERVISOR).",
                )
            booking.supervisor_id = supervisor.id

    if payload.status is not None:
        booking.status = payload.status
        if payload.status == BookingStatus.terminated:
            booking.terminated_at = datetime.now(timezone.utc)

    if payload.effective_until is not None:
        booking.effective_until = payload.effective_until

    if payload.monthly_fee_to_merchant is not None:
        booking.monthly_fee_to_merchant = Decimal(str(payload.monthly_fee_to_merchant))
    if payload.monthly_payout_to_logistics is not None:
        booking.monthly_payout_to_logistics = Decimal(str(payload.monthly_payout_to_logistics))

    compute_and_set_margin(booking)
    db.commit()
    db.refresh(booking)

    return {
        "ok": True,
        "message": "تم تحديث بيانات العقد بنجاح.",
        "booking_id": booking.id,
        "status": booking.status.value,
        "monthly_fee_to_merchant": float(booking.monthly_fee_to_merchant),
        "monthly_payout_to_logistics": float(booking.monthly_payout_to_logistics),
        "dou_margin": float(booking.dou_margin),
        "dou_net_margin": float(booking.dou_margin),
    }
