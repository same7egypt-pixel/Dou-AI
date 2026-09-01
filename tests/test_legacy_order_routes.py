import pytest
from fastapi import HTTPException

from app.models.entities import Country, User, UserRole
from app.routers import fleet


@pytest.mark.parametrize(
    "action",
    [
        lambda user, db: fleet.fleet_reassign(1, {}, user, db),
        lambda user, db: fleet.fleet_escalate(1, user, db),
        lambda user, db: fleet.fleet_broadcast(1, user, db),
    ],
)
def test_legacy_order_mutations_are_unavailable_when_feature_is_disabled(monkeypatch, action):
    monkeypatch.setattr(fleet, "ENABLE_LEGACY_DELIVERY", False, raising=False)
    company_user = User(
        phone="966500000010",
        name="Company",
        password_hash="not-used",
        role=UserRole.COMPANY,
        tenant_id=1,
        country=Country.SA,
        is_active=True,
    )

    with pytest.raises(HTTPException) as error:
        action(company_user, object())

    assert error.value.status_code == 404
