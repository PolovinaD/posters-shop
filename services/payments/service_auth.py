"""
Service-to-service authentication.

WHY this exists
---------------
The ALB routes /api/<service> straight to each Service, so every route a
service declares is reachable from the internet — including the ones only
another service is supposed to call. Before this module, an anonymous caller
could POST /api/orders/orders/{id}/deliver, /api/inventory/release or
/api/production/events/order-paid and drive the platform's state directly.

Those endpoints cannot simply take the customer JWT dependency: the callers are
background workers with no user in context.

WHAT IT DOES
------------
A caller mints a short-lived HS256 token signed with the JWT_SECRET the platform
already distributes, carrying role="service". A callee accepts either that or a
genuine owner token. No new secret is introduced — `postershop-jwt` already
exists as a Kubernetes Secret.

THE TRADE-OFF, STATED PLAINLY
-----------------------------
JWT_SECRET is symmetric, so every service holding it can MINT any role, not just
verify one. This widens the blast radius of that single key: a compromised
service can forge an owner token. The correct fix is asymmetric signing (RS256,
private key in the issuer, public key everywhere else), which is recorded as
future work. This module is a strict improvement on "no check at all" and
deliberately not the end state.

ROLLOUT ORDER MATTERS
---------------------
Callers must start SENDING before callees start REQUIRING, or a rolling update
leaves new callees rejecting old callers. Sending is harmless to a callee that
does not yet check, so the safe order is: ship the senders, wire the env, then
ship the guards.
"""
import os
import time
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

ALGORITHM = "HS256"

# Minted per call. Signing is microseconds, so there is no cache to invalidate
# and no token sitting in memory to leak; the short life limits replay if one
# is captured from a log.
TOKEN_TTL_SECONDS = 300

SERVICE_ROLE = "service"

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login", auto_error=False)


def _secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        # Fail loud rather than mint an unsigned or throwaway token: a silently
        # unauthenticated caller is exactly the state this module exists to end.
        raise RuntimeError("JWT_SECRET environment variable is required")
    return secret


def mint_service_token(service_name: Optional[str] = None) -> str:
    """Return a short-lived token identifying this service to another service."""
    name = service_name or os.getenv("SERVICE_NAME") or "unknown"
    now = int(time.time())
    return jwt.encode(
        {
            "sub": f"service:{name}",
            "role": SERVICE_ROLE,
            "iat": now,
            "exp": now + TOKEN_TTL_SECONDS,
        },
        _secret(),
        algorithm=ALGORITHM,
    )


def service_auth_headers(service_name: Optional[str] = None) -> dict:
    """Authorization header for an outgoing service-to-service call."""
    return {"Authorization": f"Bearer {mint_service_token(service_name)}"}


def internal_headers(service_name: Optional[str] = None) -> dict:
    """Correlation + authorization headers for an internal call.

    Callers already pass `headers=correlation_headers()`; swapping that for
    `internal_headers()` keeps correlation-ID propagation intact and adds the
    service token in one edit per call site.
    """
    from logger import correlation_headers  # local import: same-service module
    return {**correlation_headers(), **service_auth_headers(service_name)}


def require_service_or_owner(token: str = Depends(_oauth2_scheme)) -> dict:
    """Allow a service token or a genuine owner token; reject everything else.

    Owner is allowed through so an operator can still drive these endpoints by
    hand during an incident, and so the admin dashboard keeps working where it
    already calls them.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        claims = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    if claims.get("role") not in (SERVICE_ROLE, "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Service or owner role required",
        )
    return claims
