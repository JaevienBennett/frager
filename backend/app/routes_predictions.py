from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
from .rate_limit import limiter, user_key
from .security import get_current_user, get_db
from .services import espn_client
from .services import sports_resolver
from . import ws

router = APIRouter(prefix="/api", tags=["predictions"])


def pick_out(
    pick: Pick, nickname: str, was_correct: bool | None = None
) -> PickOut:
    return PickOut(
        id=pick.id,
        user_id=pick.user_id,
        nickname=nickname,
        side=pick.side,
        stake=pick.stake,
        created_at=pick.created_at,
        was_correct=was_correct,
    )


def prediction_out(prediction: Prediction) -> PredictionOut:
    yes = sum(1 for p in prediction.picks if p.side == "yes")
    no = sum(1 for p in prediction.picks if p.side == "no")
    yes_stake = sum(p.stake for p in prediction.picks if p.side == "yes")
    no_stake = sum(p.stake for p in prediction.picks if p.side == "no")
    return PredictionOut(
        id=prediction.id,
        question=prediction.question,
        status=prediction.status,
        creator_id=prediction.creator_id,
        created_at=prediction.created_at,
        yes_count=yes,
        no_count=no,
        yes_stake=yes_stake,
        no_stake=no_stake,
        resolved_outcome=prediction.resolved_outcome,
    )


@router.post(
    "/leagues/{league_id}/predictions",
    response_model=PredictionOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("20/minute", key_func=user_key)
def create_prediction(
    request: Request,
    league_id: int,
    body: PredictionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_member(db, league_id, user.id)
    external_game_id = None
    sport = None
    league_name = None
    game_time = None
    home_team = None
    away_team = None
    resolution_source = "manual"
    if body.game_url:
        eid = espn_client.extract_nfl_event_id(body.game_url)
        if not eid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid ESPN NFL game URL. Paste a full espn.com nfl game link.",
            )
        external_game_id = eid
        sport = "nfl"
        league_name = "nfl"
        resolution_source = "auto"
        event = espn_client.fetch_nfl_event(eid)
        parsed = espn_client.parse_nfl_result(event)
        game_time = parsed.get("game_time")
        home_team = parsed.get("home_team")
        away_team = parsed.get("away_team")
    prediction = Prediction(
        league_id=league_id,
        creator_id=user.id,
        question=body.question,
        external_game_id=external_game_id,
        sport=sport,
        league=league_name,
        home_team=home_team,
        away_team=away_team,
        game_time=game_time,
        resolution_source=resolution_source,
    )
    db.add(prediction)
    db.commit()
    db.refresh(prediction)
    ws.broadcast_nowait(
        league_id,
        {
            "type": "prediction_created",
            "league_id": league_id,
            "prediction_id": prediction.id,
        },
    )
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
    for p in predictions:
        if sports_resolver.try_auto_resolve(p, db):
            ws.broadcast_nowait(
                p.league_id,
                {
                    "type": "prediction_resolved",
                    "league_id": p.league_id,
                    "prediction_id": p.id,
                    "outcome": p.resolved_outcome,
                },
            )
            ws.broadcast_nowait(
                p.league_id,
                {"type": "leaderboard_updated", "league_id": p.league_id},
            )
    return [prediction_out(p) for p in predictions]


@router.post("/predictions/{prediction_id}/pick", response_model=PickOut)
@limiter.limit("60/minute", key_func=user_key)
def make_pick(
    request: Request,
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
    ws.broadcast_nowait(
        prediction.league_id,
        {
            "type": "pick_updated",
            "league_id": prediction.league_id,
            "prediction_id": prediction.id,
        },
    )
    ws.broadcast_nowait(
        prediction.league_id,
        {"type": "leaderboard_updated", "league_id": prediction.league_id},
    )
    return pick_out(pick, user.nickname)


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
    if sports_resolver.try_auto_resolve(prediction, db):
        ws.broadcast_nowait(
            prediction.league_id,
            {
                "type": "prediction_resolved",
                "league_id": prediction.league_id,
                "prediction_id": prediction.id,
                "outcome": prediction.resolved_outcome,
            },
        )
        ws.broadcast_nowait(
            prediction.league_id,
            {"type": "leaderboard_updated", "league_id": prediction.league_id},
        )
    caller_has_pick = any(p.user_id == user.id for p in prediction.picks)
    picks_visible = caller_has_pick or prediction.status == "resolved"
    detail = prediction_out(prediction).model_dump()
    if picks_visible and prediction.picks:
        picker_ids = {p.user_id for p in prediction.picks}
        nicknames = {
            u.id: u.nickname
            for u in db.query(User).filter(User.id.in_(picker_ids)).all()
        }
        resolved = prediction.status == "resolved"
        detail["picks"] = [
            pick_out(
                p,
                nicknames.get(p.user_id, f"user-{p.user_id}"),
                (
                    p.side == prediction.resolved_outcome
                    if resolved
                    else None
                ),
            )
            for p in prediction.picks
        ]
    else:
        detail["picks"] = []
    detail["picks_visible"] = picks_visible
    return PredictionDetail(**detail)


@router.post("/predictions/{prediction_id}/resolve", response_model=PredictionOut)
@limiter.limit("30/minute", key_func=user_key)
def resolve_prediction(
    request: Request,
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
            detail="Prediction is already settled",
        )
    prediction.status = "resolved"
    prediction.resolved_outcome = body.outcome
    prediction.resolved_at = utcnow()
    prediction.resolution_source = "manual"
    db.commit()
    db.refresh(prediction)
    ws.broadcast_nowait(
        prediction.league_id,
        {
            "type": "prediction_resolved",
            "league_id": prediction.league_id,
            "prediction_id": prediction.id,
            "outcome": body.outcome,
        },
    )
    ws.broadcast_nowait(
        prediction.league_id,
        {"type": "leaderboard_updated", "league_id": prediction.league_id},
    )
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
                nickname=member.nickname,
                points=points,
                correct=correct,
                total=total,
                accuracy=accuracy,
            )
        )
    entries.sort(key=lambda e: (-e.points, -e.accuracy, e.user_id))
    return entries
