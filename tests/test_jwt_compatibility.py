import jwt

from app.config import SECRET_KEY
from app.models.entities import Country, User, UserRole
from app.routers.auth import ALGORITHM, create_token


def test_created_access_token_is_decodable_with_expected_claims():
    user = User(
        id=77,
        phone="966500000077",
        name="JWT rider",
        password_hash="not-used",
        role=UserRole.COURIER,
        country=Country.SA,
        token_version=3,
        is_active=True,
    )

    token = create_token(user)
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

    assert payload["sub"] == "77"
    assert payload["phone"] == user.phone
    assert payload["role"] == "COURIER"
    assert payload["ver"] == 3
    assert "exp" in payload
