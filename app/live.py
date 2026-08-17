"""Live match monitor.

Polls the live feeds — Robobet ``events/today`` is the real-time base for
live matches (status, minute, score), enriched with SokkerPro livescores
stats (corners, shots, xG, possession) — and generates *signals*: goal
alerts, corner runs, over-2.5 pace and live entries from Robobet. Signals
are deduplicated and kept in a rolling list.
"""
from __future__ import annotations

import collections
import datetime
import threading
import time
import uuid

from app.fetch import FetchError
from app.normalize import match_teams
from app.scrapers import robobet, sokkerpro

LIVE_STATUSES = {"1ST", "2ND", "HT", "ET", "PEN", "BT"}

_state_lock = threading.Lock()
_previous: dict[str, dict] = {}          # match key -> goals/corners snapshot
_signals: collections.deque = collections.deque(maxlen=30)
_emitted: set[str] = set()               # dedup keys for change-based signals
_last_refresh: float = 0.0
_last_error: str | None = None


def _signal(kind: str, match: dict, message: str, level: str = "info", meta: dict | None = None, key: str | None = None):
    if key is not None:
        if key in _emitted:
            return
        _emitted.add(key)
        if len(_emitted) > 2000:
            _emitted.clear()
    s = {
        "id": uuid.uuid4().hex[:10],
        "kind": kind,                      # goal | corner | over_pace | attack | entry
        "message": message,
        "level": level,                    # info | alert | hot
        "home": match.get("home", ""),
        "away": match.get("away", ""),
        "league": match.get("league", ""),
        "minute": match.get("minute", ""),
        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if meta:
        s.update(meta)
    _signals.append(s)


def _refresh(min_interval: float = 45.0) -> None:
    global _last_refresh, _last_error
    now = time.time()
    with _state_lock:
        if now - _last_refresh < min_interval:
            return
        _last_refresh = now
    try:
        _do_refresh()
        _last_error = None
    except (FetchError, Exception) as exc:  # noqa: BLE001
        _last_error = str(exc)[:300]


def _parse_live_minute(raw) -> int:
    """Robobet 'time' like "53'", "45+2'" or "HT" -> minute int (0 for specials)."""
    s = str(raw or "").strip()
    if s.endswith("'"):
        s = s[:-1]
    if "+" in s:  # stoppage time
        try:
            a, b = s.split("+", 1)
            return int(a) + int(b)
        except (TypeError, ValueError):
            return 0
    try:
        v = int(s)
        return v if 0 <= v <= 130 else 0
    except (TypeError, ValueError):
        return 0


def _sk_live_list(matches: list[dict]) -> list[dict]:
    """SokkerPro live fixtures reduced to a lightweight stats dict."""
    out = []
    for m in matches:
        if not m.get("isLive"):
            continue
        out.append({
            "home": m.get("home"), "away": m.get("away"), "league": m.get("league"),
            "minute": _parse_live_minute(m.get("minute")),
            "status": m.get("status"),
            "corners": (m.get("corners_home") or 0) + (m.get("corners_away") or 0),
            "corners_home": m.get("corners_home"), "corners_away": m.get("corners_away"),
            "shots_on_home": m.get("shots_on_home"), "shots_on_away": m.get("shots_on_away"),
            "possession_home": m.get("possession_home"), "possession_away": m.get("possession_away"),
            "xg_home": m.get("xg_home"), "xg_away": m.get("xg_away"),
            "dapm_home": m.get("dapm_home"), "dapm_away": m.get("dapm_away"),
            "dangerous_att_home": m.get("dangerous_att_home"), "dangerous_att_away": m.get("dangerous_att_away"),
            "url": m.get("url"),
        })
    return out


def _find_stats(sk_live: list[dict], home: str, away: str) -> dict | None:
    """Best SokkerPro stats match for a Robobet live match (fuzzy team names)."""
    for s in sk_live:
        if match_teams(s["home"], s["away"], home, away):
            return s
    return None


def _do_refresh() -> None:
    """Refresh live state. Robobet (events/today) is the real-time base for
    status/minute/score; SokkerPro enriches corners/shots/xG/possession stats."""
    global _previous
    rb = robobet.scrape(ttl=45)
    sk = sokkerpro.scrape(ttl=45)
    sk_live = _sk_live_list(sk.get("matches"))
    state: dict[str, dict] = {}

    for m in rb.get("matches", []):
        if not m.get("isLive"):
            continue
        minute = _parse_live_minute(m.get("time") or m.get("minute"))
        home, away = m.get("home", ""), m.get("away", "")
        key = f"{home}|{away}"
        sh = m.get("scoreHome") or 0
        sa = m.get("scoreAway") or 0
        goals = sh + sa
        stats = _find_stats(sk_live, home, away) or {}
        entry = {
            "key": key,
            "home": home, "away": away,
            "league": m.get("league") or stats.get("league") or "",
            "minute": minute,
            "status": (m.get("status") or "live").upper(),
            "isLive": True,
            "goals": goals,
            "score_home": sh, "score_away": sa,
            "corners": stats.get("corners"),
            "dapm": {"home": stats.get("dapm_home"), "away": stats.get("dapm_away")},
        }
        prev = _previous.get(key)
        state[key] = entry
        if minute <= 0:
            continue
        if prev and prev.get("goals") is not None:
            if goals > prev["goals"]:
                _signal("goal", entry,
                        f"⚽ GOL! {home} {sh} x {sa} {away} ({minute}')",
                        level="alert", meta={"score_home": sh, "score_away": sa},
                        key=f"goal:{key}:{goals}")
        if prev and prev.get("corners") is not None and entry["corners"] is not None:
            if entry["corners"] > prev["corners"] and entry["corners"] >= 2:
                rate = round(entry["corners"] / max(1, minute) * 90, 1)
                _signal("corner", entry,
                        f"🚩 Escanteio! Total de {entry['corners']} (ritmo de {rate}/jogo) — {home} x {away} ({minute}')",
                        level="info", meta={"corners": entry["corners"]},
                        key=f"corner:{key}:{entry['corners']}")
        # over 2.5 pace
        if minute >= 20 and goals >= 1:
            projected = goals * 90.0 / minute
            if projected >= 2.6:
                _signal("over_pace", entry,
                        f"📈 Projeção de {projected:.1f} gols no jogo — over 2.5 no caminho ({goals} gols em {minute}')",
                        level="info", meta={"projected": round(projected, 1)},
                        key=f"over:{key}:{goals}")
        # attack pace (from sokkerpro stats)
        for side, team in (("home", home), ("away", away)):
            dapm = entry["dapm"].get(side)
            if dapm is not None and dapm >= 1.0:
                _signal("attack", entry,
                        f"🔥 {team} com ritmo forte ({dapm:.1f} ataques perigosos/min) — {home} x {away} ({minute}')",
                        level="hot" if dapm >= 1.5 else "info",
                        key=f"attack:{key}:{side}:{int(dapm * 2)}")

    # robobet live entries
    for pick in rb.get("picks", []):
        if not pick.get("match", {}).get("isLive"):
            continue
        m = pick["match"]
        pick_key = f"entry:{m.get('id')}:{pick['block']}:{pick['selection']}"
        _signal("entry", m,
                f"🎯 Entrada ao vivo ({pick['block_label']}): {pick['selection']} @ {pick['odd']} — prob. {pick.get('probability', 0):.0f}%",
                level="hot", meta={"odd": pick.get("odd"), "prob": pick.get("probability")},
                key=pick_key)

    # robobet corner pressure on live matches
    for c in rb.get("corners", []):
        if not c.get("match", {}).get("isLive"):
            continue
        cp = c.get("corner_pressure") or {}
        if cp.get("best_value", 0) >= 70:
            m = c["match"]
            _signal("corner_pressure", m,
                    f"🚩 Pressão de escanteios alta ({cp.get('best_value')}% no {cp.get('best_period')}) — {m['home']} x {m['away']}",
                    level="hot", meta={"pressure": cp.get("best_value")},
                    key=f"cp:{m.get('id')}")

    _previous = state


def get_live() -> dict:
    _refresh()
    with _state_lock:
        signals = list(_signals)
        error = _last_error
    # surface current live matches: Robobet is the base, sokkerpro adds stats
    try:
        rb = robobet.scrape(ttl=45)
        sk = sokkerpro.scrape(ttl=45)
        sk_live = _sk_live_list(sk.get("matches"))
        live = []
        for m in rb.get("matches", []):
            if not m.get("isLive"):
                continue
            st = _find_stats(sk_live, m.get("home"), m.get("away")) or {}
            minute = _parse_live_minute(m.get("time") or m.get("minute"))
            live.append({
                "home": m.get("home"), "away": m.get("away"),
                "league": m.get("league") or st.get("league") or "",
                "minute": minute or m.get("time") or "",
                "status": m.get("status"),
                "isLive": True,
                "score_home": m.get("scoreHome"), "score_away": m.get("scoreAway"),
                "corners_home": st.get("corners_home"), "corners_away": st.get("corners_away"),
                "shots_on_home": st.get("shots_on_home"), "shots_on_away": st.get("shots_on_away"),
                "possession_home": st.get("possession_home"), "possession_away": st.get("possession_away"),
                "xg_home": st.get("xg_home"), "xg_away": st.get("xg_away"),
                "dapm_home": st.get("dapm_home"), "dapm_away": st.get("dapm_away"),
                "url": st.get("url"),
            })
        live.sort(key=lambda m: _parse_live_minute(m.get("minute")), reverse=True)
    except (FetchError, Exception):  # noqa: BLE001
        live = []
    return {
        "live_matches": live,
        "signals": signals[-24:],
        "error": error,
        "refreshed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
