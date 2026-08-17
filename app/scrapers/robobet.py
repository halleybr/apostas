"""Robobet scraper (https://robobet.app).

The site exposes a public JSON API at https://m.robobet.app/api with:
  - opportunities/picks     : curated bets with probability/confidence/odd
  - opportunities/corners   : corner-pressure opportunities
  - events/today            : today's matches with model forecasts + EV
  - opportunities/scoreboard: historical hit rate / ROI
"""
from __future__ import annotations

from app.fetch import cached_fetch_json

BASE = "https://m.robobet.app/api"
HEADERS = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
TTL = 10 * 60

BLOCK_LABELS = {
    "winner": "Vencedor (dupla chance)",
    "over_15_ft": "Mais de 1.5 gols",
    "over_05_ht": "Mais de 0.5 gols (1º tempo)",
    "btts": "Ambos marcam",
}


def _match_info(item: dict) -> dict:
    league = item.get("league") or {}
    return {
        "id": item.get("id"),
        "home": item.get("home", ""),
        "away": item.get("away", ""),
        "league": league.get("name", ""),
        "start_time": item.get("start_time"),
        "status": item.get("status"),
        "isLive": item.get("isLive", False),
        "time": item.get("time"),
        "scoreHome": item.get("scoreHome"),
        "scoreAway": item.get("scoreAway"),
        "slug": item.get("slug"),
        "odds": item.get("odds") or [],
    }


def scrape(ttl: float | None = None) -> dict:
    """Scrape all Robobet feeds.

    The ``events/today`` feed carries the real-time live state (status, minute,
    score) — its TTL follows the ``ttl`` argument so live consumers can poll it
    as fresh as they need (e.g. 45s), while the curated picks/corners/scoreboard
    feeds keep the default, longer TTL.
    """
    t = ttl if ttl is not None else TTL
    picks_doc = cached_fetch_json(f"{BASE}/opportunities/picks", t, headers=HEADERS)
    corners_doc = cached_fetch_json(f"{BASE}/opportunities/corners", TTL, headers=HEADERS)
    events_doc = cached_fetch_json(f"{BASE}/events/today", t, headers=HEADERS)
    scoreboard_doc = cached_fetch_json(f"{BASE}/opportunities/scoreboard", TTL, headers=HEADERS)

    picks: list[dict] = []
    for block in picks_doc.get("blocks", []):
        key = block.get("key", "")
        for item in block.get("items", []):
            pk = item.get("pick") or {}
            picks.append({
                "match": _match_info(item),
                "block": key,
                "block_label": BLOCK_LABELS.get(key, key),
                "selection": pk.get("selection", ""),
                "probability": pk.get("probability"),
                "confidence": pk.get("confidence"),
                "odd": pk.get("odd"),
                "status": pk.get("status"),      # won/lost/pending
                "state": pk.get("state"),
                "published_at": pk.get("published_at"),
            })

    corners: list[dict] = []
    for item in corners_doc.get("items", []):
        cp = item.get("corner_pressure") or {}
        corners.append({
            "match": _match_info(item),
            "corner_pressure": cp,
        })

    matches: list[dict] = []
    for league in events_doc.get("leagues", []):
        for item in league.get("matches", []):
            m = _match_info(item)
            m["league"] = league.get("name", "")
            m["forecast"] = item.get("forecast_data")
            m["best_suggestion"] = item.get("best_suggestion")
            matches.append(m)

    return {
        "matches": matches,
        "picks": picks,
        "corners": corners,
        "scoreboard": scoreboard_doc.get("scoreboard"),
    }
