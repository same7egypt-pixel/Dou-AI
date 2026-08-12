from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.entities import Merchant, Product, User, UserRole
from ..schemas.dou import MerchantCreate, MerchantOut, ProductCreate, ProductOut, PatchIn
from .auth import get_current_user

BUSINESS_ROLES = (UserRole.COMPANY, UserRole.DOU_OPS, UserRole.DOU_ADMIN)

def _business_only(user: User = Depends(get_current_user)):
    if user.role not in BUSINESS_ROLES:
        raise HTTPException(403, "Insufficient permissions")

router = APIRouter(prefix="/merchants", tags=["merchants"], dependencies=[Depends(_business_only)])


@router.post("", response_model=MerchantOut)
def create_merchant(payload: MerchantCreate, db: Session = Depends(get_db)):
    merchant = Merchant(**payload.model_dump(exclude_none=True))
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    return merchant


@router.get("", response_model=list[MerchantOut])
def list_merchants(db: Session = Depends(get_db)):
    return db.query(Merchant).all()


@router.get("/{merchant_id}", response_model=MerchantOut)
def get_merchant(merchant_id: int, db: Session = Depends(get_db)):
    merchant = db.get(Merchant, merchant_id)
    if not merchant:
        raise HTTPException(404, "Merchant not found")
    return merchant


@router.post("/{merchant_id}/products", response_model=ProductOut)
def add_product(merchant_id: int, payload: ProductCreate, db: Session = Depends(get_db)):
    if not db.get(Merchant, merchant_id):
        raise HTTPException(404, "Merchant not found")
    product = Product(merchant_id=merchant_id, **payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("/{merchant_id}/products", response_model=list[ProductOut])
def list_products(merchant_id: int, db: Session = Depends(get_db)):
    return db.query(Product).filter(Product.merchant_id == merchant_id).all()


@router.patch("/{merchant_id}/theme")
def update_theme(merchant_id: int, payload: PatchIn, db: Session = Depends(get_db)):
    merchant = db.get(Merchant, merchant_id)
    if not merchant:
        raise HTTPException(404, "Merchant not found")
    merchant.theme = payload.theme
    db.commit()
    return {"ok": True, "theme": merchant.theme}


@router.patch("/{merchant_id}/delivery-method")
def update_delivery_method(merchant_id: int, payload: PatchIn, db: Session = Depends(get_db)):
    merchant = db.get(Merchant, merchant_id)
    if not merchant:
        raise HTTPException(404, "Merchant not found")
    merchant.delivery_method = payload.delivery_method
    db.commit()
    return {"ok": True, "delivery_method": merchant.delivery_method}
