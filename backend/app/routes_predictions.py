from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from .membership import is_member, require_member
from .models import Pick, Prediction, User
from .schemas import PickCreate, PickOut, PredictionCreate, PredictionDetail, PredictionOut
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
