import pytest
from fastapi import HTTPException

from app.models.entities import Country, User, UserRole
from app.routers.fleet import _require_permission, fleet_save_settings


def test_dou_admin_cannot_write_tenant_settings_without_tenant_context():
    user = User(role=UserRole.DOU_ADMIN, tenant_id=None)
    with pytest.raises(HTTPException) as error:
        fleet_save_settings({}, user, object())
    assert error.value.status_code == 403


def test_malformed_custom_permissions_fail_closed():
    user = User(role=UserRole.OPERATIONS, custom_permissions="{broken")
    with pytest.raises(HTTPException) as error:
        _require_permission(user, "dashboard")
    assert error.value.status_code == 403
