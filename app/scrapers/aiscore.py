"""AiScore scraper (https://www.aiscore.com) — best effort.

AiScore's API (api.aiscore.com) returns protobuf with obfuscated ids, which is
not worth reverse-engineering for this project. We expose the live/odds
deep-links and, when the endpoint answers with usable JSON, a light match list.
"""
from __future__ import annotations

import json

from app.fetch import fetch_json, FetchError

URL = "https://www.aiscore.com/"
TTL = 20 * 60

LINKS = {
    "Futebol (hoje)": "https://www.aiscore.com/football",
    "Placar ao vivo": "https://www.aiscore.com/live-scores",
    "Resultados de hoje": "https://www.aiscore.com/football-results",
    "Previsões": "https://www.aiscore.com/predictions",
}


def scrape() -> dict:
    out = {
        "status": "parcial",
        "matches": [],
        "links": LINKS,
        "url": URL,
        "note": (
            "A API do AiScore usa protobuf com IDs ofuscados (anti-bot). "
            "O site exibe os links oficiais de placar ao vivo e previsões. "
            "Os dados ao vivo vêm do SokkerPro e Robobet."
        ),
    }
    # try the JSON endpoint once; if it answers with JSON use it, else degrade
    try:
        doc = fetch_json(
            "https://api.aiscore.com/v1/web/api/today/matches?sid=1&tz=America/Sao_Paulo&lang=1",
            headers={"Accept": "application/json"},
        )
        matches = _normalize(doc)
        if matches:
            out["matches"] = matches
            out["status"] = "ok"
            out.pop("note", None)
    except (FetchError, ValueError, KeyError):
        pass
    return out


def _normalize(doc: dict) -> list[dict]:
    out = []
    for comp in doc.get("data", {}).get("league", []) or doc.get("data", {}).get("list", []) or []:
        league = comp.get("name") or comp.get("league_name") or ""
        for m in comp.get("matches", []) or comp.get("list", []) or []:
            out.append({
                "home": m.get("home_team") or m.get("home_name") or "",
                "away": m.get("away_team") or m.get("away_name") or "",
                "league": league,
                "status": m.get("status") or m.get("status_name") or "",
                "start_time": m.get("start_time") or m.get("match_time") or "",
                "score_home": m.get("home_score"),
                "score_away": m.get("away_score"),
            })
    return out
