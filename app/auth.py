from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings


bearer_scheme = HTTPBearer(auto_error=False)
SUPPORTED_JWT_ALGORITHMS = ("RS256", "ES256")
_jwks_client: PyJWKClient | None = None
_jwks_url: str | None = None


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str | None
    claims: dict[str, Any]


def _supabase_url() -> str:
    if not settings.supabase_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="supabase url is not configured",
        )
    return settings.supabase_url.rstrip("/")


def _jwks_uri() -> str:
    return f"{_supabase_url()}/auth/v1/.well-known/jwks.json"


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client, _jwks_url

    jwks_url = _jwks_uri()
    if _jwks_client is None or _jwks_url != jwks_url:
        _jwks_client = PyJWKClient(jwks_url)
        _jwks_url = jwks_url
    return _jwks_client


def verify_supabase_jwt(token: str) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token",
        )

    algorithm = header.get("alg")
    if algorithm not in SUPPORTED_JWT_ALGORITHMS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unsupported authentication token",
        )

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=[algorithm],
            audience=settings.supabase_audience,
            issuer=f"{_supabase_url()}/auth/v1",
            options={"require": ["aud", "exp", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication token has expired",
        )
    except jwt.ImmatureSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication token is not active",
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token audience",
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token issuer",
        )
    except jwt.MissingRequiredClaimError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token",
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token",
        )

    if not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token subject",
        )

    return payload


def require_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = verify_supabase_jwt(credentials.credentials)
    try:
        user_id = UUID(claims["sub"])
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token subject",
        )

    return CurrentUser(
        id=user_id,
        email=claims.get("email"),
        claims=claims,
    )
