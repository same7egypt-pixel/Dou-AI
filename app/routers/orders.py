from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import Merchant, Order, OrderItem, OrderStatus, Product, User, UserRole
from ..schemas.dou import OrderCreate, OrderOut, PatchStatusIn
from ..services.dispatch_engine import dispatch_order
from .auth import get_current_user

BUSINESS_ROLES = (UserRole.COMPANY, UserRole.DOU_OPS, UserRole.DOU_ADMIN)

def _business_only(user: User = Depends(get_current_user)):
    if user.role not in BUSINESS_ROLES:
        raise HTTPException(403, "Insufficient permissions")

router = APIRouter(prefix="/orders", tags=["orders"], dependencies=[Depends(_business_only)])


@router.post("", response_model=OrderOut)
def create_order(payload: OrderCreate, db: Session = Depends(get_db)):
    merchant = db.get(Merchant, payload.merchant_id)
    if not merchant:
        raise HTTPException(404, "Merchant not found")

    subtotal = 0.0
    items = []
    for line in payload.items:
        product = db.get(Product, line.product_id)
        if not product or product.merchant_id != merchant.id:
            raise HTTPException(404, f"Product {line.product_id} not found in merchant")
        subtotal += product.price * line.quantity
        items.append(OrderItem(
            product_id=product.id, name=product.name,
            quantity=line.quantity, unit_price=product.price,
        ))

    delivery_method = payload.delivery_method or merchant.delivery_method

    order = Order(
        merchant_id=merchant.id,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        customer_lat=payload.customer_lat,
        customer_lng=payload.customer_lng,
        customer_address=payload.customer_address,
        delivery_method=delivery_method,
        subtotal=subtotal,
        delivery_fee=8.0,   # رسوم توصيل افتراضية، تُحسب لاحقاً حسب المسافة
        total=subtotal + 8.0,
        status=OrderStatus.PLACED,
    )
    db.add(order)
    db.flush()
    for it in items:
        it.order_id = order.id
        db.add(it)

    db.commit()
    db.refresh(order)
    order = dispatch_order(db, order)
    db.refresh(order)
    return order


@router.get("", response_model=list[OrderOut])
def list_orders(db: Session = Depends(get_db)):
    return db.query(Order).all()


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    return order


@router.patch("/{order_id}/status", response_model=OrderOut)
def update_order_status(order_id: int, payload: PatchStatusIn, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    order.status = OrderStatus(payload.status)
    db.commit()
    db.refresh(order)
    return order
