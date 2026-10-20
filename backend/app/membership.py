from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .models import Membership


def is_member(db: Session, league_id: int, user_id: int) -> bool:
    return (
        db.query(Membership)
        .filter(Membership.league_id == league_id, Membership.user_id == user_id)
        .first()
        is not None
    )


def require_member(db: Session, league_id: int, user_id: int) -> None:
    if not is_member(db, league_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="League not found"
        )
