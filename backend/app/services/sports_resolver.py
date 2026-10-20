from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Prediction, utcnow
from . import espn_client


def try_auto_resolve(prediction: Prediction, db: Session) -> bool:
    """
    Lazy on-read auto-resolution. Returns True if resolved now.
    Never overwrites manually resolved or already resolved predictions.
    """
    if prediction.status != "open":
        return False
    if (prediction.resolution_source or "").lower() != "auto":
        return False
    if not prediction.external_game_id or (prediction.sport or "").lower() != "nfl":
        return False
    game_time = prediction.game_time
    if game_time is not None and game_time.tzinfo is None:
        game_time = game_time.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if game_time is not None and game_time > now:
        return False
    event = espn_client.fetch_nfl_event(prediction.external_game_id)
    if event is None:
        return False
    parsed = espn_client.parse_nfl_result(event)
    if not parsed.get("ready"):
        return False
    home_won = parsed.get("home_won")
    if home_won is True:
        outcome = "yes"
    elif home_won is False:
        outcome = "no"
    else:
        return False
    # Resolve via same path logic
    prediction.status = "resolved"
    prediction.resolved_outcome = outcome
    prediction.resolved_at = utcnow()
    prediction.auto_resolved_at = utcnow()
    if not prediction.home_team and parsed.get("home_team"):
        prediction.home_team = parsed.get("home_team")
    if not prediction.away_team and parsed.get("away_team"):
        prediction.away_team = parsed.get("away_team")
    if prediction.game_time is None and parsed.get("game_time"):
        prediction.game_time = parsed.get("game_time")
    db.commit()
    db.refresh(prediction)
    return True
