import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import rate_limit
from . import ws
from .config import REFRESH_COOKIE_ONLY, REFRESH_TOKEN_EXPIRE_DAYS
from .models import League, Membership, Prediction, RefreshToken, User
from .schemas import (
    AccountDelete,
    Credentials,
    PasswordChange,
    RefreshRequest,
    SignupRequest,
    Token,
    UserOut,
)
from .security import (
    create_access_token,
    get_current_user,
    get_db,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from .session_cookie import (
    clear_refresh_cookie,
    csrf_token,
    read_refresh_cookie,
    require_allowed_origin,
    require_csrf,
    set_refresh_cookie,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# A rotated token replayed within this window is treated as a multi-tab race,
# not as theft. Outside the window, replaying it revokes every session.
ROTATION_GRACE = timedelta(seconds=15)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def _issue_session(
    db: Session, user: User, request: Request, response: Response
) -> Token:
    """Mint an access/refresh pair and persist the refresh token hash.

    The refresh token goes into an httpOnly cookie, so the browser keeps it
    and no script can read it. The access token goes into the response body:
    it is short lived and the client holds it in memory only.
    """
    access_token = create_access_token(str(user.id), user.token_version)
    refresh_token = _new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=_now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    db.commit()
    set_refresh_cookie(response, refresh_token, request)
    return Token(
        access_token=access_token,
        refresh_token=None if REFRESH_COOKIE_ONLY else refresh_token,
        csrf_token=csrf_token(user.id, user.token_version),
    )


def _revoke_active_refresh_tokens(
    db: Session, user_id: int, now: datetime, reason: str
) -> int:
    rows = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .all()
    )
    for row in rows:
        row.revoked_at = now
        row.revoked_reason = reason
    return len(rows)


@router.post("/signup", response_model=Token, status_code=status.HTTP_201_CREATED)
@rate_limit.limiter.limit("5/minute")
def signup(
    request: Request,
    response: Response,
    body: SignupRequest,
    db: Session = Depends(get_db),
):
    require_allowed_origin(request)
    existing = db.query(User).filter(User.email == body.email).first()
    if existing is not None:
        rate_limit.note_failed_attempt(request, body.email, kind="signup")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    existing = db.query(User).filter(User.nickname == body.nickname).first()
    if existing is not None:
        rate_limit.note_failed_attempt(request, body.email, kind="signup")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nickname already taken",
        )
    user = User(
        email=body.email,
        nickname=body.nickname,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _issue_session(db, user, request, response)


@router.post("/login", response_model=Token)
def login(
    request: Request,
    response: Response,
    body: Credentials,
    db: Session = Depends(get_db),
):
    # There is no request-count limit on this endpoint: it would count correct
    # logins too, and ten logins a minute from a shared address would lock
    # that address out. The address and the account are limited by the number
    # of *failures* instead - see rate_limit.note_failed_attempt.
    require_allowed_origin(request)
    user = db.query(User).filter(User.email == body.email).first()
    if user is None or not verify_password(body.password, user.password_hash):
        # Only failures are charged, so a correct password is never refused:
        # nobody can lock a known account out of signing in.
        rate_limit.note_failed_attempt(request, body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _issue_session(db, user, request, response)


@router.post("/refresh", response_model=Token)
@rate_limit.limiter.limit("60/minute")
def refresh(
    request: Request,
    response: Response,
    body: RefreshRequest | None = None,
    db: Session = Depends(get_db),
):
    """Rotate a refresh token. Presenting an already revoked token is theft.

    The token comes from the httpOnly cookie. The body is only read while
    clients are being moved over to the cookie, and never once
    ``REFRESH_COOKIE_ONLY`` is on.
    """
    require_allowed_origin(request)
    token = read_refresh_cookie(request)
    if token is None and not REFRESH_COOKIE_ONLY and body is not None:
        token = body.refresh_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(token))
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    now = _now()
    if row.revoked_at is not None:
        if row.revoked_reason != "rotated":
            # Deliberately revoked (logout or logout-all): not theft.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token has been revoked",
            )
        if now - _as_utc(row.revoked_at) <= ROTATION_GRACE:
            # Two tabs refreshed at once; the loser must not kill the winner.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token already rotated",
            )
        # A spent token replayed much later: assume it leaked.
        user = db.get(User, row.user_id)
        _revoke_active_refresh_tokens(db, row.user_id, now, "reuse")
        if user is not None:
            user.token_version += 1
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token reuse detected; all sessions revoked",
        )

    if _as_utc(row.expires_at) <= now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
        )

    row.revoked_at = now
    row.revoked_reason = "rotated"
    new_refresh_token = _new_refresh_token()
    db.add(
        RefreshToken(
            user_id=row.user_id,
            token_hash=hash_refresh_token(new_refresh_token),
            expires_at=now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    db.commit()
    user = db.get(User, row.user_id)
    access_token = create_access_token(
        str(row.user_id), user.token_version if user is not None else 0
    )
    set_refresh_cookie(response, new_refresh_token, request)
    return Token(
        access_token=access_token,
        refresh_token=None if REFRESH_COOKIE_ONLY else new_refresh_token,
        csrf_token=csrf_token(
            row.user_id, user.token_version if user is not None else 0
        ),
    )


@router.post("/logout")
@rate_limit.limiter.limit("30/minute")
def logout(
    request: Request,
    response: Response,
    body: RefreshRequest | None = None,
    db: Session = Depends(get_db),
):
    """Revoke the session the cookie points at and clear the cookie.

    The cookie is the credential here, so a request that carries it has to
    prove it came from the app: without the CSRF token another site could log
    the visitor out.
    """
    require_allowed_origin(request)
    token = read_refresh_cookie(request)
    from_cookie = token is not None
    if token is None and not REFRESH_COOKIE_ONLY and body is not None:
        token = body.refresh_token
    if token:
        row = (
            db.query(RefreshToken)
            .filter(RefreshToken.token_hash == hash_refresh_token(token))
            .first()
        )
        if row is not None and row.revoked_at is None:
            if from_cookie:
                user = db.get(User, row.user_id)
                require_csrf(
                    request,
                    csrf_token(
                        row.user_id, user.token_version if user is not None else 0
                    ),
                )
            row.revoked_at = _now()
            row.revoked_reason = "logout"
            db.commit()
    clear_refresh_cookie(response)
    return {"ok": True}


@router.post("/logout-all")
@rate_limit.limiter.limit("30/minute")
def logout_all(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke every refresh token and invalidate every outstanding access token."""
    require_allowed_origin(request)
    if read_refresh_cookie(request) is not None:
        # The browser will attach the cookie to this request, so the request
        # has to prove it came from the app.
        require_csrf(request, csrf_token(user.id, user.token_version))
    user.token_version += 1
    _revoke_active_refresh_tokens(db, user.id, _now(), "logout_all")
    db.commit()
    clear_refresh_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password", response_model=Token)
@rate_limit.limiter.limit("5/minute", key_func=rate_limit.user_key)
@rate_limit.limiter.limit("20/hour", key_func=rate_limit.user_key)
def change_password(
    request: Request,
    response: Response,
    body: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the caller's password and drop every other session.

    The old password is checked first, so the answer never says whether a
    password would be accepted without the current one being right.
    """
    require_allowed_origin(request)
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the current password",
        )
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    _revoke_active_refresh_tokens(db, user.id, _now(), "password_change")
    db.commit()
    db.refresh(user)
    # The access token this session was opened with is dead now. Drop the
    # sockets that were opened with it so they stop receiving updates.
    ws.close_user_nowait(user.id)
    return _issue_session(db, user, request, response)


@router.post("/delete-account")
@rate_limit.limiter.limit("5/minute", key_func=rate_limit.user_key)
@rate_limit.limiter.limit("20/hour", key_func=rate_limit.user_key)
def delete_account(
    request: Request,
    response: Response,
    body: AccountDelete,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete the caller's account, their picks and their open predictions.

    A league the caller owns that has other members in it has to be handed
    over or deleted first: deleting it here would take the other members'
    picks with it and rewrite their points.
    """
    require_allowed_origin(request)
    # Lock the row so two requests at once cannot both pass the checks below.
    locked = (
        db.query(User).filter(User.id == user.id).with_for_update().first()
    )
    if locked is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    if not verify_password(body.password, locked.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is incorrect",
        )

    blocking = (
        db.query(League)
        .join(Membership, Membership.league_id == League.id)
        .filter(League.owner_id == locked.id)
        .group_by(League.id)
        .having(func.count(Membership.id) > 1)
        .all()
    )
    if blocking:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transfer or delete the leagues you own that have other members first",
        )

    # Predictions the caller made by hand and never resolved are voided: with
    # the creator gone nobody can settle them any more. Games that settle
    # themselves stay open and keep working.
    (
        db.query(Prediction)
        .filter(
            Prediction.creator_id == locked.id,
            Prediction.status == "open",
            or_(
                Prediction.resolution_source.is_(None),
                Prediction.resolution_source != "auto",
            ),
        )
        .update({"status": "void"}, synchronize_session=False)
    )

    user_id = locked.id
    # Memberships, picks and refresh tokens go with the user. Predictions the
    # user created keep the picks other members made on them and keep their
    # points; only their creator becomes nobody.
    db.delete(locked)
    db.commit()
    ws.close_user_nowait(user_id)
    clear_refresh_cookie(response)
    return {"ok": True}
