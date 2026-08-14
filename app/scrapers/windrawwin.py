"""Windrawwin predictions scraper (https://www.windrawwin.com/predictions/today/).

Parses the prediction tables: match odds (1X2), O/U 2.5, BTTS, form,
stats, prediction text and the site's own daily accumulator.
"""
from __future__ import annotations

import re

from app.fetch import cached_fetch_text
from app.htmlparse import Node, parse

URL = "https://www.windrawwin.com/predictions/today/"
TTL = 15 * 60  # 15 min

STAKES = {
    "small": 0.6,
    "medium": 0.75,
    "moderate": 0.75,
    "big": 0.9,
    "large": 0.9,
    "heavy": 0.9,
}


def _dec(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return float(text.strip())
    except ValueError:
        return None


def _parse_prediction(text: str):
    """Map windrawwin prediction text to our selection vocabulary."""
    t = text.strip().lower()
    if "home win" in t or t == "1":
        return "1", "Vitória do mandante"
    if "away win" in t or t == "2":
        return "2", "Vitória do visitante"
    if "draw" in t or t == "x":
        return "X", "Empate"
    if "over 2.5" in t:
        return "over25", "Mais de 2.5 gols"
    if "under 2.5" in t:
        return "under25", "Menos de 2.5 gols"
    if "over 1.5" in t:
        return "over15", "Mais de 1.5 gols"
    if "under 1.5" in t:
        return "under15", "Menos de 1.5 gols"
    if "both teams to score - yes" in t or "btts - yes" in t or t == "yes":
        return "btts_yes", "Ambos marcam (sim)"
    if "both teams to score - no" in t or "btts - no" in t or t == "no":
        return "btts_no", "Ambos marcam (não)"
    if "home -1" in t or "home minus" in t:
        return "home_ah-1", "Casa -1 (handicap)"
    if "away +1" in t or "away plus" in t:
        return "away_ah+1", "Fora +1 (handicap)"
    return None, None


def _clean_date(text: str) -> str:
    t = re.sub(r"(?i)kick off on\s*", "", text).strip()
    t = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t)  # SundayAugust -> Sunday August
    return t


def _stake_conf(text: str) -> float:
    m = re.search(r"(small|medium|moderate|big|large|heavy)\s+stake", text.lower())
    if m:
        return STAKES.get(m.group(1), 0.6)
    return 0.6


def scrape() -> dict:
    """Return {'matches': [...], 'acca': {...}|None, 'url': ...}"""
    for attempt in range(2):
        result = _scrape_once()
        if result["matches"] or attempt > 0:
            if not result["matches"] and result.get("status") != "error":
                result["status"] = "parcial"
                result["note"] = "Windrawwin não retornou previsões (anti-bot/limite). As demais fontes seguem normais."
            return result
        import time as _time

        _time.sleep(6)
    return result


def _scrape_once() -> dict:
    """One parse pass; returns matches/acca or marks the outcome."""
    html = cached_fetch_text(URL, TTL)
    root = parse(html)
    matches: list[dict] = []
    acca: dict | None = None

    # --- daily accumulator block -----------------------------------------
    sug = root.find(class_="sugbetgo2")
    if sug is not None:
        date_node = sug.find(class_="sugbetdate2")
        odd_node = sug.find(class_="sugbetvbigodds2")
        btn = sug.find("a", class_="btnc")
        acca = {
            "date": _clean_date(date_node.get_text()) if date_node else "",
            "odd": _dec(odd_node.get_text()) if odd_node else None,
            "legs": [],
            "url": None,
        }
        if btn is not None:
            href = btn.get("href", "")
            acca["url"] = href if href.startswith("http") else "https://www.windrawwin.com" + href
            m = re.search(r"[?&]p=([^&]+)", href)
            if m:
                acca["legs"] = [seg.split("~")[0] for seg in m.group(1).split("|") if seg]

    # --- prediction tables -------------------------------------------------
    # NB: the league header (wtcont) and the prediction table (wdwtablest)
    # are *siblings* inside the page — walk them in document order.
    current_league = ""
    for node in root.find_all(class_=("wtcont", "wdwtablest")):
        if node.has_class("wtcont"):
            league = ""
            flag = node.find(class_="ptflag")
            if flag is not None:
                for div in flag.find_all("div"):
                    title = div.get("title")
                    if title:
                        league = title
                        break
            if not league:
                leag = node.find(class_="ptleag")
                if leag is not None:
                    league = leag.get_text()
            current_league = league or current_league
            continue
        for row in node.find_all(class_="wttr"):
            match = _parse_row(row, current_league)
            if match:
                matches.append(match)

    # resolve acca legs against matches via data-ref1
    if acca and acca.get("legs"):
        ref_map: dict[str, dict] = {}
        for a in root.find_all("a"):
            ref1 = a.get("data-ref1")
            if ref1 and a.get("data-type"):
                ref_map[ref1] = {
                    "home": a.get("data-home", ""),
                    "away": a.get("data-away", ""),
                    "type": a.get("data-type", ""),
                    "odds": _dec(a.get("data-odds")),
                    "oddsf": a.get("data-oddsf", ""),
                }
        resolved = []
        for leg in acca["legs"]:
            ref1 = leg.split("-")[-1]
            info = ref_map.get(ref1)
            if info:
                resolved.append({
                    "home": info["home"],
                    "away": info["away"],
                    "market": info["type"],
                    "odds": info["odds"],
                    "fraction": info["oddsf"],
                })
            else:
                resolved.append({"ref": leg})
        acca["legs"] = resolved

    status = "ok"
    if not matches and not acca:
        status = "parcial"
    return {"matches": matches, "acca": acca, "url": URL, "status": status}


def _parse_row(row: Node, league: str) -> dict | None:
    odds: dict[str, float] = {}
    types: dict[str, str] = {}
    home = away = ""
    ref1 = ref2 = oddsf = ""
    for a in row.find_all("a"):
        t = a.get("data-type")
        raw_odd = a.get("data-odds")
        if t and raw_odd:
            try:
                odds[t] = float(raw_odd)
                types[t] = a.get("data-home", "") + "|" + a.get("data-away", "")
            except ValueError:
                pass
            if not ref1 and a.get("data-ref1") and a.get("data-ref2"):
                ref1 = a.get("data-ref1", "")
                ref2 = a.get("data-ref2", "")
                oddsf = a.get("data-oddsf", "")
    if not odds:
        return None

    # teams from the fixture cells
    moblnks = row.find_all(class_="wtmoblnk")
    if len(moblnks) >= 2:
        home = moblnks[0].get_text()
        away = moblnks[1].get_text()
    if not home or not away:
        m = re.match(r"(.+?)\s+v(?:s)?\.?\s+(.+)", (row.find(class_="wtdesklnk") or row.find(class_="wtmoblnk") or Node("#n", {}, None)).get_text() or "")
        if m:
            home, away = m.group(1).strip(), m.group(2).strip()

    # prediction text + score + stake
    pred = {"code": None, "label": None, "text": "", "stake": None, "score": None, "confidence": 0.6}
    prd = row.find(class_="wtprd")
    if prd is not None:
        pred["text"] = prd.get_text()
        pred["code"], pred["label"] = _parse_prediction(pred["text"])
    full = row.find(class_="wtfullpred")
    if full is not None:
        stake_node = full.find(class_="predstake")
        score_node = full.find(class_="predscore")
        if stake_node is not None:
            st = stake_node.get_text()
            pred["stake"] = st
            if not pred["code"]:
                pred["code"], pred["label"] = _parse_prediction(st)
            conf = _stake_conf(st)
            pred["confidence"] = conf if conf > pred["confidence"] else pred["confidence"]
        if score_node is not None:
            pred["score"] = score_node.get_text()

    # stats / form
    stats = []
    for span in row.find_all(class_="statgrey"):
        txt = span.get_text()
        if txt:
            stats.append(txt)

    l5h, l5a = _form_per_team(row)

    # bet365 deep link (windrawwin official betslip proxy) + tip page
    bet_url = None
    if ref1 and ref2:
        bet_url = f"https://www.windrawwin.com/bet365/betslip/?p={ref2}-{ref1}~{oddsf}"
    tip_url = None
    desk = row.find(class_="wtdesklnk")
    if desk is not None:
        href = desk.get("href")
        if href:
            tip_url = href if href.startswith("http") else "https://www.windrawwin.com" + href

    return {
        "home": home,
        "away": away,
        "league": league,
        "odds": odds,
        "prediction": pred,
        "form_home": l5h,
        "form_away": l5a,
        "stats": stats[:6],
        "bet_url": bet_url,
        "tip_url": tip_url,
        "source_url": URL,
    }


def _form_per_team(row: Node):
    """Extract last-5 form (W/D/L) per team in the correct order."""
    out_h, out_a = [], []
    containers = row.find_all(class_="wtl5mcont")
    if len(containers) >= 2:
        out_h = [d.text.strip() for d in containers[0].find_all("div") if d.text.strip() in ("W", "D", "L")]
        out_a = [d.text.strip() for d in containers[1].find_all("div") if d.text.strip() in ("W", "D", "L")]
    return out_h, out_a
