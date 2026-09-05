"""Cash Float Service — Single Source of Truth for COD calculations.

All driver and cashier float calculations MUST use this service to ensure
identical logic across all surfaces.

Definition of Open COD Cash Float:
- Assigned to the rider (BranchDispatchOrder.rider_id == rider_id)
- Order is delivered (BranchDispatchOrder.status == OrderStatus.delivered)
- Payment method is cash (BranchDispatchOrder.payment_method == PaymentMethod.cash)
- Not yet settled by cashier (BranchDispatchOrder.cod_settled_at.is_(None))
- Optional branch filter (BranchDispatchOrder.merchant_branch_id == branch_id)
"""

from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.models.merchant import BranchDispatchOrder, OrderStatus, PaymentMethod


def open_cod_query(
    db: Session,
    rider_id: int,
    branch_id: Optional[int] = None,
) -> Query:
    """Canonical query for open COD orders."""
    q = db.query(BranchDispatchOrder).filter(
        BranchDispatchOrder.rider_id == rider_id,
        BranchDispatchOrder.status == OrderStatus.delivered,
        BranchDispatchOrder.payment_method == PaymentMethod.cash,
        BranchDispatchOrder.cod_settled_at.is_(None),
    )
    if branch_id is not None:
        q = q.filter(BranchDispatchOrder.merchant_branch_id == branch_id)
    return q


def open_cod_float(
    db: Session,
    rider_id: int,
    branch_id: Optional[int] = None,
) -> float:
    """
    Returns the sum of unsettled cod_amount for the specified rider (and optional branch).
    Single source of truth across cashier portal and driver app.
    """
    q = open_cod_query(db, rider_id=rider_id, branch_id=branch_id)
    total = q.with_entities(
        func.coalesce(func.sum(BranchDispatchOrder.cod_amount), 0)
    ).scalar()
    return float(total or 0.0)


def open_cod_orders(
    db: Session,
    rider_id: int,
    branch_id: Optional[int] = None,
    require_positive_amount: bool = False,
) -> list[BranchDispatchOrder]:
    """Returns the list of open COD orders for the specified rider."""
    q = open_cod_query(db, rider_id=rider_id, branch_id=branch_id)
    if require_positive_amount:
        q = q.filter(BranchDispatchOrder.cod_amount > 0)
    return q.order_by(BranchDispatchOrder.delivered_at.desc()).all()


def open_cod_summary(
    db: Session,
    rider_id: int,
    branch_id: Optional[int] = None,
) -> dict:
    """Returns a dict summary of open COD float for API responses."""
    orders = open_cod_orders(db, rider_id=rider_id, branch_id=branch_id)
    total = sum(Decimal(str(o.cod_amount or 0)) for o in orders)
    return {
        "unsettled_amount": float(total),
        "delivered_orders_count": len(orders),
        "orders": orders,
    }
