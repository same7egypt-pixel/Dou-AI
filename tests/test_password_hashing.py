from app.routers.auth import hash_password, verify_password


def test_password_hash_round_trip_and_rejection():
    encoded = hash_password("StrongPass9!")

    assert encoded.startswith(("$2a$", "$2b$", "$2y$"))
    assert verify_password("StrongPass9!", encoded)
    assert not verify_password("WrongPass9!", encoded)
    assert not verify_password("StrongPass9!", "not-a-bcrypt-hash")
