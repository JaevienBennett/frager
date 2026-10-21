import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .membership import is_member
from .models import League, Membership, User
from .schemas import JoinRequest, LeagueCreate, LeagueOut, LeagueUpdate
from .security import get_current_user, get_db

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
def create_league(
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
def join_league(
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
def leave_league(
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
            detail="Owner cannot leave; delete the league instead",
        )
    db.delete(membership)
    db.commit()
    return {"ok": True}


@router.patch("/{league_id}", response_model=LeagueOut)
def update_league(
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
def delete_league(
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
