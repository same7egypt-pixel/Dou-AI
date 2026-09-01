"""طبقة تكامل شركات الشحن (سمسا SMSA / بوسطه Bosta / أرامكس Aramex).

في الـ MVP: ممرّ Mock مع واجهة موحّدة — لاحقاً يُستبدل كل adapter بنداء API حقيقي.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ShipmentRequest:
    order_id: int
    company_code: str  # SMSA / BOSTA / ARAMEX
    from_address: str
    to_address: str
    from_city: str
    to_city: str
    weight_kg: float = 1.0
    cash_on_delivery: float = 0.0
    phone: Optional[str] = None


@dataclass
class ShipmentResult:
    company_code: str
    tracking_number: str
    label_url: Optional[str] = None
    estimated_delivery_days: int = 3


class ShippingGateway:
    """واجهة موحّدة — تستبدل بـ Adapters حقيقية حسب الشركة."""

    def create_shipment(self, req: ShipmentRequest) -> ShipmentResult:
        # --- SMSA (السعودية) ---
        if req.company_code == "SMSA":
            return self._smsa(req)
        # --- Bosta (مصر) ---
        if req.company_code == "BOSTA":
            return self._bosta(req)
        # --- Aramex (السعودية/مصر) ---
        if req.company_code == "ARAMEX":
            return self._aramex(req)
        raise ValueError(f"Unknown shipping company: {req.company_code}")

    def _smsa(self, req: ShipmentRequest) -> ShipmentResult:
        return ShipmentResult(
            company_code="SMSA",
            tracking_number=f"SMSA-{req.order_id}-{req.to_city}",
            label_url="https://demo.smsaexpress.com/label/mock",
            estimated_delivery_days=2,
        )

    def _bosta(self, req: ShipmentRequest) -> ShipmentResult:
        return ShipmentResult(
            company_code="BOSTA",
            tracking_number=f"BST-{req.order_id}-{req.to_city}",
            estimated_delivery_days=3,
        )

    def _aramex(self, req: ShipmentRequest) -> ShipmentResult:
        return ShipmentResult(
            company_code="ARAMEX",
            tracking_number=f"AX-{req.order_id}-{req.to_city}",
            estimated_delivery_days=2,
        )


gateway = ShippingGateway()
