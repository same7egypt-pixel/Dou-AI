from fastapi import APIRouter, Depends, HTTPException, Header
from typing import Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import ADMIN_KEY
from ..models.entities import Channel, Courier, Merchant, Staff, CourierType, Country


async def require_admin(x_admin_key: str = Header(default="", alias="X-Admin-Key")):
    """بوابة لوحة التحكم: تتحقق من المفتاح الإداري في الـ header."""
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Access denied")
    return True


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

gate_router = APIRouter(prefix="/admin", tags=["admin"])


class NameOnly(BaseModel):
    name: str


class GateIn(BaseModel):
    username: str
    password: str


@gate_router.post("/gate")
def admin_gate(payload: GateIn):
    """بوابة لوحة التحكم: تتأكد من بيانات صاحب المنصة وتعطي مفتاح الجلسة."""
    if payload.username == "Sameh" and payload.password == ADMIN_KEY:
        return {"ok": True, "key": ADMIN_KEY}
    raise HTTPException(401, "بيانات دخول غير صحيحة")


# ---------- Merchants ----------
class MerchantIn(BaseModel):
    name: str
    country: str = "SA"
    delivery_method: str = "PLATFORM"
    city: Optional[str] = None
    district: Optional[str] = None
    category: Optional[str] = None


class MerchantPatch(BaseModel):
    active: Optional[bool] = None
    delivery_method: Optional[str] = None
    category: Optional[str] = None


@router.get("/merchants")
def list_merchants(db: Session = Depends(get_db)):
    rows = []
    for m in db.query(Merchant).all():
        rows.append({
            "id": m.id, "name": m.name, "country": m.country.value if hasattr(m.country, "value") else m.country,
            "city": m.city, "district": m.district, "category": m.category or "",
            "delivery_method": m.delivery_method.value if hasattr(m.delivery_method, "value") else m.delivery_method,
            "is_active": True, "theme": m.theme, "slug": m.slug,
        })
    return rows


@router.post("/merchants")
def add_merchant(payload: MerchantIn, db: Session = Depends(get_db)):
    m = Merchant(
        name=payload.name,
        country=Country(payload.country) if payload.country in ("SA", "EG") else Country.SA,
        city=payload.city or "", district=payload.district or "",
        slug=f"store-{abs(hash(payload.name)) % 99999}", category=payload.category or "",
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return {"id": m.id, "name": m.name, "country": m.country.value, "city": m.city,
            "district": m.district, "category": m.category, "is_active": True}


@router.patch("/merchants/{mid}")
def patch_merchant(mid: int, payload: MerchantPatch, db: Session = Depends(get_db)):
    m = db.get(Merchant, mid)
    if not m:
        raise HTTPException(404, "Merchant not found")
    if payload.active is not None:
        m.is_active = payload.active
    if payload.delivery_method:
        m.delivery_method = payload.delivery_method
    if payload.category:
        m.category = payload.category
    db.commit()
    return {"ok": True, "id": m.id, "is_active": m.is_active}


@router.delete("/merchants/{mid}")
def delete_merchant(mid: int, db: Session = Depends(get_db)):
    m = db.get(Merchant, mid)
    if not m:
        raise HTTPException(404, "Merchant not found")
    db.delete(m)
    db.commit()
    return {"ok": True}


# ---------- Channels ----------
class ChannelIn(BaseModel):
    name: str
    icon: str = "🔌"
    type: str = "PARTNER"
    commission: float = 0.0


class ChannelPatch(BaseModel):
    active: Optional[bool] = None
    commission: Optional[float] = None


@router.get("/channels")
def list_channels(db: Session = Depends(get_db)):
    return [
        {"id": c.id, "name": c.name, "icon": c.icon, "type": c.type,
         "commission": c.commission, "is_active": c.is_active, "orders_share": c.orders_share}
        for c in db.query(Channel).all()
    ]


@router.post("/channels")
def add_channel(payload: ChannelIn, db: Session = Depends(get_db)):
    c = Channel(name=payload.name, icon=payload.icon, type=payload.type, commission=payload.commission)
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name, "icon": c.icon, "type": c.type,
            "commission": c.commission, "is_active": True, "orders_share": 0}


@router.patch("/channels/{cid}")
def patch_channel(cid: int, payload: ChannelPatch, db: Session = Depends(get_db)):
    c = db.get(Channel, cid)
    if not c:
        raise HTTPException(404, "Channel not found")
    if payload.active is not None:
        c.is_active = payload.active
        c.status = "active" if payload.active else "inactive"
    if payload.commission is not None:
        c.commission = payload.commission
    db.commit()
    return {"id": c.id, "is_active": c.is_active, "commission": c.commission}


@router.delete("/channels/{cid}")
def delete_channel(cid: int, db: Session = Depends(get_db)):
    c = db.get(Channel, cid)
    if not c:
        raise HTTPException(404, "Channel not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


# ---------- Companies ----------
class CompanyIn(BaseModel):
    name: str
    code: str
    country: str = "SA"


class CompanyPatch(BaseModel):
    active: Optional[bool] = None


@router.get("/companies")
def list_companies(db: Session = Depends(get_db)):
    from ..models.entities import ShippingCompany
    return [
        {"id": c.id, "name": c.name, "code": c.code,
         "country": c.country.value if hasattr(c.country, "value") else c.country,
         "is_active": c.is_active}
        for c in db.query(ShippingCompany).all()
    ]


@router.post("/companies")
def add_company(payload: CompanyIn, db: Session = Depends(get_db)):
    from ..models.entities import ShippingCompany
    c = ShippingCompany(name=payload.name, code=payload.code.upper(),
                        country=Country(payload.country) if payload.country in ("SA", "EG") else Country.SA)
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name, "code": c.code, "country": c.country.value, "is_active": True}


@router.patch("/companies/{cid}")
def patch_company(cid: int, payload: CompanyPatch, db: Session = Depends(get_db)):
    from ..models.entities import ShippingCompany
    c = db.get(ShippingCompany, cid)
    if not c:
        raise HTTPException(404, "Company not found")
    if payload.active is not None:
        c.is_active = payload.active
    db.commit()
    return {"ok": True, "id": c.id, "is_active": c.is_active}


@router.delete("/companies/{cid}")
def delete_company(cid: int, db: Session = Depends(get_db)):
    from ..models.entities import ShippingCompany
    c = db.get(ShippingCompany, cid)
    if not c:
        raise HTTPException(404, "Company not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


# ---------- Couriers ----------
class CourierIn(BaseModel):
    name: str
    phone: str
    courier_type: str = "FREELANCER"
    country: str = "SA"


class CourierPatch(BaseModel):
    active: Optional[bool] = None


@router.get("/couriers")
def list_couriers(db: Session = Depends(get_db)):
    return [
        {"id": c.id, "name": c.name, "phone": c.phone,
         "courier_type": c.courier_type.value if hasattr(c.courier_type, "value") else c.courier_type,
         "country": c.country.value if hasattr(c.country, "value") else c.country,
         "is_active": True, "is_online": c.is_online, "score": c.score}
        for c in db.query(Courier).all()
    ]


@router.post("/couriers")
def add_courier(payload: CourierIn, db: Session = Depends(get_db)):
    c = Courier(
        name=payload.name, phone=payload.phone,
        courier_type=CourierType(payload.courier_type) if payload.courier_type in ("COMPANY", "FREELANCER") else CourierType.FREELANCER,
        country=Country(payload.country) if payload.country in ("SA", "EG") else Country.SA,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name, "phone": c.phone,
            "courier_type": c.courier_type.value, "country": c.country.value, "is_active": True}


@router.patch("/couriers/{cid}")
def patch_courier(cid: int, payload: CourierPatch, db: Session = Depends(get_db)):
    c = db.get(Courier, cid)
    if not c:
        raise HTTPException(404, "Courier not found")
    if payload.active is not None:
        c.is_available = payload.active
    db.commit()
    return {"ok": True, "id": c.id}


@router.delete("/couriers/{cid}")
def delete_courier(cid: int, db: Session = Depends(get_db)):
    c = db.get(Courier, cid)
    if not c:
        raise HTTPException(404, "Courier not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


# ---------- Staff ----------
class StaffIn(BaseModel):
    name: str
    email: str = ""
    role: str = ""
    access: str = "limited"


class StaffPatch(BaseModel):
    active: Optional[bool] = None
    role: Optional[str] = None


@router.get("/staff")
def list_staff(db: Session = Depends(get_db)):
    return [
        {"id": s.id, "name": s.name, "email": s.email, "role": s.role,
         "access": s.access, "region": s.region or "", "status": s.status}
        for s in db.query(Staff).all()
    ]


@router.post("/staff")
def add_staff(payload: StaffIn, db: Session = Depends(get_db)):
    s = Staff(name=payload.name, email=payload.email, role=payload.role, access=payload.access)
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "name": s.name, "email": s.email, "role": s.role,
            "access": s.access, "status": "active"}


@router.patch("/staff/{sid}")
def patch_staff(sid: int, payload: StaffPatch, db: Session = Depends(get_db)):
    s = db.get(Staff, sid)
    if not s:
        raise HTTPException(404, "Staff not found")
    if payload.active is not None:
        s.status = "active" if payload.active else "inactive"
    if payload.role:
        s.role = payload.role
    db.commit()
    return {"ok": True, "id": s.id, "status": s.status}


@router.delete("/staff/{sid}")
def delete_staff(sid: int, db: Session = Depends(get_db)):
    s = db.get(Staff, sid)
    if not s:
        raise HTTPException(404, "Staff not found")
    db.delete(s)
    db.commit()
    return {"ok": True}