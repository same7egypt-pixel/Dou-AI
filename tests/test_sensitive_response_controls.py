import pytest
from fastapi import HTTPException

from app.models.entities import Country, Courier, User, UserRole
from app.routers import fleet, hr


class _CreationDb:
    def commit(self):
        return None

    def refresh(self, _record):
        return None

    def get(self, *_args):
        return None


def _company_user():
    return User(
        phone="966500000030",
        name="Company",
        password_hash="not-used",
        role=UserRole.COMPANY,
        tenant_id=1,
        country=Country.SA,
        is_active=True,
    )


def test_create_rider_response_does_not_echo_password(monkeypatch):
    courier = Courier(
        id=42,
        tenant_id=1,
        name="Rider",
        phone="966500000031",
        country=Country.SA,
        supervisor_id=None,
        primary_project_id=None,
    )
    monkeypatch.setattr(fleet, "create_rider_record", lambda *_args, **_kwargs: (courier, object()))

    response = fleet.add_courier(
        {"name": "Rider", "phone": courier.phone, "password": "SecretPass9!"},
        _company_user(),
        _CreationDb(),
    )

    assert "password" not in response
    assert response["login_phone"] == courier.phone


def test_test_order_is_unavailable_when_legacy_delivery_is_disabled(monkeypatch):
    monkeypatch.setattr(fleet, "ENABLE_LEGACY_DELIVERY", False)

    with pytest.raises(HTTPException) as error:
        fleet.fleet_test_order({}, _company_user(), object())

    assert error.value.status_code == 404


class _EmptyQuery:
    def filter(self, *_args):
        return self

    def first(self):
        return None


class _SupervisorDb:
    def query(self, *_args):
        return _EmptyQuery()

    def add(self, record):
        if getattr(record, "id", None) is None:
            record.id = 77

    def commit(self):
        return None

    def refresh(self, _record):
        return None


def test_create_supervisor_response_does_not_echo_password():
    response = hr.create_supervisor(
        {"name": "Supervisor", "phone": "500000032", "password": "SecretPass9!"},
        _company_user(),
        _SupervisorDb(),
    )

    assert "password" not in response
    assert response["login_phone"] == "966500000032"
