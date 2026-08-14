#!/usr/bin/env python3
"""Freebuff Bets — HTTP server (stdlib only).

Endpoints:
  GET /api/predictions   aggregated daily predictions (all sources)
  GET /api/accumulator   the recommended accumulator (<=3 legs, odd <= 4.0)
  GET /api/youtube       YouTube daily betting tips
  GET /api/live          live matches + signals (goals/corners/entries)
  GET /api/overview      everything above in one response
  GET /                  frontend (public/)
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from app import accumulator as acc_mod
from app import aggregator, live as live_mod, youtube

PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "127.0.0.1")

PUBLIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")

_cache_lock = threading.Lock()
_cached: dict[str, tuple[float, object]] = {}


def _cached_call(key: str, ttl: float, fn):
    now = time.time()
    with _cache_lock:
        item = _cached.get(key)
        if item and now - item[0] < ttl:
            return item[1]
    value = fn()
    with _cache_lock:
        _cached[key] = (now, value)
    return value


def _predictions():
    return _cached_call("predictions", 5 * 60, aggregator.aggregate)


def _accumulator():
    def build():
        agg = aggregator.aggregate()
        acca = acc_mod.build_accumulator(agg["matches"])
        return {"aggregated": agg, "accumulator": acca}
    return _cached_call("accumulator", 5 * 60, build)


def _youtube():
    return _cached_call("youtube", 20 * 60, youtube.get_daily_tips)


class Handler(BaseHTTPRequestHandler):
    server_version = "FreebuffBets/1.0"

    # quiet the logs
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, rel: str):
        path = os.path.normpath(os.path.join(PUBLIC_DIR, rel.lstrip("/")))
        if not path.startswith(PUBLIC_DIR) or not os.path.isfile(path):
            self.send_error(404)
            return
        ext = os.path.splitext(path)[1].lower()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".json": "application/json; charset=utf-8",
        }.get(ext, "application/octet-stream")
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path

        try:
            if route == "/api/predictions":
                self._send_json(_predictions())
            elif route == "/api/accumulator":
                self._send_json(_accumulator())
            elif route == "/api/youtube":
                qs = parse_qs(parsed.query)
                if qs.get("q"):
                    data = _cached_call("youtube:q", 20 * 60, youtube.get_daily_tips)
                    self._send_json(data)
                else:
                    self._send_json(_youtube())
            elif route == "/api/live":
                self._send_json(live_mod.get_live())
            elif route == "/api/overview":
                acca = _accumulator()
                live = live_mod.get_live()
                yt = _youtube()
                self._send_json({
                    "predictions": acca["aggregated"],
                    "accumulator": acca["accumulator"],
                    "youtube": yt,
                    "live": live,
                })
            elif route == "/" or route == "/index.html":
                self._send_file("index.html")
            elif route.startswith("/static/"):
                self._send_file(route[len("/static/"):])
            else:
                self.send_error(404)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)[:500]}, status=500)


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Freebuff Bets rodando em http://{HOST}:{PORT}")
    print(f"  /api/overview    -> previsões + acumuladora + youtube + ao vivo")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nParado.")


if __name__ == "__main__":
    main()
