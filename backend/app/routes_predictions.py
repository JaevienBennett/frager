from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from .membership import is_member, require_member
from .models import Membership, Pick, Prediction, User, utcnow
from .schemas import (
    LeaderboardEntry,
    PickCreate,
    PickOut,
    PredictionCreate,
    PredictionDetail,
    PredictionOut,
    ResolveRequest,
)
from .security import get_current_user, get_db

router = APIRouter(prefix="/api", tags=["predictions"])


def prediction_out(prediction: Prediction) -> PredictionOut:
    yes = sum(1 for p in prediction.picks if p.side == "yes")
    no = sum(1 for p in prediction.picks if p.side == "no")
    return PredictionOut(
        id=prediction.id,
        question=prediction.question,
        status=prediction.status,
        creator_id=prediction.creator_id,
        created_at=prediction.created_at,
        yes_count=yes,
        no_count=no,
        resolved_outcome=prediction.resolved_outcome,
    )


@router.post(
    "/leagues/{league_id}/predictions",
    response_model=PredictionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_prediction(
    league_id: int,
    body: PredictionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_member(db, league_id, user.id)
    prediction = Prediction(
        league_id=league_id, creator_id=user.id, question=body.question
    )
    db.add(prediction)
    db.commit()
    db.refresh(prediction)
    return prediction_out(prediction)


@router.get("/leagues/{league_id}/predictions", response_model=list[PredictionOut])
def list_predictions(
    league_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_member(db, league_id, user.id)
    predictions = (
        db.query(Prediction)
        .filter(Prediction.league_id == league_id)
        .order_by(Prediction.id)
        .all()
    )
    return [prediction_out(p) for p in predictions]


@router.post("/predictions/{prediction_id}/pick", response_model=PickOut)
def make_pick(
    prediction_id: int,
    body: PickCreate,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    prediction = db.get(Prediction, prediction_id)
    if prediction is None or not is_member(db, prediction.league_id, user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Prediction not found"
        )
    if prediction.status != "open":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prediction is already settled",
        )
    pick = (
        db.query(Pick)
        .filter(Pick.prediction_id == prediction_id, Pick.user_id == user.id)
        .first()
    )
    if pick is not None:
        pick.side = body.side
        pick.stake = body.stake
        response.status_code = status.HTTP_200_OK
    else:
        pick = Pick(
            prediction_id=prediction_id,
            user_id=user.id,
            side=body.side,
            stake=body.stake,
        )
        db.add(pick)
        response.status_code = status.HTTP_201_CREATED
    db.commit()
    db.refresh(pick)
    return pick


@router.get("/predictions/{prediction_id}", response_model=PredictionDetail)
def get_prediction(
    prediction_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    prediction = db.get(Prediction, prediction_id)
    if prediction is None or not is_member(db, prediction.league_id, user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Prediction not found"
        )
    detail = prediction_out(prediction).model_dump()
    detail["picks"] = [PickOut.model_validate(p) for p in prediction.picks]
    return PredictionDetail(**detail)


@router.post("/predictions/{prediction_id}/resolve", response_model=PredictionOut)
def resolve_prediction(
    prediction_id: int,
    body: ResolveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    prediction = db.get(Prediction, prediction_id)
    if prediction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Prediction not found"
        )
    if prediction.creator_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the creator can resolve a prediction",
        )
    if prediction.status != "open":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prediction is already resolved",
        )
    prediction.status = "resolved"
    prediction.resolved_outcome = body.outcome
    prediction.resolved_at = utcnow()
    db.commit()
    db.refresh(prediction)
    return prediction_out(prediction)


@router.get(
    "/leagues/{league_id}/leaderboard", response_model=list[LeaderboardEntry]
)
def leaderboard(
    league_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_member(db, league_id, user.id)
    members = (
        db.query(User)
        .join(Membership, Membership.user_id == User.id)
        .filter(Membership.league_id == league_id)
        .all()
    )
    settled_picks = (
        db.query(Pick, Prediction)
        .join(Prediction, Prediction.id == Pick.prediction_id)
        .filter(
            Prediction.league_id == league_id,
            Prediction.status == "resolved",
        )
        .all()
    )
    entries: list[LeaderboardEntry] = []
    for member in members:
        points = 0
        correct = 0
        total = 0
        for pick, prediction in settled_picks:
            if pick.user_id != member.id:
                continue
            total += 1
            if pick.side == prediction.resolved_outcome:
                correct += 1
                points += pick.stake
            else:
                points -= pick.stake
        accuracy = correct / total if total else 0.0
        entries.append(
            LeaderboardEntry(
                user_id=member.id,
                email=member.email,
                points=points,
                correct=correct,
                total=total,
                accuracy=accuracy,
            )
        )
    entries.sort(key=lambda e: (-e.points, -e.accuracy, e.user_id))
    return entries
