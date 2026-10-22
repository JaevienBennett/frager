import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .membership import is_member
from .models import League, Membership, User
from .rate_limit import limiter, user_key
from .schemas import (
    JoinRequest,
    LeagueCreate,
    LeagueMemberOut,
    LeagueOut,
    LeagueUpdate,
    TransferOwnership,
)
from .security import get_current_user, get_db
from . import ws

router = APIRouter(prefix="/api/leagues", tags=["leagues"])


def member_count(db: Session, league_id: int) -> int:
    return db.query(Membership).filter(Membership.league_id == league_id).count()


def league_out(db: Session, league: League) -> LeagueOut:
    return LeagueOut(
        id=league.id,
        name=league.name,
        invite_code=league.invite_code,
        owner_id=league.owner_id,
        member_count=member_count(db, league.id),
    )


@router.post("", response_model=LeagueOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute", key_func=user_key)
def create_league(
    request: Request,
    body: LeagueCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    league = League(
        name=body.name,
        invite_code=secrets.token_urlsafe(6),
        owner_id=user.id,
    )
    db.add(league)
    db.flush()
    db.add(Membership(league_id=league.id, user_id=user.id))
    db.commit()
    db.refresh(league)
    return league_out(db, league)


@router.get("", response_model=list[LeagueOut])
def list_leagues(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(League, Membership)
        .join(Membership, Membership.league_id == League.id)
        .filter(Membership.user_id == user.id)
        .order_by(League.id)
        .all()
    )
    return [
        LeagueOut(
            id=league.id,
            name=league.name,
            invite_code=league.invite_code,
            owner_id=league.owner_id,
            member_count=member_count(db, league.id),
        )
        for league, _ in rows
    ]


@router.get("/{league_id}", response_model=LeagueOut)
def get_league(
    league_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    league = db.get(League, league_id)
    if league is None or not is_member(db, league_id, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    return league_out(db, league)


@router.post("/join", response_model=LeagueOut)
@limiter.limit("20/minute", key_func=user_key)
def join_league(
    request: Request,
    body: JoinRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    league = (
        db.query(League).filter(League.invite_code == body.invite_code).first()
    )
    if league is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invite code"
        )
    existing = (
        db.query(Membership)
        .filter(Membership.league_id == league.id, Membership.user_id == user.id)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Already a member"
        )
    db.add(Membership(league_id=league.id, user_id=user.id))
    db.commit()
    return league_out(db, league)


@router.post("/{league_id}/leave")
@limiter.limit("30/minute", key_func=user_key)
def leave_league(
    request: Request,
    league_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    league = db.get(League, league_id)
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    membership = (
        db.query(Membership)
        .filter(Membership.league_id == league_id, Membership.user_id == user.id)
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    if league.owner_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Owner cannot leave; transfer ownership or delete the league instead",
        )
    db.delete(membership)
    db.commit()
    return {"ok": True}


@router.get("/{league_id}/members", response_model=list[LeagueMemberOut])
def list_members(
    league_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the members of a league (no emails: only the pick list needs this)."""
    league = db.get(League, league_id)
    if league is None or not is_member(db, league_id, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    members = (
        db.query(User)
        .join(Membership, Membership.user_id == User.id)
        .filter(Membership.league_id == league_id)
        .order_by(User.nickname)
        .all()
    )
    return [
        LeagueMemberOut(
            user_id=member.id,
            nickname=member.nickname,
            is_owner=member.id == league.owner_id,
        )
        for member in members
    ]


@router.post("/{league_id}/transfer", response_model=LeagueOut)
@limiter.limit("10/minute", key_func=user_key)
def transfer_ownership(
    request: Request,
    league_id: int,
    body: TransferOwnership,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hand the league over to another member.

    The former owner stays a member and may leave afterwards; the new owner
    inherits the "cannot leave an owned league" rule.
    """
    league = db.get(League, league_id)
    if league is None or not is_member(db, league_id, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    if league.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the league owner can transfer ownership",
        )
    if body.new_owner_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already own this league",
        )
    target = (
        db.query(Membership)
        .filter(
            Membership.league_id == league_id,
            Membership.user_id == body.new_owner_id,
        )
        .first()
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this league",
        )

    # Conditional update: if somebody else won the race, no row is updated and
    # the caller is told to reload instead of silently overwriting them.
    updated = (
        db.query(League)
        .filter(League.id == league_id, League.owner_id == user.id)
        .update({League.owner_id: body.new_owner_id}, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ownership changed; reload and try again",
        )
    db.commit()
    db.refresh(league)
    ws.broadcast_nowait(
        league_id,
        {"type": "league_updated", "league_id": league_id, "owner_id": body.new_owner_id},
    )
    return league_out(db, league)


@router.patch("/{league_id}", response_model=LeagueOut)
@limiter.limit("30/minute", key_func=user_key)
def update_league(
    request: Request,
    league_id: int,
    body: LeagueUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    league = db.get(League, league_id)
    if league is None or not is_member(db, league_id, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    if league.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the league owner can rename it",
        )
    league.name = body.name
    db.commit()
    db.refresh(league)
    return league_out(db, league)


@router.delete("/{league_id}")
@limiter.limit("10/minute", key_func=user_key)
def delete_league(
    request: Request,
    league_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    league = db.get(League, league_id)
    if league is None or not is_member(db, league_id, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="League not found")
    if league.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the league owner can delete it",
        )
    # memberships / predictions / picks go with it via ON DELETE CASCADE
    db.delete(league)
    db.commit()
    return {"ok": True}
