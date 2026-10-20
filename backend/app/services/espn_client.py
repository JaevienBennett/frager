from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ESPN_EVENT_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/events/{event_id}"


class ESPNError(Exception):
    pass


def extract_nfl_event_id(game_url: str) -> str | None:
    if not game_url or not isinstance(game_url, str):
        return None
    try:
        parsed = urlparse(game_url.strip())
    except Exception:
        return None
    host = (parsed.netloc or "").lower()
    if "espn.com" not in host:
        return None
    path = parsed.path or ""
    if "/nfl/" not in path:
        return None
    m = re.search(r"/game/_/(?:[^/]+/)?(\d{6,12})", path)
    if m:
        return m.group(1)
    m = re.search(r"gameId[=/](\d{6,12})", parsed.query or "")
    if m:
        return m.group(1)
    return None


def _safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def fetch_nfl_event(event_id: str, timeout: float = 8.0) -> dict | None:
    url = ESPN_EVENT_URL.format(event_id=event_id)
    req = Request(url, headers={"User-Agent": "frager/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        return json.loads(raw)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def parse_nfl_result(event: dict | None) -> dict:
    """
    Parse ESPN event. Return dict with:
      - ready: bool
      - reason: str | None
      - home_team, away_team, game_time
      - outcome: 'yes'|'no'|None (meaning the home team won? We'll resolve
        based on winner vs? caller decides; return winner_side by home win)
      - home_won: bool|None
    """
    if not isinstance(event, dict):
        return {"ready": False, "reason": "PARSE_ERROR"}
    competitions = _safe_get(event, "competitions")
    if not isinstance(competitions, list) or not competitions:
        return {"ready": False, "reason": "PARSE_ERROR"}
    comp = competitions[0]
    if not isinstance(comp, dict):
        return {"ready": False, "reason": "PARSE_ERROR"}
    status = comp.get("status") or {}
    if not isinstance(status, dict):
        status = {}
    type_obj = status.get("type") or {}
    if not isinstance(type_obj, dict):
        type_obj = {}
    state = (type_obj.get("state") or "").lower()
    completed = bool(type_obj.get("completed"))
    name = (type_obj.get("name") or "").lower()
    if "postpon" in name or state == "postponed":
        return {"ready": False, "reason": "POSTPONED"}
    if "cancel" in name or state == "cancelled":
        return {"ready": False, "reason": "CANCELLED"}
    if "suspend" in name or "delay" in name:
        return {"ready": False, "reason": "SUSPENDED"}
    if not completed and state != "postgame":
        return {"ready": False, "reason": "GAME_NOT_ENDED"}
    competitors = comp.get("competitors") or []
    if not isinstance(competitors, list) or len(competitors) < 2:
        return {"ready": False, "reason": "PARSE_ERROR"}
    home = None
    away = None
    for c in competitors:
        if not isinstance(c, dict):
            continue
        ha = (c.get("homeAway") or "").lower()
        if ha == "home":
            home = c
        elif ha == "away":
            away = c
    if home is None or away is None:
        # try by order
        home = competitors[0]
        away = competitors[1]
    try:
        home_score = int(home.get("score") or 0)
        away_score = int(away.get("score") or 0)
    except (TypeError, ValueError):
        return {"ready": False, "reason": "PARSE_ERROR"}
    if home_score == away_score:
        return {"ready": False, "reason": "TIE"}
    home_name = ""
    away_name = ""
    for c, name_out in [(home, "home_name"), (away, "away_name")]:
        team = c.get("team") or {}
        if isinstance(team, dict):
            if not home_name and name_out == "home_name":
                home_name = team.get("displayName") or team.get("abbreviation") or ""
            if not away_name and name_out == "away_name":
                away_name = team.get("displayName") or team.get("abbreviation") or ""
    date_str = comp.get("date") or event.get("date")
    game_time = None
    if isinstance(date_str, str):
        try:
            # ESPN typically ISO8601
            if date_str.endswith("Z"):
                game_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                game_time = datetime.fromisoformat(date_str)
            if game_time.tzinfo is None:
                game_time = game_time.replace(tzinfo=timezone.utc)
            else:
                game_time = game_time.astimezone(timezone.utc)
        except Exception:
            game_time = None
    return {
        "ready": True,
        "reason": None,
        "home_team": home_name or None,
        "away_team": away_name or None,
        "game_time": game_time,
        "home_won": home_score > away_score,
        "home_score": home_score,
        "away_score": away_score,
    }
