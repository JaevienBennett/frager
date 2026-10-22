"""Rate limit keys.

The production stack is Cloudflare -> Render -> uvicorn. uvicorn's proxy
headers middleware rewrites ``request.client`` with the *first*
``X-Forwarded-For`` entry, and that entry is chosen by the caller, so keying
limits on ``request.client.host`` let anybody walk around a limit by sending a
fresh header with every request.

Two kinds of key are used instead:

``client_ip``   coarse abuse layer. The address of the caller, not of a
                header the caller wrote.
``user_key``    the signed-in user (the subject of the access token).

Credentials get a third, softer budget in ``note_failed_attempt``. It is keyed
on the account being tried *and* on the address the attempt came from, and it
only counts *failures*, so a correct password is never refused. That matters: a
limit that counts successes can be turned into a lockout by anybody who knows
an email address - and it is not only the account that has to be protected. The
address budget is what stops one machine from trying one hundred accounts ten
times each, and it counts failures for the same reason: ten correct logins
from a shared office address must not lock the office out.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from slowapi import Limiter

from .security import decode_access_token

# How many wrong passwords one account may spend inside the window. The
# window is the same length as the per-IP login limit.
FAILED_ATTEMPT_LIMIT = 10
FAILED_ATTEMPT_WINDOW_SECONDS = 60
# Signup conflicts (email or nickname taken) get their own, smaller budget.
SIGNUP_ATTEMPT_LIMIT = 5


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


def failed_attempt_key(email: str, kind: str = "login") -> str:
    """Key on the account whose attempts are failing.

    The address is normalised so that one account cannot buy itself a fresh
    budget by changing the case of the address it guesses.
    """
    return f"failed-{kind}:{email.strip().lower()}"


def failed_address_key(address: str, kind: str = "login") -> str:
    """Key on the address the failing attempts came from."""
    return f"failed-address-{kind}:{address}"


def note_failed_attempt(request: Request, email: str, kind: str = "login") -> None:
    """Charge one failed attempt to the account and to the address.

    Only failures are charged. A correct password is never blocked, so nobody
    can lock a known account out of signing in by guessing at it, and a busy
    address (an office, a school, a phone carrier) cannot be locked out
    either - this is the defence against credential stuffing that a plain
    per-account request counter used to provide.

    Every address is charged the same way, including addresses that have no
    account, so the answer does not reveal whether an account exists.
    """
    limit = SIGNUP_ATTEMPT_LIMIT if kind == "signup" else FAILED_ATTEMPT_LIMIT
    keys = (
        failed_attempt_key(email, kind),
        failed_address_key(client_ip(request), kind),
    )
    for key in keys:
        count = limiter._storage.incr(key, FAILED_ATTEMPT_WINDOW_SECONDS)
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Try again later.",
            )


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


limiter = Limiter(key_func=client_ip)
