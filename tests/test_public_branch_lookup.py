"""The cashier's branch lookup takes no token, so what it returns is public.

It briefly listed every active branch of every merchant. That published the
customer book — which brands run on DOU, in which cities, how many branches each
has — to anyone with the URL, and handed out the `branch_id` that is half of a
cashier's credential (the other half is a four-digit PIN).

The screen it serves is real: a cashier must not be asked to type a database id.
So the lookup stayed, as a search. Someone setting up a tablet knows the
restaurant's name; a scraper does not.
"""

import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models.merchant import MerchantAccount, MerchantBranch
from app.utils.security import hash_pin

TEST_DB_FILE = "./test_public_branch_lookup.db"
engine = create_engine(
    f"sqlite:///{TEST_DB_FILE}", connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

BRANDS = [
    ("شاورما كلاسيك", "فرع السليمانية", "الرياض"),
    ("بيتزا الحي", "فرع التحلية", "الرياض"),
    ("برجر ستيشن", "فرع الملقا", "الرياض"),
    ("كشري المحروسة", "فرع مدينة نصر", "القاهرة"),
]


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    if os.path.exists(TEST_DB_FILE):
        os.remove(TEST_DB_FILE)
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    for i, (brand, branch_name, city) in enumerate(BRANDS, start=1):
        db.add(
            MerchantAccount(
                id=i,
                trade_name=brand,
                billing_contact_email=f"b{i}@test.sa",
                billing_contact_phone=f"96650000000{i}",
                payment_terms_days=30,
                is_active=True,
            )
        )
        db.flush()
        db.add(
            MerchantBranch(
                id=i,
                merchant_account_id=i,
                branch_name=branch_name,
                city=city,
                latitude=24.7,
                longitude=46.7,
                geofence_radius_meters=200,
                cashier_access_pin=hash_pin("4417"),
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
        )
    db.commit()
    db.close()

    yield
    app.dependency_overrides.clear()
    engine.dispose()
    if os.path.exists(TEST_DB_FILE):
        os.remove(TEST_DB_FILE)


@pytest.fixture
def client():
    return TestClient(app)


def test_no_search_term_returns_no_customers(client):
    """The bare endpoint used to hand back the whole book."""
    res = client.get("/merchant/branches/public")
    assert res.status_code == 200
    assert res.json() == [], "the customer list is readable without a search term"


def test_a_single_character_is_not_a_search(client):
    """One letter would enumerate almost everything just as well as no term."""
    for ch in ("ش", "ا", "f"):
        res = client.get("/merchant/branches/public", params={"q": ch})
        assert res.json() == [], f"'{ch}' returned customers"


def test_a_city_name_does_not_list_the_customers_in_it(client):
    """Everyone knows the city. Matching on it is the same leak by another route."""
    res = client.get("/merchant/branches/public", params={"q": "الرياض"})
    assert res.status_code == 200
    names = {b["merchant_name"] for b in res.json()}
    assert "بيتزا الحي" not in names and "برجر ستيشن" not in names, (
        "searching a city listed unrelated customers who operate there"
    )


def test_the_cashier_still_finds_the_branch_by_its_name(client):
    """The screen this exists for has to keep working."""
    res = client.get("/merchant/branches/public", params={"q": "شاورما"})
    assert res.status_code == 200
    found = res.json()
    assert len(found) == 1, f"expected the one matching brand, got {len(found)}"
    assert found[0]["merchant_name"] == "شاورما كلاسيك"
    assert found[0]["id"] == 1

    # And by the branch's own name, which is what is written on the door.
    res = client.get("/merchant/branches/public", params={"q": "السليمانية"})
    assert [b["id"] for b in res.json()] == [1]
