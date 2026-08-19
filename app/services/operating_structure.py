"""Operational-structure helpers for Phase 1.

The service keeps GeoCity as the canonical city catalog and TenantOperatingCity as the
company-specific activation layer. Legacy city strings are retained as display data and
only backfilled when an exact normalized match is unambiguous.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.entities import (
    ContractBranch,
    Courier,
    GeoCity,
    GeoCountry,
    Tenant,
    TenantOperatingCity,
    User,
    UserRole,
)


def normalize_city_name(value: Optional[str]) -> str:
    return " ".join((value or "").strip().casefold().split())


def _country_name(code: str) -> str:
    return {"SA": "Saudi Arabia", "EG": "Egypt"}.get((code or "").upper(), (code or "Unknown").upper())


def ensure_geo_country(db: Session, tenant: Tenant) -> GeoCountry:
    code = (tenant.market_code or getattr(tenant.country, "value", tenant.country) or "SA").upper()
    country = db.query(GeoCountry).filter(func.upper(GeoCountry.code) == code).first()
    if country:
        return country
    country = GeoCountry(name=_country_name(code), code=code, active=True)
    db.add(country)
    db.flush()
    return country


def find_or_create_city(db: Session, tenant: Tenant, name: str) -> GeoCity:
    cleaned = " ".join((name or "").strip().split())
    if not cleaned:
        raise ValueError("اسم المدينة مطلوب")
    country = ensure_geo_country(db, tenant)
    norm = normalize_city_name(cleaned)
    matches = db.query(GeoCity).filter(
        GeoCity.country_id == country.id,
        func.lower(GeoCity.name) == norm,
    ).all()
    if len(matches) > 1:
        raise ValueError("توجد مدن مرجعية مكررة بالاسم نفسه؛ راجع إدارة DOU")
    if matches:
        return matches[0]
    city = GeoCity(country_id=country.id, name=cleaned, active=True)
    db.add(city)
    db.flush()
    return city


def ensure_tenant_operating_city(db: Session, tenant: Tenant, city: GeoCity, active: bool = True) -> TenantOperatingCity:
    record = db.query(TenantOperatingCity).filter(
        TenantOperatingCity.tenant_id == tenant.id,
        TenantOperatingCity.geo_city_id == city.id,
    ).first()
    if record:
        if active and not record.is_active:
            record.is_active = True
        return record
    record = TenantOperatingCity(tenant_id=tenant.id, geo_city_id=city.id, is_active=active)
    db.add(record)
    db.flush()
    return record


def active_tenant_city_ids(db: Session, tenant_id: int) -> set[int]:
    return {
        row[0]
        for row in db.query(TenantOperatingCity.geo_city_id).filter(
            TenantOperatingCity.tenant_id == tenant_id,
            TenantOperatingCity.is_active.is_(True),
        ).all()
    }


def resolve_active_tenant_city_by_name(db: Session, tenant_id: int, value: str) -> GeoCity:
    normalized = normalize_city_name(value)
    if not normalized:
        raise ValueError("اختر مدينة تشغيل مفعلة")
    links = db.query(TenantOperatingCity).filter(
        TenantOperatingCity.tenant_id == tenant_id,
        TenantOperatingCity.is_active.is_(True),
    ).all()
    matches = []
    for link in links:
        city = db.get(GeoCity, link.geo_city_id)
        if city and city.active and normalized in {normalize_city_name(city.name), normalize_city_name(link.display_name)}:
            matches.append(city)
    if len(matches) != 1:
        raise ValueError("المدينة غير مفعلة لهذه الشركة؛ فعّلها من مدن التشغيل أولاً")
    return matches[0]


def require_active_tenant_city(db: Session, tenant_id: int, city_id: int) -> GeoCity:
    city = db.get(GeoCity, int(city_id))
    if not city or not city.active:
        raise ValueError("المدينة غير موجودة أو غير مفعلة")
    enabled = db.query(TenantOperatingCity).filter(
        TenantOperatingCity.tenant_id == tenant_id,
        TenantOperatingCity.geo_city_id == city.id,
        TenantOperatingCity.is_active.is_(True),
    ).first()
    if not enabled:
        raise ValueError("المدينة غير مفعلة لهذه الشركة")
    return city


def branch_city(db: Session, branch: ContractBranch) -> Optional[GeoCity]:
    return db.get(GeoCity, branch.city_id) if branch and branch.city_id else None


def validate_supervisor_for_branch(db: Session, tenant_id: int, supervisor_id: Optional[int], branch: ContractBranch) -> Optional[User]:
    if not supervisor_id:
        return None
    supervisor = db.get(User, int(supervisor_id))
    if not supervisor or supervisor.tenant_id != tenant_id or supervisor.role != UserRole.SUPERVISOR or not supervisor.is_active:
        raise ValueError("المشرف غير صالح لهذه الشركة")
    if branch.city_id:
        scope = db.query(ContractBranch).filter(
            ContractBranch.tenant_id == tenant_id,
            ContractBranch.supervisor_id == supervisor.id,
            ContractBranch.city_id == branch.city_id,
            ContractBranch.is_active.is_(True),
        ).first()
        # يسمح بإسناد المشرف عند إنشاء أو تعديل الفرع نفسه؛ أما تعيين مندوب لفرع قائم فيتطلب النطاق نفسه.
        if scope is None and branch.supervisor_id != supervisor.id:
            raise ValueError("المشرف غير مرتبط بنطاق المدينة المختار")
    return supervisor


def backfill_operating_cities(db: Session) -> dict:
    """Backfill only exact normalized legacy strings; never merges ambiguous names or deletes data."""
    stats = defaultdict(int)
    tenants = db.query(Tenant).all()
    for tenant in tenants:
        branches = db.query(ContractBranch).filter(ContractBranch.tenant_id == tenant.id).all()
        for branch in branches:
            if branch.city_id:
                city = db.get(GeoCity, branch.city_id)
                if city:
                    ensure_tenant_operating_city(db, tenant, city)
                continue
            if not normalize_city_name(branch.city):
                stats["unresolved_branches"] += 1
                continue
            try:
                city = find_or_create_city(db, tenant, branch.city)
            except ValueError:
                stats["unresolved_branches"] += 1
                continue
            ensure_tenant_operating_city(db, tenant, city)
            branch.city_id = city.id
            stats["branches_backfilled"] += 1
        couriers = db.query(Courier).filter(Courier.tenant_id == tenant.id).all()
        for courier in couriers:
            if courier.city_id:
                continue
            branch = db.get(ContractBranch, courier.contract_branch_id) if courier.contract_branch_id else None
            if branch and branch.city_id:
                courier.city_id = branch.city_id
                if not courier.work_city:
                    courier.work_city = branch.city
                stats["couriers_backfilled_from_branch"] += 1
                continue
            if not normalize_city_name(courier.work_city):
                stats["unresolved_couriers"] += 1
                continue
            try:
                city = find_or_create_city(db, tenant, courier.work_city)
            except ValueError:
                stats["unresolved_couriers"] += 1
                continue
            ensure_tenant_operating_city(db, tenant, city)
            courier.city_id = city.id
            stats["couriers_backfilled_from_text"] += 1
    db.commit()
    return dict(stats)


def operating_city_counts(db: Session, tenant_id: int, city_id: int) -> dict:
    return {
        "branches": db.query(ContractBranch).filter(ContractBranch.tenant_id == tenant_id, ContractBranch.city_id == city_id).count(),
        "riders": db.query(Courier).filter(Courier.tenant_id == tenant_id, Courier.city_id == city_id).count(),
        "supervisors": db.query(User).filter(User.tenant_id == tenant_id, User.role == UserRole.SUPERVISOR).filter(
            User.id.in_(db.query(ContractBranch.supervisor_id).filter(ContractBranch.tenant_id == tenant_id, ContractBranch.city_id == city_id, ContractBranch.supervisor_id.isnot(None)))
        ).count(),
        "contracts": db.query(ContractBranch.contract_id).filter(ContractBranch.tenant_id == tenant_id, ContractBranch.city_id == city_id).distinct().count(),
    }
