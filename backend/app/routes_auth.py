import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from . import rate_limit
from .config import REFRESH_TOKEN_EXPIRE_DAYS
from .models import RefreshToken, User
from .schemas import Credentials, RefreshRequest, SignupRequest, Token, UserOut
from .security import (
    create_access_token,
    get_current_user,
    get_db,
    hash_password,
    hash_refresh_token,
    verify_password,
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


def _issue_session(db: Session, user: User) -> Token:
    """Mint an access/refresh pair and persist the refresh token hash."""
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
    return Token(access_token=access_token, refresh_token=refresh_token)


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
@rate_limit.limiter.limit("5/minute", key_func=rate_limit.account_key)
def signup(
    request: Request,
    body: SignupRequest,
    db: Session = Depends(get_db),
    _account: None = Depends(rate_limit.stash_account_email),
):
    existing = db.query(User).filter(User.email == body.email).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    existing = db.query(User).filter(User.nickname == body.nickname).first()
    if existing is not None:
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
    return _issue_session(db, user)


@router.post("/login", response_model=Token)
@rate_limit.limiter.limit("10/minute")
@rate_limit.limiter.limit("10/minute", key_func=rate_limit.account_key)
def login(
    request: Request,
    body: Credentials,
    db: Session = Depends(get_db),
    _account: None = Depends(rate_limit.stash_account_email),
):
    user = db.query(User).filter(User.email == body.email).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _issue_session(db, user)


@router.post("/refresh", response_model=Token)
@rate_limit.limiter.limit("60/minute")
def refresh(request: Request, body: RefreshRequest, db: Session = Depends(get_db)):
    """Rotate a refresh token. Presenting an already revoked token is theft."""
    row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(body.refresh_token))
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
    return Token(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout")
@rate_limit.limiter.limit("30/minute")
def logout(request: Request, body: RefreshRequest, db: Session = Depends(get_db)):
    """Revoke a single refresh token. Unknown tokens are a no-op."""
    row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(body.refresh_token))
        .first()
    )
    if row is not None and row.revoked_at is None:
        row.revoked_at = _now()
        row.revoked_reason = "logout"
        db.commit()
    return {"ok": True}


@router.post("/logout-all")
@rate_limit.limiter.limit("30/minute")
def logout_all(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke every refresh token and invalidate every outstanding access token."""
    user.token_version += 1
    _revoke_active_refresh_tokens(db, user.id, _now(), "logout_all")
    db.commit()
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
