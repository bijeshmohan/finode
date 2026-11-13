"""Who is calling the JSON API or /mcp: verifies Supabase JWTs against Supabase's published keys and exposes `CurrentUser`.

There are three ways in: a bearer header (scripts, assistants' own clients), the web pages' request state (set by
`web_auth.web_login_required`) and the session cookie sent by the finode app (the React frontend). A cookie request that
changes anything must also carry `X-Finode: 1` from the app's own origin (`FINODE_FRONTEND_ORIGIN`), so another site
cannot make the browser act for you.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import settings
from .session import ACCESS_COOKIE, REFRESH_COOKIE, AuthUnavailableError, InvalidCredentialsError, refresh_session

bearer_scheme = HTTPBearer(auto_error=False)
APP_HEADER = "X-Finode"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
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
        ) from None

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
        ) from None
    except jwt.ImmatureSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication token is not active",
        ) from None
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token audience",
        ) from None
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token issuer",
        ) from None
    except jwt.MissingRequiredClaimError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token",
        ) from None
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token",
        ) from None

    if not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token subject",
        )

    return payload


def reject_app_token(claims: dict[str, Any]) -> None:
    """Tokens Supabase issued to an OAuth app (an AI assistant) carry a `client_id`. They work on /mcp only,
    where the access level the user granted is enforced; everywhere else they would be a full sign-in."""
    if claims.get("client_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="this token belongs to a connected app and only works with the MCP server",
        )


def token_from_cookies(request: Request) -> str | None:
    """The access token the session cookies carry, renewed with the refresh cookie when it has expired (the new
    cookies are written by `web_auth.refreshed_cookies_middleware`); None when there is no usable session.

    Worked out once per request: Supabase rotates refresh tokens, so refreshing twice would spend the old one again."""
    if hasattr(request.state, "cookie_token"):
        return request.state.cookie_token
    request.state.cookie_token = _token_from_cookies(request)
    return request.state.cookie_token


def _token_from_cookies(request: Request) -> str | None:
    token = request.cookies.get(ACCESS_COOKIE)
    if token:
        try:
            reject_app_token(verify_supabase_jwt(token))
        except HTTPException as e:
            if e.status_code != 401:
                raise
        else:
            return token

    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if refresh_token:
        try:
            tokens = refresh_session(refresh_token)
        except InvalidCredentialsError, AuthUnavailableError:
            return None
        request.state.refreshed_tokens = tokens
        return tokens.access_token
    return None


def check_app_request(request: Request) -> None:
    """Refuse a cookie request that changes something unless it comes from the finode app: its own origin, with the
    X-Finode header (another site can send neither without the browser asking us first, and we would refuse)."""
    origin = request.headers.get("origin")
    if request.headers.get(APP_HEADER) != "1" or not settings.frontend_origin or origin != settings.frontend_origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="this request did not come from the finode app"
        )


def _user(token: str) -> CurrentUser:
    claims = verify_supabase_jwt(token)
    reject_app_token(claims)
    try:
        user_id = UUID(claims["sub"])
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid authentication token subject",
        ) from None
    return CurrentUser(id=user_id, email=claims.get("email"), claims=claims)


def require_authenticated_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials:
        return _user(credentials.credentials)
    token = getattr(request.state, "access_token", None)  # the web pages (web_auth.web_login_required)
    if token is None:
        token = token_from_cookies(request)
        if token is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if request.method not in SAFE_METHODS:
            check_app_request(request)
        request.state.access_token = token
    return _user(token)


@dataclass(frozen=True)
class CookieSession:
    """A signed-in person using the finode app, with the Supabase token their cookie carries (for calls Supabase
    must see the person make, such as OAuth consent)."""

    user: CurrentUser
    access_token: str


def require_cookie_session(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CookieSession:
    """For what a token alone must never do (minting tokens, connecting apps, erasing the books): the person has to be
    signed in to the finode app itself."""
    token = None if credentials else token_from_cookies(request)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="this needs you signed in to the finode app"
        )
    if request.method not in SAFE_METHODS:
        check_app_request(request)
    request.state.access_token = token
    return CookieSession(user=_user(token), access_token=token)
