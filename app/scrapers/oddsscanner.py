"""Oddsscanner (https://oddsscanner.com/br/futebol) — best effort.

The fixture grid loads client-side through a session-protected API, but the
page pre-renders the "Palpites de Hoje" (match analyses for today's games)
in its Next.js RSC payload. We extract those games + analysis links so the
site surfaces OddsScanner's picks of the day even without session access.
"""
from __future__ import annotations

import html as htmlmod
import re

from app.fetch import cached_fetch_text

URL = "https://oddsscanner.com/br/futebol"
TTL = 30 * 60

LINKS = {
    "Futebol (hoje)": "https://oddsscanner.com/br/futebol",
    "Palpites": "https://oddsscanner.com/br/palpites",
    "Futebol ao vivo": "https://oddsscanner.com/br/futebol-ao-vivo",
}

_RSC_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.S)
_POST_RE = re.compile(
    r'"href":"(https://oddsscanner\.com/br/palpites/futebol/[^"]+)",'
    r'"children":\["\$","span",null,\{"dangerouslySetInnerHTML":\{"__html":"([^"]+)"',
    re.S,
)


def _extract(html_text: str) -> list[dict]:
    allp = "".join(_RSC_RE.findall(html_text))
    try:
        allp = allp.encode().decode("unicode_escape", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    posts: list[dict] = []
    seen = set()
    for href, title in _POST_RE.findall(allp):
        if href in seen:
            continue
        seen.add(href)
        title = htmlmod.unescape(title).strip()
        home = away = ""
        # slug always contains "home_x_away" (e.g. racing-x-banfield)
        slug = href.rstrip("/").split("/")[-1]
        m = re.match(r"^(.+?)-x-(.+?)-(?:\d{2}-\d{2}-\d{4})$", slug)
        if m:
            home = m.group(1).replace("-", " ").title()
            away = m.group(2).replace("-", " ").title()
        if not home:
            mm = re.match(r"^(.+?)\s*x\s+(.+?)\s*[–-]", title)
            if mm:
                home, away = mm.group(1).strip(), mm.group(2).strip()
        posts.append({
            "home": home,
            "away": away,
            "league": "",
            "title": title,
            "url": href,
            "source": "Oddsscanner",
        })
    return posts


def scrape() -> dict:
    try:
        html = cached_fetch_text(URL, TTL)
    except Exception as exc:  # noqa: BLE001
        return {"matches": [], "url": URL, "status": "error", "error": str(exc)[:200], "links": LINKS}
    posts = _extract(html)
    note = (
        "Palpites de hoje do OddsScanner (análises). O grid de odds ao vivo "
        "exige sessão — os jogos do dia vêm do Robobet, SokkerPro, Windrawwin e PredictZ."
    )
    status = "ok" if posts else "parcial"
    return {"matches": posts, "url": URL, "status": status, "note": note, "links": LINKS}
