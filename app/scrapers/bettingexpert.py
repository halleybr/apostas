"""BettingExpert scraper (https://www.bettingexpert.com/tips) — best effort.

The tips feed is rendered entirely client-side behind Next.js server actions,
so the raw HTML contains no tip rows. We expose:
  - the public URLs (today / tomorrow / upcoming feeds)
  - search deep-links
  - any tipster/tip data that IS present in the SSR payload (usually none)
The aggregator treats this source as supplementary.
"""
from __future__ import annotations

import re

from app.fetch import cached_fetch_text, FetchError

URL = "https://www.bettingexpert.com/tips"
TTL = 30 * 60

LINKS = {
    "Dicas de hoje": "https://www.bettingexpert.com/tips",
    "Dicas de amanhã": "https://www.bettingexpert.com/tips/tomorrow",
    "Próximas partidas": "https://www.bettingexpert.com/tips/upcoming",
}


def scrape() -> dict:
    out = {
        "status": "ok",
        "tips": [],
        "top_tipsters": [],
        "links": LINKS,
        "url": URL,
    }
    try:
        html = cached_fetch_text(URL, TTL)
    except FetchError as exc:
        out["status"] = "error"
        out["error"] = str(exc)
        return out

    # top tipsters are rendered server-side on some pages
    tipsters = []
    for m in re.finditer(r'href="/(?:tipster|en/tipster)/([a-zA-Z0-9_.-]+)"', html):
        name = m.group(1).replace("-", " ").title()
        if name not in tipsters:
            tipsters.append(name)
    out["top_tipsters"] = tipsters[:10]
    if not tipsters:
        out["status"] = "parcial"
        out["note"] = (
            "A lista de dicas da BettingExpert é carregada via JavaScript "
            "(server actions do Next.js) e não está disponível no HTML estático. "
            "Acesse os links abaixo para ver as dicas no site original."
        )
    return out
