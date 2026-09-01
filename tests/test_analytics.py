"""Wave 3 tests — KPIs, targets, incentive rules, payroll inputs, dashboards."""
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import (
    Courier, CourierType, Country, DashboardDefinition, DashboardWidget,
    IncentiveRule, KPIDefinition, KPIResult, PayrollInputRecord, Target,
    Tenant, User, UserRole,
)
from app.routers.analytics import (
    DashboardCreate, DashboardUpdate, DashboardWidgetCreate,
    IncentiveRuleCreate, IncentiveRuleUpdate,
    KPIDefinitionCreate, KPIDefinitionUpdate, KPIResultCreate,
    PayrollInputCreate, TargetCreate, TargetUpdate,
    create_kpi, update_kpi, list_kpis,
    create_kpi_result, list_kpi_results,
    create_target, list_targets, update_target,
    create_incentive_rule, list_incentive_rules, update_incentive_rule,
    create_payroll_input, list_payroll_inputs, reverse_payroll_input,
    create_dashboard, list_dashboards, update_dashboard,
    create_dashboard_widget, list_dashboard_widgets,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def make_tenant(db, name):
    tenant = Tenant(name=name, country=Country.SA)
    db.add(tenant); db.commit(); db.refresh(tenant)
    return tenant


def make_user(db, tenant_id, phone, role=UserRole.COMPANY):
    user = User(phone=phone, password_hash="x", role=role, tenant_id=tenant_id)
    db.add(user); db.commit(); db.refresh(user)
    return user


def make_rider(db, tenant_id, suffix):
    rider = Courier(
        tenant_id=tenant_id, name=f"Rider {suffix}", phone=f"700{suffix}",
        courier_type=CourierType.COMPANY, country=Country.SA,
    )
    db.add(rider); db.commit(); db.refresh(rider)
    return rider


# ---------- KPI definitions ----------

def test_create_kpi(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000001")
    result = create_kpi(
        KPIDefinitionCreate(
            code="COMPLETION_RATE", name_ar="معدل الإكمال", name_en="Completion Rate",
            category="OPERATIONS", numerator_expression="completed_orders",
            denominator_expression="total_orders", unit="PERCENTAGE",
            effective_from=date(2026, 1, 1),
        ),
        user, db,
    )
    assert result["code"] == "COMPLETION_RATE"


def test_kpi_code_version_unique(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000002")
    create_kpi(
        KPIDefinitionCreate(
            code="CR", name_ar="معدل الإكمال", numerator_expression="x",
            effective_from=date(2026, 1, 1),
        ),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        create_kpi(
            KPIDefinitionCreate(
                code="CR", name_ar="معدل الإكمال 2", numerator_expression="x",
                effective_from=date(2026, 1, 1),
            ),
            user, db,
        )
    assert error.value.status_code == 409


def test_update_kpi(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000003")
    created = create_kpi(
        KPIDefinitionCreate(
            code="CR", name_ar="معدل الإكمال", numerator_expression="x",
            effective_from=date(2026, 1, 1),
        ),
        user, db,
    )
    updated = update_kpi(created["id"], KPIDefinitionUpdate(name_ar="معدل الإكمال المحدث"), user, db)
    assert updated["name_ar"] == "معدل الإكمال المحدث"


# ---------- KPI results ----------

def test_create_kpi_result(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000004")
    kpi = create_kpi(
        KPIDefinitionCreate(
            code="CR", name_ar="معدل الإكمال", numerator_expression="x",
            effective_from=date(2026, 1, 1),
        ),
        user, db,
    )
    result = create_kpi_result(
        KPIResultCreate(
            kpi_definition_id=kpi["id"], scope_type="RIDER", scope_id=1,
            period="2026-09", numerator_value=95, denominator_value=100, result_value=95.0,
        ),
        user, db,
    )
    assert result["result_value"] == 95.0


def test_kpi_result_updates_existing(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000005")
    kpi = create_kpi(
        KPIDefinitionCreate(
            code="CR", name_ar="معدل الإكمال", numerator_expression="x",
            effective_from=date(2026, 1, 1),
        ),
        user, db,
    )
    create_kpi_result(
        KPIResultCreate(
            kpi_definition_id=kpi["id"], scope_type="RIDER", scope_id=1,
            period="2026-09", numerator_value=95, denominator_value=100, result_value=95.0,
        ),
        user, db,
    )
    result = create_kpi_result(
        KPIResultCreate(
            kpi_definition_id=kpi["id"], scope_type="RIDER", scope_id=1,
            period="2026-09", numerator_value=98, denominator_value=100, result_value=98.0,
        ),
        user, db,
    )
    assert result["result_value"] == 98.0


# ---------- targets ----------

def test_create_target(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000006")
    result = create_target(
        TargetCreate(
            scope_type="RIDER", scope_id=1, target_type="ORDERS",
            period="2026-09", target_value=500,
        ),
        user, db,
    )
    assert result["target_value"] == 500


def test_target_unique_per_scope_period(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000007")
    create_target(
        TargetCreate(scope_type="RIDER", scope_id=1, target_type="ORDERS", period="2026-09", target_value=500),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        create_target(
            TargetCreate(scope_type="RIDER", scope_id=1, target_type="ORDERS", period="2026-09", target_value=600),
            user, db,
        )
    assert error.value.status_code == 409


def test_update_target(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000008")
    created = create_target(
        TargetCreate(scope_type="RIDER", scope_id=1, target_type="ORDERS", period="2026-09", target_value=500),
        user, db,
    )
    updated = update_target(created["id"], TargetUpdate(actual_value=450, achievement_percentage=90.0), user, db)
    assert updated["actual_value"] == 450


# ---------- incentive rules ----------

def test_create_incentive_rule(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000009")
    result = create_incentive_rule(
        IncentiveRuleCreate(
            code="BONUS_500", name_ar="بونص 500", name_en="Bonus 500",
            rule_type="BONUS", calculation_expression="base_salary * 0.1",
            effective_from=date(2026, 1, 1),
        ),
        user, db,
    )
    assert result["code"] == "BONUS_500"


def test_incentive_rule_unique_version(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000010")
    create_incentive_rule(
        IncentiveRuleCreate(
            code="BONUS_500", name_ar="بونص 500", calculation_expression="x",
            effective_from=date(2026, 1, 1),
        ),
        user, db,
    )
    with pytest.raises(HTTPException) as error:
        create_incentive_rule(
            IncentiveRuleCreate(
                code="BONUS_500", name_ar="بونص 500 2", calculation_expression="x",
                effective_from=date(2026, 1, 1),
            ),
            user, db,
        )
    assert error.value.status_code == 409


# ---------- payroll inputs ----------

def test_create_payroll_input(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000011")
    rider = make_rider(db, tenant.id, "1")
    result = create_payroll_input(
        PayrollInputCreate(
            courier_id=rider.id, month="2026-09", source_type="MANUAL",
            input_type="EARNING", amount=500, description="Bonus",
        ),
        user, db,
    )
    assert result["amount"] == 500
    assert result["input_type"] == "EARNING"


def test_payroll_input_rejects_invalid_type(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000012")
    rider = make_rider(db, tenant.id, "2")
    with pytest.raises(HTTPException) as error:
        create_payroll_input(
            PayrollInputCreate(
                courier_id=rider.id, month="2026-09", source_type="MANUAL",
                input_type="INVALID", amount=500,
            ),
            user, db,
        )
    assert error.value.status_code == 400


def test_reverse_payroll_input(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000013")
    rider = make_rider(db, tenant.id, "3")
    original = create_payroll_input(
        PayrollInputCreate(
            courier_id=rider.id, month="2026-09", source_type="MANUAL",
            input_type="EARNING", amount=500, description="Bonus",
        ),
        user, db,
    )
    result = reverse_payroll_input(original["id"], user, db)
    assert result["reversal_of_id"] == original["id"]


def test_reverse_rejects_double_reverse(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000014")
    rider = make_rider(db, tenant.id, "4")
    original = create_payroll_input(
        PayrollInputCreate(
            courier_id=rider.id, month="2026-09", source_type="MANUAL",
            input_type="EARNING", amount=500,
        ),
        user, db,
    )
    reverse_payroll_input(original["id"], user, db)
    with pytest.raises(HTTPException) as error:
        reverse_payroll_input(original["id"], user, db)
    assert error.value.status_code == 409


# ---------- dashboards ----------

def test_create_dashboard(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000015")
    result = create_dashboard(
        DashboardCreate(code="EXEC", name_ar="لوحة التنفيذ", name_en="Executive Dashboard", category="EXECUTIVE"),
        user, db,
    )
    assert result["code"] == "EXEC"


def test_dashboard_code_unique(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000016")
    create_dashboard(DashboardCreate(code="EXEC", name_ar="لوحة التنفيذ"), user, db)
    with pytest.raises(HTTPException) as error:
        create_dashboard(DashboardCreate(code="EXEC", name_ar="لوحة التنفيذ 2"), user, db)
    assert error.value.status_code == 409


def test_create_dashboard_widget(db):
    tenant = make_tenant(db, "Tenant")
    user = make_user(db, tenant.id, "966500000017")
    dashboard = create_dashboard(DashboardCreate(code="EXEC", name_ar="لوحة التنفيذ"), user, db)
    result = create_dashboard_widget(
        DashboardWidgetCreate(
            dashboard_definition_id=dashboard["id"],
            title_ar="معدل الإكمال", title_en="Completion Rate",
            widget_type="METRIC",
        ),
        user, db,
    )
    assert result["title_ar"] == "معدل الإكمال"


# ---------- tenant isolation ----------

def test_cross_tenant_kpi_rejected(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000018")
    kpi = create_kpi(
        KPIDefinitionCreate(code="CR", name_ar="معدل", numerator_expression="x", effective_from=date(2026, 1, 1)),
        user1, db,
    )
    user2 = make_user(db, tenant2.id, "966500000019")
    with pytest.raises(HTTPException) as error:
        update_kpi(kpi["id"], KPIDefinitionUpdate(name_ar="Hacked"), user2, db)
    assert error.value.status_code == 404


def test_cross_tenant_target_rejected(db):
    tenant1 = make_tenant(db, "Tenant1")
    tenant2 = make_tenant(db, "Tenant2")
    user1 = make_user(db, tenant1.id, "966500000020")
    target = create_target(
        TargetCreate(scope_type="RIDER", scope_id=1, target_type="ORDERS", period="2026-09", target_value=500),
        user1, db,
    )
    user2 = make_user(db, tenant2.id, "966500000021")
    with pytest.raises(HTTPException) as error:
        update_target(target["id"], TargetUpdate(actual_value=100), user2, db)
    assert error.value.status_code == 404
