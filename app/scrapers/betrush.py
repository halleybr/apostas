"""Betrush / TipGol picks scraper.

Both sites run on the same tipster-platform template (picktooltip rows with
a date, flag, match link, pick text + odd and the tipster name). One parser
serves both; the tip text is usually in English on Betrush and Spanish on
TipGol.
"""
from __future__ import annotations

import re

from app.fetch import cached_fetch_text
from app.htmlparse import Node, parse

SOURCES = {
    "betrush": {
        "url": "https://www.betrush.com/",
        "label": "Betrush",
        "lang": "en",
    },
    "tipgol": {
        "url": "https://www.tipgol.com/",
        "label": "TipGol",
        "lang": "es",
    },
}
TTL = 15 * 60

_MARKET_KEYS = {
    # EN
    "over": "over",
    "under": "under",
    "btts": "btts_yes",
    "both teams to score": "btts_yes",
    "home": "1",
    "away": "2",
    "draw": "X",
    "win": "1",
    # ES
    "mas de": "over",
    "menos de": "under",
    "ambos marcan": "btts_yes",
    "local": "1",
    "visitante": "2",
    "empate": "X",
    "gana": "1",
}


def _parse_pick_text(text: str) -> dict:
    """Extract {selection, market} from free-text picks like
    'AH -2,5 1 Dinamo, 1.85 @ 888sport' or 'Braumschweig gana, 2.36 @ Caliente'."""
    t = text.strip()
    out: dict = {"selection": "", "market": "", "odd": None, "bookmaker": ""}
    # bookmaker after @
    m = re.search(r"@\s*([A-Za-z0-9 .-]+)$", t)
    if m:
        out["bookmaker"] = m.group(1).strip()
        t = t[: m.start()].strip()
    # trailing odd
    m = re.search(r",\s*(\d+(?:[.,]\d+)?)\s*$", t)
    if m:
        out["odd"] = float(m.group(1).replace(",", "."))
        t = t[: m.start()].strip()
    out["selection"] = t
    low = t.lower()
    for key, code in _MARKET_KEYS.items():
        if key in low:
            out["market"] = code
            break
    return out


def scrape(source: str = "betrush") -> dict:
    conf = SOURCES.get(source, SOURCES["betrush"])
    try:
        html = cached_fetch_text(conf["url"], TTL)
        root = parse(html)
    except Exception as exc:  # noqa: BLE001
        return {"matches": [], "url": conf["url"], "status": "error", "error": str(exc)[:200]}

    picks: list[dict] = []
    for td in root.find_all(class_="picktooltip"):
        # match link
        a = td.find("a")
        if a is None:
            continue
        name = a.get_text().strip()
        href = a.get("href") or ""
        m = re.match(r"^(.+?)\s+[-–]\s+(.+)$", name) or re.match(r"^(.+?)\s+(?:vs|v)\.?\s+(.+)$", name)
        if not m:
            continue
        home, away = m.group(1).strip(), m.group(2).strip()
        # pick text
        pt = td.find(class_="picktext")
        pick_txt = pt.get_text() if pt else ""
        parsed = _parse_pick_text(pick_txt)
        # tipster name in the sibling td
        tipster = ""
        row = td.find_parent("tr")
        if row is not None:
            rt = row.find(class_="right_td")
            if rt is not None:
                ta = rt.find("a")
                tipster = ta.get_text() if ta else rt.get_text()

        picks.append({
            "home": home,
            "away": away,
            "league": "",
            "pick": parsed["selection"],
            "market": parsed["market"],
            "odd": parsed["odd"],
            "bookmaker": parsed["bookmaker"],
            "tipster": tipster,
            "source": conf["label"],
            "url": href if href.startswith("http") else conf["url"].rstrip("/") + "/" + href.lstrip("/"),
        })

    status = "ok" if picks else "parcial"
    return {"matches": picks, "url": conf["url"], "status": status,
            "note": None if picks else f"{conf['label']} não retornou picks agora."}
