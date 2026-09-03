"""Authenticating a partner that posts data in, rather than a person logging in.

Ninja's ingestion endpoints took an `X-Tenant-Id` header and believed it. There
was no key, and the `X-Ninja-Signature` header the handler accepted was never
read. Anyone who could reach the port could write delivery facts into any
tenant, and those facts feed the order counts payroll pays on.

The credential these endpoints should have been using already existed:
`PartnerCredential` issues a key, stores only its SHA-256, carries scopes and an
expiry, and belongs to exactly one tenant. This module is the missing verifier.

The tenant comes from the credential and never from the request. That is the
whole point: a caller cannot name the tenant it is writing to.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from ..models.entities import PartnerCredential, Tenant
from .entitlements import capabilities_for

# The prefix issued by enterprise.create_credential is the first 16 characters
# of the key itself, so a lookup narrows to one row before any hashing.
KEY_PREFIX_LENGTH = 16


def _scopes(credential: PartnerCredential) -> list[str]:
    raw = credential.scopes
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        # Tolerate a comma-separated string; several rows were written that way.
        return [s.strip() for s in str(raw).split(",") if s.strip()]
    if isinstance(parsed, str):
        return [parsed]
    return [str(s) for s in parsed]


def authenticate_partner(
    db: Session, api_key: str | None, scope: str
) -> PartnerCredential:
    """Resolve an API key to its credential, or refuse.

    Every failure returns the same 401 so a caller cannot use the response to
    learn whether a prefix exists, whether it has expired, or which tenant it
    belongs to. The one distinguishable answer is 403 for a valid key that has
    not been granted this scope, which the partner's own operator needs to see.
    """
    if not api_key or len(api_key) <= KEY_PREFIX_LENGTH:
        raise HTTPException(401, "Invalid or missing partner credential")

    prefix = api_key[:KEY_PREFIX_LENGTH]
    candidates = (
        db.query(PartnerCredential)
        .filter(
            PartnerCredential.key_prefix == prefix,
            PartnerCredential.is_active.is_(True),
        )
        .all()
    )

    digest = hashlib.sha256(api_key.encode()).hexdigest()
    credential = None
    for row in candidates:
        # compare_digest, not ==, so the comparison does not leak the hash one
        # byte at a time under timing measurement.
        if hmac.compare_digest(row.key_hash or "", digest):
            credential = row
            break
    if credential is None:
        raise HTTPException(401, "Invalid or missing partner credential")

    if credential.expires_at is not None:
        expires = credential.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            raise HTTPException(401, "Invalid or missing partner credential")

    if scope not in _scopes(credential):
        raise HTTPException(403, f"Credential is not granted the {scope} scope")

    return credential


def ingestion_tenant(
    db: Session, api_key: str | None, scope: str, capability: str
) -> Tenant:
    """The tenant a partner may write to, proven by its key.

    Two independent conditions, because either alone has failed before: the key
    must be valid and scoped, and the tenant it belongs to must still hold the
    capability. A subscription that lapses stops the feed without anyone having
    to remember to revoke the key.
    """
    credential = authenticate_partner(db, api_key, scope)
    tenant = db.get(Tenant, credential.tenant_id)
    if tenant is None:
        raise HTTPException(401, "Invalid or missing partner credential")
    if capability not in capabilities_for(tenant):
        raise HTTPException(
            403, f"This account is not entitled to {capability}"
        )
    return tenant


def api_key_header(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    authorization: str | None = Header(None),
) -> str | None:
    """Accept the key either as X-API-Key or as a bearer token."""
    if x_api_key:
        return x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None
