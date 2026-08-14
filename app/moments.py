"""Melhores do momento — live match analysis for in-play betting ideas.

Polls the SokkerPro live feed and ranks matches by "agitation" (pressure,
shots, corners, goals pace). For the most agitated matches it generates
moment tips like "mais 1 escanteio até o fim" or "mais 1 gol no jogo",
with a heuristic probability derived from live pace and xG.
"""
from __future__ import annotations

import datetime
import threading

from app.scrapers import sokkerpro
from app.fetch import FetchError

MINUTE_LIMIT = 88          # still enough time left to matter
MIN_MINUTE = 12            # too early: data is noise
MIN_CORNERS = 5            # minimum total corners to talk about corner lines
MIN_SHOTS = 8              # minimum total shots to call a match "agitado"
CORNER_PACE_HOT = 9.5      # corners/90min projection considered high
CORNER_PACE_HIGH = 7.5
GOAL_PACE_HOT = 2.5
GOAL_PACE_HIGH = 1.9
XG_REMAINING_HOT = 0.55    # combined xG still on the board (per half remaining)
XG_REMAINING_HIGH = 0.35

_lock = threading.Lock()
_cache: dict[str, object] = {}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _minute(m) -> int:
    return _i(m.get("minute"))


def _pace(value: float, minute: int, span: int = 90) -> float:
    if minute <= 0:
        return 0.0
    return value / minute * span


def _agitation_score(m: dict, minute: int) -> dict:
    """Score how 'agitado' a match is right now (0..100)."""
    shots = _i(m.get("shots_total_home")) + _i(m.get("shots_total_away"))
    shots_on = _i(m.get("shots_on_home")) + _i(m.get("shots_on_away"))
    corners = _i(m.get("corners_home")) + _i(m.get("corners_away"))
    da = _f(m.get("dangerous_att_home")) + _f(m.get("dangerous_att_away"))
    xg = _f(m.get("xg_home")) + _f(m.get("xg_away"))
    goals = _i(m.get("score_home")) + _i(m.get("score_away"))

    parts = {
        "pressao": min(100, da / max(1, minute) * 8.0),          # dangerous attacks/min
        "chutes": min(100, shots / max(1, minute) * 45.0),
        "chutes_no_gol": min(100, shots_on / max(1, minute) * 60.0),
        "escanteios": min(100, corners / max(1, minute) * 42.0),
        "gols": min(100, goals / max(1, minute) * 70.0),
        "xg": min(100, xg / max(1, minute) * 55.0),
    }
    # weighted: pressure and shots matter most, corners and goals next
    score = (
        parts["pressao"] * 0.22
        + parts["chutes"] * 0.22
        + parts["chutes_no_gol"] * 0.18
        + parts["escanteios"] * 0.16
        + parts["gols"] * 0.12
        + parts["xg"] * 0.10
    )
    return {"score": round(score, 1), "parts": parts}


def _corner_tips(m: dict, minute: int) -> list[dict]:
    tips = []
    c = _i(m.get("corners_home")) + _i(m.get("corners_away"))
    if c < MIN_CORNERS or minute > MINUTE_LIMIT:
        return tips
    corner_pace = _pace(c, minute)
    remaining = max(1, 90 - minute)
    expected_more = corner_pace / 90.0 * remaining
    if corner_pace >= CORNER_PACE_HOT and expected_more >= 1.2:
        prob = min(88, 62 + (corner_pace - CORNER_PACE_HOT) * 6)
        tips.append({
            "tipo": "escanteio",
            "dica": f"Mais 1 escanteio até o fim ({c} agora, ritmo de {corner_pace:.1f}/jogo)",
            "odd_sugerida": round(100 / max(55, prob), 2),
            "probabilidade": round(prob),
            "nivel": "🔥 Quente",
            "base": f"{c} escanteios em {minute}' · projeção de {corner_pace:.1f} no jogo",
        })
    elif corner_pace >= CORNER_PACE_HIGH and expected_more >= 1.0:
        prob = min(80, 56 + (corner_pace - CORNER_PACE_HIGH) * 5)
        tips.append({
            "tipo": "escanteio",
            "dica": f"Mais 1 escanteio até o fim ({c} agora, ritmo de {corner_pace:.1f}/jogo)",
            "odd_sugerida": round(100 / max(52, prob), 2),
            "probabilidade": round(prob),
            "nivel": "📈 Em alta",
            "base": f"{c} escanteios em {minute}' · projeção de {corner_pace:.1f} no jogo",
        })
    return tips


def _goal_tips(m: dict, minute: int) -> list[dict]:
    tips = []
    if minute > MINUTE_LIMIT:
        return tips
    goals = _i(m.get("score_home")) + _i(m.get("score_away"))
    shots_on = _i(m.get("shots_on_home")) + _i(m.get("shots_on_away"))
    goal_pace = _pace(goals, minute)
    shots_pace = _pace(shots_on, minute)
    xg = _f(m.get("xg_home")) + _f(m.get("xg_away"))
    remaining = max(1, 90 - minute)
    xg_remaining = xg / max(1, minute) * remaining

    # "mais 1 gol" — pace-based
    expected_goals = goal_pace / 90.0 * remaining
    if (goal_pace >= GOAL_PACE_HOT and expected_goals >= 0.9) or (goal_pace >= 1.5 and expected_goals >= 1.1):
        prob = min(85, 60 + (goal_pace - GOAL_PACE_HOT) * 8 + min(8, shots_on / max(1, minute) * 2))
        tips.append({
            "tipo": "gol",
            "dica": "Mais 1 gol no jogo (ritmo forte de gols e finalizações)",
            "odd_sugerida": round(100 / max(55, prob), 2),
            "probabilidade": round(prob),
            "nivel": "🔥 Quente",
            "base": f"{goals} gol(ns) em {minute}' · ritmo de {goal_pace:.1f}/jogo · {shots_on} chutes no gol",
        })
    # xG-based
    elif xg_remaining >= XG_REMAINING_HOT and shots_pace >= 8:
        prob = min(82, 58 + (xg_remaining - XG_REMAINING_HOT) * 25)
        tips.append({
            "tipo": "gol",
            "dica": "Mais 1 gol no jogo (xG alto acumulado e pressão mantida)",
            "odd_sugerida": round(100 / max(52, prob), 2),
            "probabilidade": round(prob),
            "nivel": "📈 Em alta",
            "base": f"xG {xg:.2f} em {minute}' · projeção restante {xg_remaining:.2f} · {shots_on} chutes no gol",
        })
    return tips


def _btts_tip(m: dict, minute: int) -> list[dict]:
    tips = []
    if minute > MINUTE_LIMIT:
        return tips
    sh, sa = _i(m.get("score_home")), _i(m.get("score_away"))
    if sh >= 1 and sa >= 1:
        return tips  # already BTTS
    xg_h, xg_a = _f(m.get("xg_home")), _f(m.get("xg_away"))
    shots_h = _i(m.get("shots_on_home")) + _i(m.get("shots_on_away"))
    remaining = max(1, 90 - minute)
    xg_h_rem = xg_h / max(1, minute) * remaining
    xg_a_rem = xg_a / max(1, minute) * remaining
    # both teams threatening + the trailing side has real xG left
    if xg_h_rem >= 0.18 and xg_a_rem >= 0.18 and shots_h >= 7 and minute >= 25:
        prob = min(78, 55 + (min(xg_h_rem, xg_a_rem) - 0.18) * 60)
        tips.append({
            "tipo": "btts",
            "dica": "Ambos marcam no jogo (os dois times com xG vivo e finalizações)",
            "odd_sugerida": round(100 / max(50, prob), 2),
            "probabilidade": round(prob),
            "nivel": "📈 Em alta",
            "base": f"xG restante casa {xg_h_rem:.2f} · fora {xg_a_rem:.2f} · {shots_h} chutes no gol",
        })
    return tips


def _totals_tip(m: dict, minute: int) -> list[dict]:
    tips = []
    if minute > MINUTE_LIMIT:
        return tips
    goals = _i(m.get("score_home")) + _i(m.get("score_away"))
    if goals >= 3:
        return tips
    xg = _f(m.get("xg_home")) + _f(m.get("xg_away"))
    shots = _i(m.get("shots_total_home")) + _i(m.get("shots_total_away"))
    remaining = max(1, 90 - minute)
    xg_rem = xg / max(1, minute) * remaining
    # over 2.5 still alive + strong output
    if xg_rem >= 0.45 and shots >= 10 and minute >= 30:
        prob = min(75, 55 + (xg_rem - 0.45) * 30)
        tips.append({
            "tipo": "total",
            "dica": "Total de gols over 2.5 (jogo aberto com xG restante alto)",
            "odd_sugerida": round(100 / max(48, prob), 2),
            "probabilidade": round(prob),
            "nivel": "📈 Em alta",
            "base": f"{goals} gol(ns) agora · xG restante {xg_rem:.2f} · {shots} chutes",
        })
    return tips


def get_moments(ttl: float = 45.0) -> dict:
    """Return ranked 'melhores do momento': agitated live games + moment tips."""
    now = datetime.datetime.now(datetime.timezone.utc)
    with _lock:
        cached = _cache.get("moments")
        if cached and isinstance(cached, tuple):
            ts, value = cached
            if (now - ts).total_seconds() < ttl:
                return value

    try:
        sk = sokkerpro.scrape(ttl=ttl)
        live = [m for m in sk.get("matches", []) if m.get("isLive")]
    except (FetchError, Exception) as exc:  # noqa: BLE001
        value = {"games": [], "error": str(exc)[:200], "refreshed_at": now.isoformat()}
        with _lock:
            _cache["moments"] = (now, value)
        return value

    games = []
    for m in live:
        minute = _minute(m)
        if minute < MIN_MINUTE or minute > MINUTE_LIMIT + 12:
            continue
        m = dict(m)  # normalize types for the output
        m["minute"] = minute
        shots = _i(m.get("shots_total_home")) + _i(m.get("shots_total_away"))
        corners = _i(m.get("corners_home")) + _i(m.get("corners_away"))
        if shots < MIN_SHOTS and corners < MIN_CORNERS:
            continue

        agg = _agitation_score(m, minute)
        tips = []
        tips += _corner_tips(m, minute)
        tips += _goal_tips(m, minute)
        tips += _btts_tip(m, minute)
        tips += _totals_tip(m, minute)
        tips.sort(key=lambda t: -t["probabilidade"])

        games.append({
            "home": m["home"],
            "away": m["away"],
            "league": m.get("league") or "",
            "minute": minute,
            "status": m.get("status"),
            "score_home": _i(m.get("score_home")),
            "score_away": _i(m.get("score_away")),
            "corners": {"home": _i(m.get("corners_home")), "away": _i(m.get("corners_away"))},
            "shots_on": {"home": _i(m.get("shots_on_home")), "away": _i(m.get("shots_on_away"))},
            "shots_total": {"home": _i(m.get("shots_total_home")), "away": _i(m.get("shots_total_away"))},
            "possession": {"home": _i(m.get("possession_home")), "away": _i(m.get("possession_away"))},
            "xg": {"home": round(_f(m.get("xg_home")), 2), "away": round(_f(m.get("xg_away")), 2)},
            "pressao": {"home": _i(m.get("dangerous_att_home")), "away": _i(m.get("dangerous_att_away"))},
            "agitation": agg,
            "url": m.get("url") or f"https://sokkerpro.com/fixture/{m.get('id', '')}",
            "tips": tips,
        })

    games.sort(key=lambda g: -g["agitation"]["score"])
    value = {
        "games": games,
        "error": None,
        "refreshed_at": now.isoformat(),
    }
    with _lock:
        _cache["moments"] = (now, value)
    return value
