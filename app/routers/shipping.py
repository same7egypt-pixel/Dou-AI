from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import (
    Merchant, Order, ShippingCompany, ShippingLabel, User, UserRole,
)
from ..schemas.dou import ShipmentIn
from ..services.shipping import ShipmentRequest, gateway
from .auth import get_current_user

BUSINESS_ROLES = (UserRole.COMPANY, UserRole.DOU_OPS, UserRole.DOU_ADMIN)

def _business_only(user: User = Depends(get_current_user)):
    if user.role not in BUSINESS_ROLES:
        raise HTTPException(403, "Insufficient permissions")

router = APIRouter(prefix="/shipping", tags=["shipping"], dependencies=[Depends(_business_only)])


@router.get("/companies")
def list_companies(db: Session = Depends(get_db)):
    return db.query(ShippingCompany).all()


@router.post("/companies")
def add_company(payload: dict, db: Session = Depends(get_db)):
    company = ShippingCompany(**payload)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.post("/create/{order_id}")
def create_shipment(order_id: int, payload: ShipmentIn, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    merchant = db.get(Merchant, order.merchant_id)

    # اختيار شركة شحن نشطة في بلد الطلب
    company = db.query(ShippingCompany).filter(
        ShippingCompany.country == merchant.country,
        ShippingCompany.is_active.is_(True),
    ).first()
    if not company:
        raise HTTPException(400, "No active shipping company in this country")

    req = ShipmentRequest(
        order_id=order.id,
        company_code=company.code,
        from_address=merchant.district or merchant.city or "",
        to_address=order.customer_address,
        from_city=merchant.city or "",
        to_city=payload.to_city or "",
        weight_kg=payload.weight_kg,
        cash_on_delivery=payload.cod or 0.0,
        phone=order.customer_phone,
    )
    result = gateway.create_shipment(req)

    label = ShippingLabel(
        order_id=order.id,
        company_id=company.id,
        tracking_number=result.tracking_number,
        status="CREATED",
    )
    db.add(label)
    order.shipping_ref = result.tracking_number
    order.shipping_company = company.name
    db.commit()

    return {
        "order_id": order.id,
        "company": company.name,
        "tracking_number": result.tracking_number,
        "estimated_delivery_days": result.estimated_delivery_days,
        "label_url": result.label_url,
    }
