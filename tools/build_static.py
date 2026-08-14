#!/usr/bin/env python3
"""Build a static, serverless version of ApostaRadar for GitHub Pages.

Runs the aggregation once (network), embeds the resulting snapshot into the
frontend (``window.__SNAPSHOT__``), and writes the site to ``site/``:

    site/index.html          dashboard (references ./static/*)
    site/static/styles.css
    site/static/app.js

The frontend already falls back to the embedded snapshot when the API is
not reachable, so the site works fully static on GitHub Pages.

Usage:  python tools/build_static.py [out-dir]   (default: site)
"""
from __future__ import annotations

import json
import shutil
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server as srv_mod  # noqa: E402


def build(out_dir: Path, host: str = "127.0.0.1", port: int = 8141) -> dict:
    srv = ThreadingHTTPServer((host, port), srv_mod.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/overview", timeout=240) as r:
            data = json.loads(r.read())
    finally:
        srv.shutdown()

    public = ROOT / "public"
    index_tpl = (public / "index.html").read_text(encoding="utf-8")
    css = (public / "styles.css").read_text(encoding="utf-8")
    js = (public / "app.js").read_text(encoding="utf-8")

    # keep the layout but swap absolute /static/* paths for relative ones
    index_tpl = index_tpl.replace('href="/static/styles.css"', 'href="./static/styles.css"')

    snapshot = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    snapshot_script = f"<script>window.__SNAPSHOT__ = {snapshot};</script>\n"
    index_tpl = index_tpl.replace(
        '<script src="/static/app.js"></script>',
        snapshot_script + '<script src="./static/app.js"></script>',
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(index_tpl, encoding="utf-8")
    (out_dir / "static").mkdir(parents=True, exist_ok=True)
    (out_dir / "static" / "styles.css").write_text(css, encoding="utf-8")
    (out_dir / "static" / "app.js").write_text(js, encoding="utf-8")

    return {
        "matches": len(data["predictions"]["matches"]),
        "acca_odd": data["accumulator"]["recommended"]["odd"] if data["accumulator"]["recommended"] else None,
        "youtube_videos": sum(len(g["videos"]) for g in data["youtube"]["groups"]),
        "live_matches": len(data["live"]["live_matches"]),
        "generated_at": data["predictions"]["generated_at"],
    }


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site"
    if out.exists():
        shutil.rmtree(out)
    info = build(out)
    print("Site estático gerado em", out)
    for k, v in info.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
