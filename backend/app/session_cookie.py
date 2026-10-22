"""The refresh token lives in an httpOnly cookie, not in JavaScript.

Until M26 the refresh token was handed to the browser in a JSON body and kept
in ``localStorage``. Any script that got into the page - a bad dependency, a
typo-squatted package, an injected snippet - could read it and mint sessions
forever, and ``localStorage`` survives until somebody clears it by hand. The
cookie fixes both halves of that: ``HttpOnly`` means JavaScript cannot read it
at all, and the browser deletes it when the session ends.

The app and the API are on different sites (the frontend is on Vercel, the API
on Render), so the browser only sends the cookie back when it is
``SameSite=None`` - and ``SameSite=None`` is only allowed together with
``Secure``. On plain http (localhost during development) the cookie is
``SameSite=Lax`` instead, which is what a browser accepts there.

A cookie is sent by the browser to any request the page makes, including one
another site made it make, so it has to be defended:

* the **origin check** refuses a request whose ``Origin`` is not one of ours.
  A browser sends ``Origin`` on every POST and a page on another site cannot
  choose what it says.
* the **CSRF token** is a value the client has to send back in a header. It
  is derived from the account with the server's secret key, so it is stable
  for the life of the session and identical in every tab, and it is useless on
  its own: an attacker still needs the cookie, which only the browser will
  send to us.
"""

from __future__ import annotations

import hmac
from hashlib import sha256

from fastapi import HTTPException, Request, Response, status

from .config import CORS_ORIGINS, REFRESH_TOKEN_EXPIRE_DAYS, SECRET_KEY

REFRESH_COOKIE = "frager_refresh"
CSRF_HEADER = "x-csrf-token"
COOKIE_PATH = "/api/auth"
REFRESH_COOKIE_MAX_AGE = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60


def _is_secure(request: Request) -> bool:
    """True when the caller reached us over https.

    Behind Render and Cloudflare ``request.url.scheme`` is already ``https``:
    uvicorn's proxy headers middleware rewrites it from ``X-Forwarded-Proto``.
    """
    return request.url.scheme == "https"


def _samesite(secure: bool) -> str:
    return "none" if secure else "lax"


def set_refresh_cookie(response: Response, token: str, request: Request) -> None:
    """Hand the refresh token to the browser as an httpOnly cookie."""
    secure = _is_secure(request)
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite=_samesite(secure),
        path=COOKIE_PATH,
        max_age=REFRESH_COOKIE_MAX_AGE,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)


def read_refresh_cookie(request: Request) -> str | None:
    return request.cookies.get(REFRESH_COOKIE)


def csrf_token(user_id: int, token_version: int) -> str:
    """The value the client has to send back to prove a request is ours.

    It is derived from the account rather than from the session, so it
    survives a token rotation and is the same in every tab. It changes when
    the account's token version changes - a password change or a log out of
    all devices ends it.
    """
    message = f"csrf:{int(user_id)}:{int(token_version or 0)}".encode()
    return hmac.new(SECRET_KEY.encode(), message, sha256).hexdigest()


def require_csrf(request: Request, expected: str) -> None:
    """Refuse a request that carries our cookie but cannot prove it is ours."""
    supplied = request.headers.get(CSRF_HEADER) or ""
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing or invalid",
        )


def require_allowed_origin(request: Request) -> None:
    """Refuse a request that a page on another site made us.

    A browser sends ``Origin`` on every POST and a page on another site
    cannot choose what it says, so this is the check that stops a page
    somewhere else from using the visitor's cookie. A request without an
    ``Origin`` header does not come from a browser form (curl, the tests) and
    is left to the CSRF token.
    """
    origin = request.headers.get("origin")
    if origin and origin not in CORS_ORIGINS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin not allowed",
        )
