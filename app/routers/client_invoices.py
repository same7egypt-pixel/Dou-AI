"""B2B Client Invoicing & Contract Profitability Margin Router.

Handles dedicated rider invoicing for commercial clients (e.g. Restaurants, Dark Stores),
calculates billed amounts vs courier payroll cost, and computes gross profit margins.
"""

from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import entities as ent
from .auth import get_current_user


router = APIRouter(prefix="/client-invoices", tags=["client-invoices"])


class GenerateInvoicePayload(BaseModel):
    contract_id: int
    billing_month: str = Field(
        default_factory=lambda: date.today().strftime("%Y-%m")
    )  # e.g. "2026-08"
    notes: Optional[str] = None
    due_days: int = Field(default=15, ge=0, le=365)


class UpdateInvoiceStatusPayload(BaseModel):
    status: str  # DRAFT / ISSUED / PAID / CANCELLED
    notes: Optional[str] = None


READ_ROLES = {
    ent.UserRole.COMPANY,
    ent.UserRole.COMPANY_ADMIN,
    ent.UserRole.OPERATIONS,
    ent.UserRole.ACCOUNTANT,
    ent.UserRole.VIEWER,
    ent.UserRole.DOU_ADMIN,
    ent.UserRole.DOU_OPS,
}
FINANCE_MANAGE_ROLES = {
    ent.UserRole.COMPANY,
    ent.UserRole.COMPANY_ADMIN,
    ent.UserRole.ACCOUNTANT,
    ent.UserRole.DOU_ADMIN,
}


def _tenant_id(user: ent.User, manage: bool = False) -> int:
    allowed = FINANCE_MANAGE_ROLES if manage else READ_ROLES
    if user.role not in allowed or not user.tenant_id:
        raise HTTPException(
            403,
            "ليس لديك صلاحية لإدارة فواتير العملاء"
            if manage
            else "ليس لديك صلاحية لعرض الفواتير",
        )
    return user.tenant_id


@router.get("")
def list_client_invoices(
    contract_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all B2B commercial client invoices for the current tenant."""
    tenant_id = _tenant_id(user, manage=False)
    query = db.query(ent.ClientInvoice).filter(ent.ClientInvoice.tenant_id == tenant_id)
    if contract_id:
        query = query.filter(ent.ClientInvoice.contract_id == contract_id)
    if status:
        query = query.filter(ent.ClientInvoice.status == status)

    invoices = query.order_by(ent.ClientInvoice.id.desc()).all()

    return [
        {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "contract_id": inv.contract_id,
            "client_name": inv.client_name,
            "billing_month": inv.billing_month,
            "total_riders_supplied": inv.total_riders_supplied,
            "total_amount_billed": inv.total_amount_billed,
            "total_courier_payroll_cost": inv.total_courier_payroll_cost,
            "net_gross_profit": inv.net_gross_profit,
            "profit_margin_pct": round(inv.profit_margin_pct or 0.0, 1),
            "status": inv.status,
            "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
            "due_date": inv.due_date.isoformat() if inv.due_date else None,
            "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
            "notes": inv.notes,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
        }
        for inv in invoices
    ]


@router.post("/generate")
def generate_client_invoice(
    payload: GenerateInvoicePayload,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a B2B monthly commercial invoice for a client contract with branch breakdowns."""
    tenant_id = _tenant_id(user, manage=True)
    contract = (
        db.query(ent.Contract)
        .filter(
            ent.Contract.id == payload.contract_id, ent.Contract.tenant_id == tenant_id
        )
        .first()
    )

    if not contract:
        raise HTTPException(404, "العقد التجاري غير موجود")

    # Prevent duplicate invoices for the same contract and billing month
    existing_inv = (
        db.query(ent.ClientInvoice)
        .filter(
            ent.ClientInvoice.tenant_id == tenant_id,
            ent.ClientInvoice.contract_id == payload.contract_id,
            ent.ClientInvoice.billing_month == payload.billing_month,
            ent.ClientInvoice.status != "CANCELLED",
        )
        .first()
    )
    if existing_inv:
        raise HTTPException(
            409,
            f"توجد فاتورة نشطة بالفعل لهذا العقد عن شهر {payload.billing_month} برقم {existing_inv.invoice_number}",
        )

    branches = (
        db.query(ent.ContractBranch)
        .filter(
            ent.ContractBranch.contract_id == contract.id,
            ent.ContractBranch.tenant_id == tenant_id,
            ent.ContractBranch.is_active,
        )
        .all()
    )

    if not branches:
        raise HTTPException(400, "لا توجد فروع تشغيلية نشطة مرتبطة بهذا العقد")

    # Generate sequential invoice number
    count = (
        db.query(ent.ClientInvoice)
        .filter(ent.ClientInvoice.tenant_id == tenant_id)
        .count()
        + 1
    )
    inv_number = (
        f"INV-{payload.billing_month.replace('-', '')}-{contract.id:02d}-{count:03d}"
    )

    total_riders = 0
    total_billed = 0.0
    total_cost = 0.0
    invoice_items = []

    for branch in branches:
        # Find couriers assigned to this branch
        branch_couriers = (
            db.query(ent.Courier)
            .filter(
                ent.Courier.tenant_id == tenant_id,
                ent.Courier.contract_branch_id == branch.id,
                ent.Courier.employment_status == "ACTIVE",
            )
            .all()
        )

        riders_count = len(branch_couriers) or (branch.dedicated_riders_target or 1)
        total_riders += riders_count

        branch_monthly_rate = branch.monthly_rate_per_rider or (
            contract.base_salary or 4500.0
        )
        line_billed_amount = riders_count * branch_monthly_rate
        total_billed += line_billed_amount

        # Calculate courier payroll cost
        line_cost = 0.0
        for c in branch_couriers:
            c_cost = c.base_salary or 3000.0
            line_cost += c_cost

        if not branch_couriers:
            line_cost = riders_count * (contract.base_salary or 3000.0)

        total_cost += line_cost

        item = ent.ClientInvoiceItem(
            tenant_id=tenant_id,
            contract_branch_id=branch.id,
            branch_name=branch.branch_name or branch.city or f"فرع {branch.id}",
            days_worked=30,
            monthly_rate=branch_monthly_rate,
            total_line_amount=line_billed_amount,
            courier_cost_share=line_cost,
        )
        invoice_items.append(item)

    net_profit = total_billed - total_cost
    profit_margin_pct = (net_profit / total_billed * 100.0) if total_billed > 0 else 0.0

    from datetime import timedelta

    due_date = date.today() + timedelta(days=payload.due_days)

    client_name = contract.client_name or contract.name

    inv = ent.ClientInvoice(
        tenant_id=tenant_id,
        contract_id=contract.id,
        invoice_number=inv_number,
        billing_month=payload.billing_month,
        client_name=client_name,
        total_riders_supplied=total_riders,
        total_shifts_served=total_riders * 30,
        total_amount_billed=total_billed,
        total_courier_payroll_cost=total_cost,
        net_gross_profit=net_profit,
        profit_margin_pct=profit_margin_pct,
        status="ISSUED",
        issue_date=date.today(),
        due_date=due_date,
        notes=payload.notes
        or f"مطالبة شهر {payload.billing_month} عن {len(branches)} فروع",
    )
    db.add(inv)
    db.flush()

    for item in invoice_items:
        item.invoice_id = inv.id
        db.add(item)

    db.commit()

    return {
        "status": "success",
        "invoice": {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "client_name": inv.client_name,
            "billing_month": inv.billing_month,
            "total_riders_supplied": inv.total_riders_supplied,
            "total_amount_billed": inv.total_amount_billed,
            "total_courier_payroll_cost": inv.total_courier_payroll_cost,
            "net_gross_profit": inv.net_gross_profit,
            "profit_margin_pct": round(inv.profit_margin_pct, 1),
            "status": inv.status,
            "due_date": inv.due_date.isoformat(),
            "items_count": len(invoice_items),
        },
    }


@router.get("/{invoice_id}")
def get_client_invoice_details(
    invoice_id: int,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get full details of a B2B client invoice with line items."""
    tenant_id = _tenant_id(user, manage=False)
    inv = (
        db.query(ent.ClientInvoice)
        .filter(
            ent.ClientInvoice.id == invoice_id, ent.ClientInvoice.tenant_id == tenant_id
        )
        .first()
    )

    if not inv:
        raise HTTPException(404, "الفاتورة غير موجودة")

    items = (
        db.query(ent.ClientInvoiceItem)
        .filter(
            ent.ClientInvoiceItem.invoice_id == inv.id,
            ent.ClientInvoiceItem.tenant_id == tenant_id,
        )
        .all()
    )

    return {
        "id": inv.id,
        "invoice_number": inv.invoice_number,
        "contract_id": inv.contract_id,
        "client_name": inv.client_name,
        "billing_month": inv.billing_month,
        "total_riders_supplied": inv.total_riders_supplied,
        "total_amount_billed": inv.total_amount_billed,
        "total_courier_payroll_cost": inv.total_courier_payroll_cost,
        "net_gross_profit": inv.net_gross_profit,
        "profit_margin_pct": round(inv.profit_margin_pct or 0.0, 1),
        "status": inv.status,
        "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
        "notes": inv.notes,
        "items": [
            {
                "id": it.id,
                "branch_name": it.branch_name,
                "days_worked": it.days_worked,
                "monthly_rate": it.monthly_rate,
                "total_line_amount": it.total_line_amount,
                "courier_cost_share": it.courier_cost_share,
                "line_margin": it.total_line_amount - it.courier_cost_share,
            }
            for it in items
        ],
    }


@router.patch("/{invoice_id}/status")
def update_client_invoice_status(
    invoice_id: int,
    payload: UpdateInvoiceStatusPayload,
    user: ent.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update invoice status: DRAFT -> ISSUED -> PAID, or CANCELLED with strict state machine validation."""
    tenant_id = _tenant_id(user, manage=True)
    inv = (
        db.query(ent.ClientInvoice)
        .filter(
            ent.ClientInvoice.id == invoice_id, ent.ClientInvoice.tenant_id == tenant_id
        )
        .first()
    )

    if not inv:
        raise HTTPException(404, "الفاتورة غير موجودة")

    target_status = payload.status.upper()
    current_status = inv.status.upper() if inv.status else "DRAFT"

    allowed_transitions = {
        "DRAFT": {"ISSUED", "CANCELLED"},
        "ISSUED": {"PAID", "CANCELLED"},
        "PAID": {"CANCELLED"},
        "CANCELLED": set(),
    }

    if target_status not in {"DRAFT", "ISSUED", "PAID", "CANCELLED"}:
        raise HTTPException(400, f"حالة الفاتورة '{payload.status}' غير صالحة")

    if target_status != current_status:
        if target_status not in allowed_transitions.get(current_status, set()):
            raise HTTPException(
                400,
                f"لا يمكن تحويل حالة الفاتورة من {current_status} إلى {target_status} مباشرة",
            )

    inv.status = target_status
    if target_status == "PAID" and not inv.paid_at:
        inv.paid_at = datetime.utcnow()
    if payload.notes:
        inv.notes = payload.notes

    db.commit()
    return {"status": "success", "invoice_id": inv.id, "new_status": inv.status}
