"""Aggregator — merge all scrapers into unified matches with selections.

Each match ends up with a set of *selections* (e.g. "1", "over25", "btts_yes")
gathered from every source that has an opinion. Every selection carries:
  - odds      : list of prices found across sources
  - best_odd  : lowest (best) price
  - prob      : average model probability across sources (0..1)
  - agreement : share of sources that hold this selection among those with data
  - reliability : 0..1 combined score used to rank accumulator legs
"""
from __future__ import annotations

import concurrent.futures
import datetime
import threading

from app.normalize import match_teams, normalize_name
from app.scrapers import (
    aiscore,
    bettingexpert,
    betrush,
    oddsscanner,
    predictz,
    robobet,
    sokkerpro,
    windrawwin,
)
from app.fetch import FetchError

# canonical selection codes and their pt-BR labels
SEL_LABELS = {
    "1": "Vitória do mandante",
    "X": "Empate",
    "2": "Vitória do visitante",
    "12": "Dupla chance: casa ou fora",
    "1X": "Dupla chance: casa ou empate",
    "X2": "Dupla chance: fora ou empate",
    "over05": "Mais de 0.5 gol",
    "over15": "Mais de 1.5 gols",
    "over25": "Mais de 2.5 gols",
    "under25": "Menos de 2.5 gols",
    "ht_over05": "Mais de 0.5 gol (1º tempo)",
    "ht_over15": "Mais de 1.5 gols (1º tempo)",
    "btts_yes": "Ambos marcam: sim",
    "btts_no": "Ambos marcam: não",
    "over35": "Mais de 3.5 gols",
    "corners_over": "Escanteios (over)",
}

# map each source's raw market key -> canonical selection code
ROB_WINNER = {"1": "1", "X": "X", "2": "2", "12": "12", "1X": "1X", "X2": "X2"}
ROB_DC = {"1X": "1X", "X2": "X2", "12": "12"}
ROB_OVER = {
    "over_05_ft": "over05",
    "over_15_ft": "over15",
    "over_25_ft": "over25",
    "over_35_ft": None,  # not in our vocabulary yet
    "over_05_ht": "ht_over05",
}
WW_TYPE = {"MH": "1", "MD": "X", "MA": "2", "GO": "over25", "GU": "under25", "YS": "btts_yes", "NS": "btts_no"}

LOCK = threading.Lock()


def _run_scrapers():
    """Run all scrapers in parallel; return {name: payload} with errors captured."""
    jobs = {
        "robobet": robobet.scrape,
        "sokkerpro": sokkerpro.scrape,
        "windrawwin": windrawwin.scrape,
        "bettingexpert": bettingexpert.scrape,
        "aiscore": aiscore.scrape,
        "predictz": predictz.scrape,
        "betrush": lambda: betrush.scrape("betrush"),
        "tipgol": lambda: betrush.scrape("tipgol"),
        "oddsscanner": oddsscanner.scrape,
    }
    results: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=9) as ex:
        futs = {name: ex.submit(fn) for name, fn in jobs.items()}
        for name, fut in futs.items():
            try:
                results[name] = fut.result()
            except (FetchError, Exception) as exc:  # noqa: BLE001
                results[name] = {"status": "error", "error": str(exc)[:300]}
    return results


# --------------------------------------------------------------------------
# selection collection
# --------------------------------------------------------------------------
class Selection:
    __slots__ = ("code", "odds", "probs", "agrees", "sources", "is_pick", "extra")

    def __init__(self, code: str):
        self.code = code
        self.odds: list[float] = []
        self.probs: list[float] = []
        self.agrees: int = 0
        self.sources: list[str] = []
        self.is_pick = False
        self.extra: list[str] = []

    def add(self, source: str, odd=None, prob=None, agree=True, pick=False, extra=None):
        if odd is not None:
            self.odds.append(round(float(odd), 2))
        if prob is not None:
            self.probs.append(float(prob))
        if agree and source not in self.sources:
            self.agrees += 1
        if source not in self.sources:
            self.sources.append(source)
        if pick:
            self.is_pick = True
        if extra:
            self.extra.append(extra)

    def to_dict(self):
        prob = sum(self.probs) / len(self.probs) if self.probs else None
        if prob is None and self.odds:
            prob = min(0.9, max(0.05, 1.0 / min(self.odds) * 0.95))
        best_odd = min(self.odds) if self.odds else None
        n_with_data = max(1, self.agrees)
        agreement = round(min(1.0, self.agrees / 3.0), 2)
        rel = 0.0
        if prob is not None:
            rel = prob * (0.55 + 0.45 * agreement)
            if self.is_pick:
                rel = min(0.99, rel * 1.03)
        return {
            "code": self.code,
            "label": SEL_LABELS.get(self.code, self.code),
            "odds": sorted(set(self.odds)),
            "best_odd": best_odd,
            "prob": round(prob, 4) if prob is not None else None,
            "prob_pct": round(prob * 100) if prob is not None else None,
            "agreement": agreement,
            "sources": self.sources,
            "is_pick": self.is_pick,
            "reliability": round(rel, 4),
            "extra": self.extra[:4],
        }


class MatchBuilder:
    def __init__(self, home: str, away: str, league: str):
        self.home = home
        self.away = away
        self.league = league
        self.key = f"{normalize_name(home)}|{normalize_name(away)}"
        self.selections: dict[str, Selection] = {}
        self.start_time: str | None = None
        self.status: str | None = None
        self.isLive = False
        self.scores: dict = {}
        self.live: dict = {}
        self.url: str | None = None
        self.bet365_url: str | None = None
        self.ww_tip_url: str | None = None
        self.sources_present: set[str] = set()

    def sel(self, code: str) -> Selection:
        if code not in self.selections:
            self.selections[code] = Selection(code)
        return self.selections[code]

    def to_dict(self) -> dict | None:
        if not self.selections:
            return None
        sels = [s.to_dict() for s in self.selections.values()]
        sels.sort(key=lambda s: s["reliability"], reverse=True)
        return {
            "key": self.key,
            "home": self.home,
            "away": self.away,
            "league": self.league,
            "start_time": self.start_time,
            "status": self.status,
            "isLive": self.isLive,
            "scores": self.scores,
            "live": self.live,
            "url": self.url,
            "bet365_url": self.bet365_url,
            "ww_tip_url": self.ww_tip_url,
            "sources": sorted(self.sources_present),
            "selections": sels,
        }


FINISHED_STATUSES = {"finished", "ft", "aet", "pen", "cancelled", "canceled", "postponed", "abandoned"}


def _parse_live_minute(raw) -> int | None:
    """robobet exposes the live minute as a string like '86'' (trailing quote)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s.endswith("'"):
        s = s[:-1]
    if "+" in s:  # stoppage time, e.g. "45+2'"
        try:
            a, b = s.split("+", 1)
            v = int(a) + int(b)
            return v if 0 <= v <= 130 else None
        except (TypeError, ValueError):
            return None
    try:
        v = int(s)
        return v if 0 <= v <= 130 else None
    except (TypeError, ValueError):
        return None


def _merge_into(match: MatchBuilder, match_obj: dict, source: str, key: str) -> None:
    """Fold a source match into the builder, filling identity + live info."""
    match.sources_present.add(source)
    if not match.start_time and match_obj.get("start_time"):
        match.start_time = match_obj["start_time"]
    if not match.status and match_obj.get("status"):
        match.status = match_obj["status"]
    # robobet 'finished' -> canonical FT
    if str(match_obj.get("status") or "").lower() in FINISHED_STATUSES:
        match.status = "FT"
        match.isLive = False
    if match_obj.get("isLive"):
        match.isLive = True
    if "minute" not in match.live and source == "robobet":
        minute = _parse_live_minute(match_obj.get("time"))
        if minute:
            match.live["minute"] = minute
    if match_obj.get("time") and str(match_obj.get("time")).upper() in ("FT", "AET", "PEN"):
        match.status = str(match_obj.get("time")).upper()
        match.isLive = False
    if not match.scores:
        sh, sa = match_obj.get("score_home"), match_obj.get("score_away")
        if sh is None:
            sh = match_obj.get("scoreHome")
        if sa is None:
            sa = match_obj.get("scoreAway")
        if sh is not None and sa is not None:
            match.scores = {"home": sh, "away": sa}
    if not match.url and match_obj.get("url"):
        match.url = match_obj["url"]


def _add_robobet(match: MatchBuilder, rb: dict, key: str) -> None:
    _merge_into(match, rb, "robobet", key)
    f = rb.get("forecast") or {}
    markets = f.get("markets") or {}
    for sel_code, data in (markets.get("winner") or {}).items():
        code = ROB_WINNER.get(str(sel_code))
        if code:
            match.sel(code).add("robobet", odd=data.get("market_odd"), prob=(data.get("probability") or 0) / 100, extra=f"EV {data.get('ev')}%")
    for sel_code, data in (markets.get("double_chance") or {}).items():
        code = ROB_DC.get(str(sel_code))
        if code:
            match.sel(code).add("robobet", odd=data.get("market_odd"), prob=(data.get("probability") or 0) / 100)
    for sel_code, data in (markets.get("over_goals") or {}).items():
        code = ROB_OVER.get(str(sel_code))
        if code:
            match.sel(code).add("robobet", odd=data.get("market_odd"), prob=(data.get("probability") or 0) / 100)
    for sel_code, data in (markets.get("btts") or {}).items():
        code = "btts_yes" if str(sel_code).lower() == "yes" else ("btts_no" if str(sel_code).lower() == "no" else None)
        if code:
            match.sel(code).add("robobet", odd=data.get("market_odd"), prob=(data.get("probability") or 0) / 100)
    bs = rb.get("best_suggestion")
    if isinstance(bs, dict):
        for sel_code, data in (bs.get("markets") or {}).items():
            code = ROB_WINNER.get(str(sel_code))
            if code:
                match.sel(code).add("robobet", odd=data.get("market_odd"), prob=(data.get("probability") or 0) / 100, pick=True)


def _add_robobet_pick(match: MatchBuilder, pick: dict, key: str) -> None:
    block = pick.get("block", "")
    raw = str(pick.get("selection", "")).lower()
    prob = (pick.get("probability") or 0) / 100
    odd = pick.get("odd")
    conf = pick.get("confidence")
    code = None
    if block == "winner":
        code = raw.upper()
    elif block == "over_15_ft" and raw == "over":
        code = "over15"
    elif block == "over_05_ht" and raw == "over":
        code = "ht_over05"
    elif block == "btts" and raw == "yes":
        code = "btts_yes"
    if code:
        s = match.sel(code)
        s.add("robobet", odd=odd, prob=prob, pick=True, extra=f"confiança {conf}%" if conf else None)


def _add_robobet_corner(match: MatchBuilder, corner: dict, key: str) -> None:
    cp = corner.get("corner_pressure") or {}
    if cp:
        match.live["corner_pressure"] = cp
        match.sources_present.add("robobet_corners")


def _add_sokkerpro(match: MatchBuilder, sk: dict, key: str) -> None:
    _merge_into(match, sk, "sokkerpro", key)
    progn = sk.get("prognosticos") or {}
    m1x2 = progn.get("mercado_1x2") or {}
    for pt, code in (("casa_vencer", "1"), ("empate", "X"), ("fora_vencer", "2")):
        d = m1x2.get(pt)
        if d:
            match.sel(code).add("sokkerpro", odd=d.get("odd"), prob=(d.get("probabilidade") or 0) / 100)
    for pt, code in (("casa_ou_empate", "1X"), ("fora_ou_empate", "X2"), ("casa_ou_fora", "12")):
        d = m1x2.get(pt)
        if d:
            match.sel(code).add("sokkerpro", prob=(d.get("probabilidade") or 0) / 100)
    # NB: sokkerpro's ``value`` field in goal markets is NOT a bookable odd
    # (it is constant across lines) — only use ``res`` (probability).
    mg = progn.get("mercado_gols") or {}
    for pt, code in (("over_0_5", "over05"), ("over_1_5", "over15"), ("over_2_5", "over25"), ("over_3_5", "over35")):
        d = mg.get(pt)
        if d:
            match.sel(code).add("sokkerpro", prob=(d.get("res") or 0) / 100,
                               extra=f"média {d.get('detalhes', {}).get('media_casa')}/{d.get('detalhes', {}).get('media_fora')}")
    mht = progn.get("mercado_gols_primeiro_tempo") or {}
    for pt, code in (("over_0_5", "ht_over05"), ("over_1_5", "ht_over15")):
        d = mht.get(pt)
        if d:
            match.sel(code).add("sokkerpro", prob=(d.get("res") or 0) / 100)
    mb = progn.get("mercado_ambos_marcam") or {}
    bsim, bnao = mb.get("ambos_sim"), mb.get("ambos_nao")
    if bsim:
        match.sel("btts_yes").add("sokkerpro", odd=bsim.get("odd"), prob=(bsim.get("probabilidade") or 0) / 100)
    if bnao:
        match.sel("btts_no").add("sokkerpro", odd=bnao.get("odd"), prob=(bnao.get("probabilidade") or 0) / 100)
    me = progn.get("mercado_escanteios") or {}
    for k, d in me.items():
        if k.startswith("over") and isinstance(d, dict):
            match.sel("corners_over").add("sokkerpro", odd=d.get("odd"), prob=(d.get("probabilidade") or 0) / 100,
                                          extra=f"média {d.get('media_total_escanteios')} cantos")
    # live stats snapshot — Robobet's real-time minute is the base (it is the
    # primary spine); sokkerpro only fills the minute when Robobet has none
    # (e.g. matches only present in the sokkerpro feed, or "HT" labels).
    if not match.live.get("minute") and sk.get("minute") not in (None, ""):
        match.live["minute"] = sk["minute"]
    match.live.update({
        "corners": {"home": sk.get("corners_home"), "away": sk.get("corners_away")},
        "shots_on": {"home": sk.get("shots_on_home"), "away": sk.get("shots_on_away")},
        "possession": {"home": sk.get("possession_home"), "away": sk.get("possession_away")},
        "xg": {"home": sk.get("xg_home"), "away": sk.get("xg_away")},
        "dapm": {"home": sk.get("dapm_home"), "away": sk.get("dapm_away")},
        "dangerous_att": {"home": sk.get("dangerous_att_home"), "away": sk.get("dangerous_att_away")},
        "odds_live": sk.get("live_odds"),
    })


def _add_windrawwin(match: MatchBuilder, ww: dict, key: str) -> None:
    _merge_into(match, ww, "windrawwin", key)
    if not match.bet365_url and ww.get("bet_url"):
        match.bet365_url = ww["bet_url"]
    if not match.ww_tip_url and ww.get("tip_url"):
        match.ww_tip_url = ww["tip_url"]
    odds = ww.get("odds") or {}
    for wt, code in WW_TYPE.items():
        o = odds.get(wt)
        if o:
            match.sel(code).add("windrawwin", odd=o)
    pred = ww.get("prediction") or {}
    if pred.get("code"):
        match.sel(pred["code"]).add("windrawwin", agree=True, extra=f"stake: {pred.get('stake')}")
    if pred.get("score"):
        match.sel("score_pred").add("windrawwin", agree=False, extra=pred["score"])
    match.live.setdefault("form", {"home": ww.get("form_home"), "away": ww.get("form_away")})
    match.live.setdefault("ww_stats", ww.get("stats"))


# --- PredictZ (1X2 predictions + odds + bet365 refs) ---------------------
def _add_predictz(match: MatchBuilder, pz: dict, key: str) -> None:
    _merge_into(match, pz, "predictz", key)
    if not match.bet365_url and pz.get("bet_url"):
        match.bet365_url = pz["bet_url"]
    if not match.ww_tip_url and pz.get("tip_url"):
        match.ww_tip_url = pz["tip_url"]
    odds = pz.get("odds") or {}
    for wt, code in WW_TYPE.items():
        o = odds.get(wt)
        if o:
            match.sel(code).add("predictz", odd=o)
    pred = pz.get("prediction") or {}
    if pred.get("code"):
        match.sel(pred["code"]).add("predictz", agree=True, extra=f"PredictZ: {pred.get('score')}")
    if pred.get("score"):
        match.sel("score_pred").add("predictz", agree=False, extra=pred["score"])
    match.live.setdefault("pz_form", {"home": pz.get("form_home"), "away": pz.get("form_away")})


# --- Betrush / TipGol (tipster picks, free text) --------------------------
def _add_tipster(match: MatchBuilder, tp: dict, key: str, source: str) -> None:
    _merge_into(match, tp, source, key)
    market = tp.get("market")
    odd = tp.get("odd")
    code = None
    if market == "1":
        code = "1"
    elif market == "2":
        code = "2"
    elif market == "X":
        code = "X"
    elif market == "over":
        code = "over25"
    elif market == "under":
        code = "under25"
    elif market == "btts_yes":
        code = "btts_yes"
    if code:
        extra = f"{tp.get('pick')} @ {tp.get('bookmaker')}" if tp.get("bookmaker") else tp.get("pick")
        prob = None
        if odd:
            prob = min(0.9, max(0.05, 1.0 / odd))
        match.sel(code).add(source, odd=odd, prob=prob, agree=True, extra=extra)
    if not match.url and tp.get("url"):
        match.url = tp["url"]


# --- OddsScanner (palpites/analysis posts for today) ----------------------
def _add_oddsscanner(match: MatchBuilder, os_: dict, key: str) -> None:
    _merge_into(match, os_, "oddsscanner", key)
    if not match.url and os_.get("url"):
        match.url = os_["url"]
    if os_.get("title"):
        match.sel("analysis").add("oddsscanner", agree=False, extra=os_["title"])


# --------------------------------------------------------------------------
# main aggregation
# --------------------------------------------------------------------------
def aggregate() -> dict:
    raw = _run_scrapers()
    builders: dict[str, MatchBuilder] = {}

    def get_builder(home: str, away: str, league: str) -> MatchBuilder:
        key = f"{normalize_name(home)}|{normalize_name(away)}"
        b = builders.get(key)
        if b is None:
            b = MatchBuilder(home, away, league)
            builders[key] = b
        return b

    def find_existing(home: str, away: str) -> MatchBuilder | None:
        for b in builders.values():
            if match_teams(b.home, b.away, home, away):
                return b
        return None

    # --- robobet matches (the primary spine) ---
    rb_doc = raw.get("robobet") or {}
    if rb_doc.get("status") != "error":
        for m in rb_doc.get("matches", []):
            b = get_builder(m["home"], m["away"], m.get("league") or "")
            _add_robobet(b, m, "robobet")
        for p in rb_doc.get("picks", []):
            b = find_existing(p["match"]["home"], p["match"]["away"]) or get_builder(
                p["match"]["home"], p["match"]["away"], p["match"].get("league") or "")
            _add_robobet_pick(b, p, "robobet")
        for c in rb_doc.get("corners", []):
            b = find_existing(c["match"]["home"], c["match"]["away"]) or get_builder(
                c["match"]["home"], c["match"]["away"], c["match"].get("league") or "")
            _add_robobet_corner(b, c, "robobet")

    # --- sokkerpro matches ---
    sk_doc = raw.get("sokkerpro") or {}
    if sk_doc.get("status") != "error":
        for m in sk_doc.get("matches", []):
            b = find_existing(m["home"], m["away"]) or get_builder(m["home"], m["away"], m.get("league") or "")
            _add_sokkerpro(b, m, "sokkerpro")

    # --- windrawwin matches ---
    ww_doc = raw.get("windrawwin") or {}
    if ww_doc.get("status") != "error":
        for m in ww_doc.get("matches", []):
            b = find_existing(m["home"], m["away"]) or get_builder(m["home"], m["away"], m.get("league") or "")
            _add_windrawwin(b, m, "windrawwin")

    # --- PredictZ matches ---
    pz_doc = raw.get("predictz") or {}
    if pz_doc.get("status") != "error":
        for m in pz_doc.get("matches", []):
            b = find_existing(m["home"], m["away"]) or get_builder(m["home"], m["away"], m.get("league") or "")
            _add_predictz(b, m, "predictz")

    # --- Betrush / TipGol picks ---
    for src in ("betrush", "tipgol"):
        doc = raw.get(src) or {}
        if doc.get("status") == "error":
            continue
        for p in doc.get("matches", []):
            b = find_existing(p["home"], p["away"]) or get_builder(p["home"], p["away"], p.get("league") or "")
            _add_tipster(b, p, src, src)

    # --- OddsScanner palpites ---
    os_doc = raw.get("oddsscanner") or {}
    if os_doc.get("status") != "error":
        for m in os_doc.get("matches", []):
            b = find_existing(m["home"], m["away"]) or get_builder(m["home"], m["away"], m.get("league") or "")
            _add_oddsscanner(b, m, "oddsscanner")

    matches = [b.to_dict() for b in builders.values()]
    matches = [m for m in matches if m is not None]

    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "generated_at": now.isoformat(),
        "sources": {
            name: {
                "status": doc.get("status", "ok"),
                "error": doc.get("error"),
                "note": doc.get("note"),
                "url": doc.get("url"),
                "links": doc.get("links"),
                "top_tipsters": doc.get("top_tipsters"),
            }
            for name, doc in raw.items()
        },
        "windrawwin_acca": (ww_doc or {}).get("acca"),
        "robobet_scoreboard": (rb_doc or {}).get("scoreboard"),
        "matches": matches,
    }
