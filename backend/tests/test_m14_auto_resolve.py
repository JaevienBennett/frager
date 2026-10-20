from datetime import datetime, timedelta, timezone

from app import models
from app.database import SessionLocal, engine
from app.services import espn_client
from app.services import sports_resolver


def _get_ids():
    db = SessionLocal()
    try:
        league = db.query(models.League).first()
        user = db.query(models.User).first()
        return league.id if league else 1, user.id if user else 1
    finally:
        db.close()


def test_migration_idempotent():
    from migrations import migrate_v14_auto_resolve

    migrate_v14_auto_resolve.migrate()
    migrate_v14_auto_resolve.migrate()
    with engine.begin() as conn:
        cols = [r[0] for r in conn.exec_driver_sql(
            "SELECT column_name FROM information_schema.columns WHERE table_name='predictions'"
        )]
    assert "external_game_id" in cols
    assert "resolution_source" in cols
    assert "auto_resolved_at" in cols
    db = SessionLocal()
    bad = db.query(models.Prediction).filter(models.Prediction.resolution_source == None).count()
    db.close()
    assert bad == 0


def test_extract_nfl():
    assert espn_client.extract_nfl_event_id("https://www.espn.com/nfl/game/_/gameId/401547378") == "401547378"
    assert espn_client.extract_nfl_event_id("https://espn.com/nfl/game/_/401234567") == "401234567"
    assert espn_client.extract_nfl_event_id("https://www.espn.com/mlb/game/_/gameId/401547378") is None
    assert espn_client.extract_nfl_event_id("http://example.com/bad") is None


def test_parse_nfl_final_win():
    ev = {
        "competitions": [{
            "date": "2020-01-01T00:00:00Z",
            "status": {"type": {"state": "postgame", "completed": True, "name": "STATUS_FINAL"}},
            "competitors": [
                {"homeAway": "home", "score": "14", "team": {"displayName": "Home"}},
                {"homeAway": "away", "score": "10", "team": {"displayName": "Away"}},
            ],
        }]
    }
    p = espn_client.parse_nfl_result(ev)
    assert p["ready"] is True
    assert p["home_won"] is True


def test_parse_tie_no_resolve():
    ev = {
        "competitions": [{
            "date": "2020-01-01T00:00:00Z",
            "status": {"type": {"state": "postgame", "completed": True, "name": "STATUS_FINAL"}},
            "competitors": [
                {"homeAway": "home", "score": "14", "team": {"displayName": "Home"}},
                {"homeAway": "away", "score": "14", "team": {"displayName": "Away"}},
            ],
        }]
    }
    p = espn_client.parse_nfl_result(ev)
    assert p["ready"] is False
    assert p["reason"] == "TIE"


def test_parse_postponed():
    ev = {"competitions": [{"status": {"type": {"name": "STATUS_POSTPONED"}}}]}
    p = espn_client.parse_nfl_result(ev)
    assert p["ready"] is False


def test_lazy_resolve(monkeypatch):
    db = SessionLocal()
    pred = models.Prediction(
        league_id=_get_ids()[0],
        creator_id=_get_ids()[1],
        question="Test?",
        status="open",
        external_game_id="123456",
        sport="nfl",
        league="nfl",
        resolution_source="auto",
        game_time=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db.add(pred)
    db.commit()
    db.refresh(pred)
    pid = pred.id

    def fake_fetch(eid):
        return {"competitions": [{"date": "2020-01-01T00:00:00Z", "status": {"type": {"state": "postgame", "completed": True, "name": "STATUS_FINAL"}}, "competitors": [{"homeAway": "home", "score": "21", "team": {"displayName": "H"}}, {"homeAway": "away", "score": "3", "team": {"displayName": "A"}}]}]}
    monkeypatch.setattr(espn_client, "fetch_nfl_event", fake_fetch)
    pred2 = db.get(models.Prediction, pid)
    resolved = sports_resolver.try_auto_resolve(pred2, db)
    assert resolved is True
    pred3 = db.get(models.Prediction, pid)
    assert pred3.status == "resolved"
    assert pred3.resolved_outcome == "yes"
    assert pred3.auto_resolved_at is not None
    # second time no overwrite
    resolved2 = sports_resolver.try_auto_resolve(pred3, db)
    assert resolved2 is False
    db.query(models.Prediction).filter(models.Prediction.id == pid).delete()
    db.commit()
    db.close()


def test_no_resolve_if_game_not_ended(monkeypatch):
    db = SessionLocal()
    pred = models.Prediction(
        league_id=_get_ids()[0],
        creator_id=_get_ids()[1],
        question="T?",
        status="open",
        external_game_id="999",
        sport="nfl",
        league="nfl",
        resolution_source="auto",
        game_time=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db.add(pred)
    db.commit()
    db.refresh(pred)
    pid = pred.id

    def fake_fetch(eid):
        return {"competitions": [{"status": {"type": {"state": "in", "completed": False}}}]}
    monkeypatch.setattr(espn_client, "fetch_nfl_event", fake_fetch)
    pred2 = db.get(models.Prediction, pid)
    resolved = sports_resolver.try_auto_resolve(pred2, db)
    assert resolved is False
    pred3 = db.get(models.Prediction, pid)
    assert pred3.status == "open"
    db.query(models.Prediction).filter(models.Prediction.id == pid).delete()
    db.commit()
    db.close()


def test_no_overwrite_manual():
    db = SessionLocal()
    pred = models.Prediction(
        league_id=_get_ids()[0],
        creator_id=_get_ids()[1],
        question="M?",
        status="resolved",
        resolved_outcome="no",
        resolution_source="auto",
        external_game_id="777",
        sport="nfl",
        league="nfl",
    )
    db.add(pred)
    db.commit()
    db.refresh(pred)
    pid = pred.id
    pred2 = db.get(models.Prediction, pid)
    resolved = sports_resolver.try_auto_resolve(pred2, db)
    assert resolved is False
    pred3 = db.get(models.Prediction, pid)
    assert pred3.resolved_outcome == "no"
    db.query(models.Prediction).filter(models.Prediction.id == pid).delete()
    db.commit()
    db.close()
