from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.entities import Courier, DailyLog, Tenant, Country, CourierType
from app.routers.driver_dedicated import _record_delivery_to_daily_log

TEST_DB_URL = "sqlite:///./test_audit_db.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)

def test_fix_1_record_delivery_increments_orders_count():
    db = TestingSession()
    try:
        tenant = Tenant(name="Test Fleet", country=Country.SA, plan="STARTER")
        db.add(tenant)
        db.flush()

        courier = Courier(
            tenant_id=tenant.id,
            name="Test Courier",
            phone="966500000001",
            courier_type=CourierType.COMPANY,
            country=Country.SA,
        )
        db.add(courier)
        db.flush()

        test_date = date(2026, 9, 5)
        daily_log = DailyLog(
            courier_id=courier.id,
            tenant_id=tenant.id,
            project_id=None,
            log_date=test_date,
            orders_count=20,
            driver_orders=20,
            verified_orders=0,
            variance=0,
            source_type="MANUAL",
        )
        db.add(daily_log)
        db.commit()

        class MockOrder:
            order_date = test_date

        # Rider delivers 1 branch dispatch order
        _record_delivery_to_daily_log(MockOrder(), courier, db)
        db.commit()
        db.refresh(daily_log)

        assert daily_log.verified_orders == 1
        assert daily_log.orders_count == 21, f"Expected orders_count to be 21, but got {daily_log.orders_count}"
        assert daily_log.variance == 1
    finally:
        db.close()
