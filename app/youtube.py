"""YouTube betting-tips search.

Primary path: parse ``ytInitialData`` from the search results page (works
without API key). Optional: if YOUTUBE_API_KEY env var is set, the official
search API is used instead (more reliable).
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse

from app.fetch import cached_fetch_text, fetch_json, FetchError

SEARCH_URL = "https://www.youtube.com/results"
TTL = 20 * 60

DEFAULT_QUERIES = [
    "dicas de apostas de futebol hoje",
    "palpites futebol hoje",
    "melhores apostas do dia futebol",
]

YT_HEADERS = {
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cookie": "CONSENT=YES+cb.20210328-17-p0.en+FX+000; PREF=gl=BR&hl=pt",
}


def _extract_videos(html: str, max_videos: int = 12) -> list[dict]:
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", html, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return []

    videos: list[dict] = []
    try:
        contents = (
            data["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"]
            ["sectionListRenderer"]["contents"]
        )
        for section in contents:
            item_section = section.get("itemSectionRenderer", {}).get("contents", [])
            for item in item_section:
                vr = item.get("videoRenderer")
                if not vr:
                    continue
                title = _text(vr.get("title"))
                if not title:
                    continue
                videos.append({
                    "id": vr.get("videoId"),
                    "title": title,
                    "channel": _text(vr.get("ownerText")),
                    "views": _text(vr.get("viewCountText")),
                    "published": _text(vr.get("publishedTimeText")),
                    "length": _text(vr.get("lengthText")),
                    "url": f"https://www.youtube.com/watch?v={vr.get('videoId')}",
                    "thumbnail": (vr.get("thumbnail", {}).get("thumbnails") or [{}])[-1].get("url", ""),
                })
                if len(videos) >= max_videos:
                    return videos
    except (KeyError, TypeError):
        pass
    return videos


def _text(node) -> str:
    if not node:
        return ""
    if isinstance(node, str):
        return node
    runs = node.get("runs")
    if runs:
        return "".join(r.get("text", "") for r in runs)
    simple = node.get("simpleText")
    return simple or ""


def _scrape_search(query: str, max_videos: int) -> list[dict]:
    url = SEARCH_URL + "?" + urllib.parse.urlencode({"search_query": query})
    html = cached_fetch_text(url, TTL, headers=YT_HEADERS, encoding="utf-8")
    return _extract_videos(html, max_videos)


def _api_search(query: str, max_videos: int, api_key: str) -> list[dict]:
    url = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode({
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": max_videos,
        "relevanceLanguage": "pt",
        "key": api_key,
    })
    doc = fetch_json(url)
    out = []
    for item in doc.get("items", []):
        sn = item.get("snippet", {})
        out.append({
            "id": item["id"]["videoId"],
            "title": sn.get("title", ""),
            "channel": sn.get("channelTitle", ""),
            "views": "",
            "published": "",
            "length": "",
            "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
            "thumbnail": (sn.get("thumbnails", {}).get("medium") or {}).get("url", ""),
        })
    return out


def get_daily_tips() -> dict:
    """Search several queries and return grouped videos."""
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    groups = []
    for q in DEFAULT_QUERIES:
        try:
            videos = _api_search(q, 8, api_key) if api_key else _scrape_search(q, 8)
        except (FetchError, ValueError, KeyError):
            videos = []
        groups.append({"query": q, "search_url": SEARCH_URL + "?" + urllib.parse.urlencode({"search_query": q}), "videos": videos})
    return {
        "groups": groups,
        "search_url": SEARCH_URL + "?" + urllib.parse.urlencode({"search_query": DEFAULT_QUERIES[0]}),
    }
