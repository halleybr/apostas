"""SokkerPro scraper (https://sokkerpro.com).

Uses the public JSON API at https://m2.sokkerpro.com/livescores which returns
today's fixtures with live stats (corners, shots, xG, possession, live odds)
and model predictions per market (``prognosticos``).
"""
from __future__ import annotations

import json

from app.fetch import cached_fetch_json

URL = "https://m2.sokkerpro.com/livescores"
TTL = 10 * 60
HEADERS = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}

LIVE_STATUSES = {"1st", "2nd", "HT", "ET", "PEN", "BT"}


def _to_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _parse_prognosticos(raw) -> dict | None:
    if not raw:
        return None
    try:
        if isinstance(raw, str):
            return json.loads(raw)
        return raw
    except (ValueError, TypeError):
        return None


def scrape(ttl: float | None = None) -> dict:
    doc = cached_fetch_json(URL, ttl if ttl is not None else TTL, headers=HEADERS)
    data = doc.get("data", doc)
    matches: list[dict] = []
    for cat in data.get("sortedCategorizedFixtures", []):
        league = cat.get("leagueName", "")
        country = cat.get("countryName", "")
        for fx in cat.get("fixtures", []):
            m = _fixture(fx, league, country)
            if m:
                matches.append(m)
    return {"matches": matches, "url": URL}


def _fixture(fx: dict, league: str, country: str) -> dict:
    home = fx.get("localTeamName", "")
    away = fx.get("visitorTeamName", "")
    if not home or not away:
        return {}
    status = fx.get("status", "")
    progn = _parse_prognosticos(fx.get("prognosticos"))

    live_odds = {}
    for key in ("XBET_VENCEDOR_HOME", "XBET_VENCEDOR_DRAW", "XBET_VENCEDOR_AWAY",
                "BET365_VENCEDOR_1_LIVE", "BET365_VENCEDOR_X_LIVE", "BET365_VENCEDOR_2_LIVE"):
        val = fx.get(key)
        if val:
            num = str(val).split("#")[0]
            live_odds[key] = _to_float(num)

    return {
        "id": fx.get("fixtureId"),
        "home": home,
        "away": away,
        "league": league or fx.get("leagueName", ""),
        "country": country,
        "status": status,
        "isLive": status in LIVE_STATUSES,
        "minute": fx.get("minute") or "",
        "start_time": fx.get("startingAtDateTime", "").strip('"'),
        "start_timestamp": _to_int(fx.get("startingAtTimestamp")),
        "score_home": _to_int(fx.get("scoresLocalTeam")),
        "score_away": _to_int(fx.get("scoresVisitorTeam")),
        "score_ht_home": _to_int(fx.get("scoresHT").split("-")[0]) if fx.get("scoresHT") else None,
        "corners_home": _to_int(fx.get("localCorners")),
        "corners_away": _to_int(fx.get("visitorCorners")),
        "shots_on_home": _to_int(fx.get("localShotsOnGoal")),
        "shots_on_away": _to_int(fx.get("visitorShotsOnGoal")),
        "shots_total_home": _to_int(fx.get("localShotsTotal")),
        "shots_total_away": _to_int(fx.get("visitorShotsTotal")),
        "dangerous_att_home": _to_int(fx.get("localAttacksDangerousAttacks")),
        "dangerous_att_away": _to_int(fx.get("visitorAttacksDangerousAttacks")),
        "possession_home": _to_int(fx.get("localBallPossession")),
        "possession_away": _to_int(fx.get("visitorBallPossession")),
        "xg_home": _to_float(fx.get("localXg")),
        "xg_away": _to_float(fx.get("visitorXg")),
        "dapm_home": _to_float(fx.get("localDapm5")),
        "dapm_away": _to_float(fx.get("visitorDapm5")),
        "live_odds": live_odds,
        "prognosticos": progn,
        "form_home": fx.get("localTeamSPR"),
        "form_away": fx.get("visitorTeamSLR"),
        "url": f"https://sokkerpro.com/fixture/{fx.get('fixtureId', '')}",
    }
