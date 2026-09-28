"""Bearer and browser-session authentication with role and CSRF enforcement."""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings
from .models import Role


_bearer = HTTPBearer(auto_error=False)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Principal:
    subject: str
    role: Role
    user_id: str | None = None
    auth_kind: str = "bearer"
    csrf_token: str | None = None


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def csrf_for_session(raw_session_token: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), raw_session_token.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def decode_bearer(value: str, settings: Settings) -> Principal:
    try:
        claims = jwt.decode(value, settings.jwt_secret, algorithms=["HS256"],
                            audience=settings.jwt_audience, issuer=settings.jwt_issuer,
                            options={"require": ["exp", "iat", "sub", "role"]})
        return Principal(subject=str(claims["sub"]), role=Role(claims["role"]))
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise HTTPException(401, "invalid bearer token") from exc


def _from_request(request: Request, credentials: HTTPAuthorizationCredentials | None,
                  settings: Settings) -> Principal | None:
    if credentials is not None:
        if credentials.scheme.lower() != "bearer":
            raise HTTPException(401, "invalid authentication scheme")
        return decode_bearer(credentials.credentials, settings)
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return None
    if request.method not in _SAFE_METHODS:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not principal.csrf_token or not hmac.compare_digest(supplied, principal.csrf_token):
            raise HTTPException(403, "valid CSRF token required")
    return principal


def principal_dependency(settings: Settings):
    def current_principal(request: Request,
                          credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
        principal = _from_request(request, credentials, settings)
        if principal is None:
            raise HTTPException(401, "authentication required")
        return principal
    return current_principal


def optional_principal_dependency(settings: Settings):
    def optional_principal(request: Request,
                           credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)
                           ) -> Principal | None:
        return _from_request(request, credentials, settings)
    return optional_principal


def require_roles(principal_dep, *roles: Role):
    allowed = frozenset(roles)

    def dependency(principal: Principal = Depends(principal_dep)) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(403, "insufficient role")
        return principal
    return dependency
