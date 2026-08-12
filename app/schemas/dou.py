from pydantic import BaseModel
from typing import List, Optional


class LoginIn(BaseModel):
    phone: str
    password: str
    name: Optional[str] = None
    role: Optional[str] = None       # CUSTOMER/MERCHANT/COURIER/COMPANY/DOU_OPS
    country: Optional[str] = None


class TokenOut(BaseModel):
    access_token: str
    role: str


class CompanyRegisterIn(BaseModel):
    name: str
    phone: str
    password: str
    country: Optional[str] = "SA"


class CompanyRegisterOut(BaseModel):
    access_token: str
    role: str
    company_id: int
    company_name: str
    fleet_id: int
    login_phone: str
    plan: str
    due_date: Optional[object] = None


class ShiftCreate(BaseModel):
    name: str
    zone: Optional[str] = None
    start_time: str = "09:00"
    end_time: str = "17:00"
    required_couriers: int = 0


class AttendanceIn(BaseModel):
    courier_id: int
    lat: Optional[float] = None
    lng: Optional[float] = None
    is_late: bool = False


class TaskActionIn(BaseModel):
    courier_id: int
    task_id: int


class ShipmentIn(BaseModel):
    to_city: str
    weight_kg: float = 1.0
    cod: Optional[float] = None


class PatchIn(BaseModel):
    theme: Optional[str] = None
    delivery_method: Optional[str] = None


class PatchStatusIn(BaseModel):
    status: str


class CourierCreate(BaseModel):
    name: str
    phone: str
    courier_type: str          # COMPANY | FREELANCER
    country: str               # SA | EG
    tenant_id: Optional[int] = None
    fleet_id: Optional[int] = None


class CourierOut(CourierCreate):
    id: int
    is_online: bool
    is_available: bool
    score: float
    current_load: Optional[int] = 0
    acceptance_rate: Optional[float] = 100.0
    on_time_rate: Optional[float] = 100.0
    completion_rate: Optional[float] = 100.0
    shift_active: Optional[bool] = False
    documents_valid: Optional[bool] = True
    lat: Optional[float] = None
    lng: Optional[float] = None

    class Config:
        from_attributes = True


class MerchantCreate(BaseModel):
    name: str
    country: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    district: Optional[str] = None
    city: Optional[str] = None
    slug: Optional[str] = None
    delivery_method: str = "PLATFORM"
    category: Optional[str] = None


class MerchantOut(MerchantCreate):
    id: int
    theme: str
    is_active: Optional[bool] = True

    class Config:
        from_attributes = True


class ProductCreate(BaseModel):
    name: str
    price: float
    description: Optional[str] = None
    category: Optional[str] = None
    currency: str = "SAR"


class ProductOut(ProductCreate):
    id: int
    is_available: bool

    class Config:
        from_attributes = True


class OrderItemIn(BaseModel):
    product_id: int
    quantity: int = 1


class OrderItemOut(BaseModel):
    id: int
    name: str
    quantity: int
    unit_price: float

    class Config:
        from_attributes = True


class OrderCreate(BaseModel):
    merchant_id: int
    customer_name: str
    customer_phone: str
    customer_lat: float
    customer_lng: float
    customer_address: str
    delivery_method: Optional[str] = None   # يتركه النظام ليحدده
    items: List[OrderItemIn]


class OrderOut(BaseModel):
    id: int
    merchant_id: int
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_lat: Optional[float] = None
    customer_lng: Optional[float] = None
    customer_address: Optional[str] = None
    delivery_method: str
    status: str
    subtotal: float
    delivery_fee: float
    total: float
    distance_km: float
    courier_id: Optional[int] = None
    shipping_ref: Optional[str] = None
    shipping_company: Optional[str] = None
    created_at: Optional[object] = None
    items: List[OrderItemOut] = []

    class Config:
        from_attributes = True
