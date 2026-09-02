"""Salary structures, components, and rider assignments."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ..database import Base
from .entities import utcnow


class SalaryStructure(Base):
    """هيكل راتب للسائقين: مكوناته + حدوده + الإصدار."""

    __tablename__ = "salary_structures"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_salary_structure_tenant_code"),
        Index("ix_salary_structure_tenant_active", "tenant_id", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    code = Column(String(40), nullable=False)
    name_ar = Column(String(120), nullable=False)
    name_en = Column(String(120))
    description_ar = Column(Text)
    description_en = Column(Text)
    currency = Column(String(3), default="SAR")
    is_active = Column(Boolean, default=True, nullable=False)
    version = Column(String(20), default="1.0")
    cycle = Column(String(20), default="MONTHLY")
    balance_period = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    components = relationship(
        "SalaryComponent", back_populates="structure", cascade="all, delete-orphan"
    )


class SalaryComponent(Base):
    """مكون راتب داخل هيكل: أساسي، لكل توصيلة، بدل، عمولة، حافز، خصم."""

    __tablename__ = "salary_components"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "salary_structure_id", "code", name="uq_salary_component_code"
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    salary_structure_id = Column(
        Integer, ForeignKey("salary_structures.id"), nullable=False, index=True
    )
    code = Column(String(40), nullable=False)
    name_ar = Column(String(120), nullable=False)
    name_en = Column(String(120))
    category = Column(String(30), default="BASE")
    calculation = Column(String(30), default="FLAT")
    amount = Column(Float, default=0.0)
    cap_amount = Column(Float)
    conditions = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)
    effective_from = Column(DateTime, default=utcnow)
    effective_to = Column(DateTime)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    structure = relationship("SalaryStructure", back_populates="components")


class RiderSalaryAssignment(Base):
    """ربط هيكل راتب بسائق مع تاريخ نفاذ."""

    __tablename__ = "rider_salary_assignments"
    __table_args__ = (
        UniqueConstraint(
            "courier_id",
            "salary_structure_id",
            "effective_from",
            name="uq_rider_salary_start",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_rider_salary_dates",
        ),
        Index("ix_rider_salary_tenant_courier", "tenant_id", "courier_id"),
        Index(
            "ix_rider_salary_structure_dates",
            "salary_structure_id",
            "effective_from",
            "effective_to",
        ),
    )

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    courier_id = Column(Integer, ForeignKey("couriers.id"), nullable=False, index=True)
    salary_structure_id = Column(
        Integer, ForeignKey("salary_structures.id"), nullable=False, index=True
    )
    effective_from = Column(DateTime, nullable=False)
    effective_to = Column(Date)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=utcnow, nullable=False)
