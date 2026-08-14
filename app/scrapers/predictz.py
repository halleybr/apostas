"""PredictZ predictions scraper (https://www.predictz.com/predictions/).

Parses the daily 1X2 prediction tables: teams, league, predicted score,
H/D/A prediction, form (last 5), 1X2 odds and — when present — the
bet365 deep-link refs (same windrawwin betslip mechanism).
"""
from __future__ import annotations

import json
import re

from app.fetch import cached_fetch_text
from app.htmlparse import Node, parse

URL = "https://www.predictz.com/predictions/"
TTL = 15 * 60  # 15 min

# prediction box classes: nred (away/danger), ngreen (home), nyellow (draw)
_PRED_MAP = {
    "Home": ("1", "Vitória do mandante"),
    "Draw": ("X", "Empate"),
    "Away": ("2", "Vitória do visitante"),
}


def _dec(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return None


def scrape() -> dict:
    """Return {'matches': [...], 'url': ...}"""
    try:
        html = cached_fetch_text(URL, TTL)
        root = parse(html)
    except Exception as exc:  # noqa: BLE001
        return {"matches": [], "url": URL, "status": "error", "error": str(exc)[:200]}

    matches: list[dict] = []
    current_league = ""
    # league headers (pttrnh ptttl) and match rows (pttr ptcnt) are siblings
    # inside each league table — walk them in document order.
    for node in root.find_all(class_=("ptttl", "pttr")):
        if node.has_class("ptttl"):
            lg = _league_for(node, current_league)
            if lg:
                current_league = lg
            continue
        if not node.has_class("ptcnt") or node.has_class("watch"):
            continue
        match = _parse_row(node, current_league)
        if match:
            matches.append(match)

    status = "ok" if matches else "parcial"
    return {"matches": matches, "url": URL, "status": status,
            "note": None if matches else "PredictZ não retornou previsões agora."}


def _league_for(row: Node, fallback: str) -> str:
    lg = row.find(class_="ptlg")
    if lg is None:
        return fallback
    a = lg.find("a")
    if a is not None:
        return a.get_text()
    h2 = lg.find("h2")
    if h2 is not None:
        return h2.get_text()
    return fallback


def _parse_row(row: Node, league: str) -> dict | None:
    game = row.find(class_="ptgame")
    if game is None:
        return None
    link = game.find("a")
    if link is None:
        return None
    name = link.get_text().strip()
    m = re.match(r"^(.+?)\s+v(?:s)?\.?\s+(.+)$", name)
    if not m:
        return None
    home, away = m.group(1).strip(), m.group(2).strip()

    # prediction box ("Home 1-0", "Away 2-1", "Draw 0-0")
    pred = {"code": None, "label": None, "score": None, "text": ""}
    box = row.find(class_="ptpredboxsml")
    if box is not None:
        txt = box.get_text().strip()
        pred["text"] = txt
        pm = re.match(r"^(Home|Draw|Away)\s+(\d+-\d+)$", txt)
        if pm:
            code, label = _PRED_MAP.get(pm.group(1), (None, None))
            pred["code"], pred["label"], pred["score"] = code, label, pm.group(2)

    # form (last 5) — home/away
    fh = [d.text.strip() for d in row.find_all("div") if d.text.strip() in ("W", "D", "L")][:5]
    # order matters: home form comes first, away after the game name
    home_form, away_form = _split_form(row)

    # odds + bet365 refs
    odds: dict[str, float] = {}
    ref1 = ref2 = oddsf = ""
    for a in row.find_all("a"):
        t = a.get("data-type")
        raw = a.get("data-odds")
        if t and raw:
            try:
                odds[t] = float(raw)
            except ValueError:
                pass
            if not ref1 and a.get("data-ref1") and a.get("data-ref2"):
                ref1 = a.get("data-ref1", "")
                ref2 = a.get("data-ref2", "")
                oddsf = a.get("data-oddsf", "")
    if not odds:
        # some rows render plain text odds instead of buttons
        plain = [d for d in row.find_all(class_="ptodds") if d.get_text().strip()]
        if len(plain) >= 3:
            o = _dec(plain[0].get_text())
            if o:
                odds["MH"] = o
            o = _dec(plain[1].get_text())
            if o:
                odds["MD"] = o
            o = _dec(plain[2].get_text())
            if o:
                odds["MA"] = o

    bet_url = None
    if ref1 and ref2:
        bet_url = f"https://www.windrawwin.com/bet365/betslip/?p={ref2}-{ref1}~{oddsf}"

    tip_url = link.get("href") or ""
    if tip_url and not tip_url.startswith("http"):
        tip_url = "https://www.predictz.com" + tip_url

    return {
        "home": home,
        "away": away,
        "league": league,
        "odds": odds,
        "prediction": pred,
        "form_home": home_form,
        "form_away": away_form,
        "bet_url": bet_url,
        "tip_url": tip_url,
        "source_url": URL,
    }


def _split_form(row: Node):
    """Extract last-5 form in the right order (home box, then away box)."""
    out_h: list[str] = []
    out_a: list[str] = []
    boxes = row.find_all(class_=("ptlast5boxh", "ptlast5boxa"))
    for box in boxes:
        vals = [d.text.strip() for d in box.find_all("div") if d.text.strip() in ("W", "D", "L")]
        if box.has_class("ptlast5boxh"):
            out_h = vals
        else:
            out_a = vals
    return out_h[:5], out_a[:5]
