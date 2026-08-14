"""Live match monitor.

Polls the live feeds (SokkerPro livescores + Robobet picks/corners) and
generates *signals* — goal alerts, corner runs, over-2.5 pace and live
entries from Robobet. Signals are deduplicated and kept in a rolling list.
"""
from __future__ import annotations

import collections
import datetime
import threading
import time
import uuid

from app.scrapers import robobet, sokkerpro
from app.fetch import FetchError

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


def _do_refresh() -> None:
    global _previous
    sk = sokkerpro.scrape(ttl=45)
    rb = robobet.scrape(ttl=45)
    state: dict[str, dict] = {}
    now_min = _to_min(sk.get("matches"))

    for m in now_min:
        key = m["key"]
        prev = _previous.get(key)
        state[key] = {
            "goals": m["goals"],
            "corners": m["corners"],
            "minute": m["minute"],
            "status": m["status"],
        }
        if not m["isLive"] or m["minute"] <= 0:
            continue
        if prev and prev.get("goals") is not None:
            if m["goals"] > prev["goals"]:
                _signal("goal", m,
                        f"⚽ GOL! {m['home']} {m['score_home']} x {m['score_away']} {m['away']} ({m['minute']}')",
                        level="alert", meta={"score_home": m["score_home"], "score_away": m["score_away"]},
                        key=f"goal:{key}:{m['goals']}")
        if prev and prev.get("corners") is not None:
            if m["corners"] > prev["corners"] and m["corners"] >= 2:
                rate = round(m["corners"] / max(1, m["minute"]) * 90, 1)
                _signal("corner", m,
                        f"🚩 Escanteio! Total de {m['corners']} (ritmo de {rate}/jogo) — {m['home']} x {m['away']} ({m['minute']}')",
                        level="info", meta={"corners": m["corners"]},
                        key=f"corner:{key}:{m['corners']}")
        # over 2.5 pace
        if m["minute"] >= 20 and m["goals"] >= 1:
            projected = m["goals"] * 90.0 / m["minute"]
            if projected >= 2.6:
                _signal("over_pace", m,
                        f"📈 Projeção de {projected:.1f} gols no jogo — over 2.5 no caminho ({m['goals']} gols em {m['minute']}')",
                        level="info", meta={"projected": round(projected, 1)},
                        key=f"over:{key}:{m['goals']}")
        # attack pace
        for side, team in (("home", m["home"]), ("away", m["away"])):
            dapm = m.get("dapm", {}).get(side)
            if dapm is not None and dapm >= 1.0:
                _signal("attack", m,
                        f"🔥 {team} com ritmo forte ({dapm:.1f} ataques perigosos/min) — {m['home']} x {m['away']} ({m['minute']}')",
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


def _to_min(matches: list[dict]) -> list[dict]:
    out = []
    for m in matches:
        sh = m.get("score_home") or 0
        sa = m.get("score_away") or 0
        ch = m.get("corners_home") or 0
        ca = m.get("corners_away") or 0
        minute = _parse_minute(m.get("minute"))
        out.append({
            "key": f"{m.get('home')}|{m.get('away')}",
            "home": m.get("home"),
            "away": m.get("away"),
            "league": m.get("league"),
            "minute": minute,
            "goals": sh + sa,
            "corners": ch + ca,
            "score_home": sh,
            "score_away": sa,
            "dapm": {"home": m.get("dapm_home"), "away": m.get("dapm_away")},
            "status": (m.get("status") or "").upper(),
            "isLive": m.get("isLive", False),
        })
    return out


def _parse_minute(raw) -> int:
    try:
        val = int(str(raw).strip())
        if 0 <= val <= 130:
            return val
    except (TypeError, ValueError):
        pass
    return 0


def get_live() -> dict:
    _refresh()
    with _state_lock:
        signals = list(_signals)
        error = _last_error
    # surface current live matches from the last sokkerpro snapshot (cached)
    try:
        sk = sokkerpro.scrape(ttl=45)
        live = [
            {
                "home": m["home"], "away": m["away"], "league": m["league"],
                "minute": m.get("minute"), "status": m.get("status"),
                "score_home": m.get("score_home"), "score_away": m.get("score_away"),
                "corners_home": m.get("corners_home"), "corners_away": m.get("corners_away"),
                "shots_on_home": m.get("shots_on_home"), "shots_on_away": m.get("shots_on_away"),
                "possession_home": m.get("possession_home"), "possession_away": m.get("possession_away"),
                "xg_home": m.get("xg_home"), "xg_away": m.get("xg_away"),
                "dapm_home": m.get("dapm_home"), "dapm_away": m.get("dapm_away"),
                "url": m.get("url"),
            }
            for m in sk.get("matches", []) if m.get("isLive")
        ]
        live.sort(key=lambda m: int(str(m.get("minute") or 0) or 0), reverse=True)
    except (FetchError, Exception):  # noqa: BLE001
        live = []
    return {
        "live_matches": live,
        "signals": signals[-24:],
        "error": error,
        "refreshed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
