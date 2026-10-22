"""Rate limit keys.

The production stack is Cloudflare -> Render -> uvicorn. uvicorn's proxy
headers middleware rewrites ``request.client`` with the *first*
``X-Forwarded-For`` entry, and that entry is chosen by the caller, so keying
limits on ``request.client.host`` let anybody walk around a limit by sending a
fresh header with every request.

Three kinds of key are used instead:

``client_ip``   coarse abuse layer. The address of the caller, not of a
                header the caller wrote.
``account_key`` the account being used. A caller cannot change the account it
                logs in to, so this limit cannot be dodged by rotating IPs or
                headers. This is the real defence against credential stuffing.
``user_key``    the signed-in user (the subject of the access token).
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from slowapi import Limiter

from .security import decode_access_token


def _clean_header(request: Request, name: str) -> str | None:
    value = request.headers.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def client_ip(request: Request) -> str:
    """The address of the caller, as far as the proxy chain allows.

    Cloudflare (which fronts Render) overwrites ``CF-Connecting-IP`` with the
    address it sees, so a caller cannot forge it. Without Cloudflare in front,
    Render's load balancer appends the address it saw to ``X-Forwarded-For``
    and the last entry is that address. Only when neither header is present is
    the socket address used, and then only because uvicorn has not replaced it
    with a header value.
    """
    connecting_ip = _clean_header(request, "cf-connecting-ip")
    if connecting_ip:
        return connecting_ip

    forwarded = request.headers.get("x-forwarded-for") or ""
    entries = [part.strip() for part in forwarded.split(",") if part.strip()]
    if entries:
        return entries[-1]

    client = request.client
    return client.host if client is not None else "unknown"


def account_key(request: Request) -> str:
    """Key on the account in use instead of on where the request came from.

    The email is read from ``request.state.email``, which the auth dependency
    stores before the limit is checked.
    """
    email = getattr(request.state, "email", None)
    if email:
        return f"account:{email}"
    return f"ip:{client_ip(request)}"


def user_key(request: Request) -> str:
    """Key on the signed-in user, taken from the access token."""
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        try:
            payload = decode_access_token(token.strip())
        except HTTPException:
            payload = None
        if payload:
            subject = payload.get("sub")
            if subject is not None:
                return f"user:{subject}"
    return f"ip:{client_ip(request)}"


async def stash_account_email(request: Request) -> None:
    """Remember the email of the request so the limit can key on the account.

    FastAPI resolves dependencies before it calls the endpoint, and the limit
    is checked inside the endpoint, so the value is in place by then.
    """
    try:
        payload = await request.json()
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    email = payload.get("email")
    if isinstance(email, str) and email.strip():
        request.state.email = email.strip().lower()


limiter = Limiter(key_func=client_ip)
