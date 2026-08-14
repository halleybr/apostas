"""Accumulator builder.

Rules (as requested):
  - at most 3 selections (games)
  - combined odd <= 4.0
  - maximise reliability (agreement between sources x model probability)
"""
from __future__ import annotations

import itertools
import math

MAX_LEGS = 3
MAX_ODD = 4.0
MIN_ODD = 1.10

FINISHED = {"FT", "finished", "AET", "PEN", "HT", "Canceled", "canceled", "abandoned"}


def _is_playable(match: dict) -> bool:
    status = (match.get("status") or "").upper()
    if status in FINISHED:
        return False
    if match.get("isLive"):
        return False
    return True


def _pick_best_selection(match: dict) -> dict | None:
    """Best playable selection for a match (highest reliability with a real odd)."""
    best = None
    for s in match.get("selections", []):
        if not s.get("best_odd") or s.get("best_odd") < MIN_ODD or s.get("best_odd") > 20:
            continue
        if s.get("prob_pct") is not None and s["prob_pct"] < 55:
            continue
        if s["reliability"] < 0.45:
            continue
        if best is None or s["reliability"] > best["reliability"]:
            best = s
    if best is None:
        return None
    return {
        "match_key": match["key"],
        "home": match["home"],
        "away": match["away"],
        "league": match["league"],
        "start_time": match.get("start_time"),
        "selection": best["code"],
        "selection_label": best["label"],
        "odd": best["best_odd"],
        "prob": best.get("prob"),
        "reliability": best["reliability"],
        "sources": best.get("sources", []),
        "is_pick": best.get("is_pick", False),
        "bet365_url": match.get("bet365_url"),
    }


def build_accumulator(matches: list[dict]) -> dict:
    candidates = []
    for m in matches:
        if not _is_playable(m):
            continue
        leg = _pick_best_selection(m)
        if leg:
            candidates.append(leg)

    candidates.sort(key=lambda l: l["reliability"], reverse=True)
    pool = candidates[:14]  # search space cap

    combos: list[dict] = []

    def score_combo(legs):
        odd = math.prod(l["odd"] for l in legs)
        rel = math.prod(l["reliability"] for l in legs) ** (1.0 / len(legs))
        # small preference for real accumulators (2-3 legs) over singles
        rel = rel * (1 + 0.04 * (len(legs) - 1))
        avg_prob = sum(l["prob"] or 0 for l in legs) / len(legs) if legs else 0
        return rel, avg_prob

    for size in range(1, MAX_LEGS + 1):
        for combo in itertools.combinations(pool, size):
            odd = math.prod(l["odd"] for l in combo)
            if odd < MIN_ODD or odd > MAX_ODD:
                continue
            rel, avg_prob = score_combo(combo)
            combos.append({
                "legs": list(combo),
                "odd": round(odd, 2),
                "reliability": round(rel, 4),
                "avg_prob": round(avg_prob, 4),
            })

    # rank: reliability first, then prefer higher odd utilisation (closer to 4.0)
    combos.sort(key=lambda c: (-c["reliability"], -c["odd"]))

    def _safe(combo):
        return combo if combo is not None else None

    recommended = _safe(combos[0] if combos else None)

    # balanced: best (reliability x odd utilisation) among decent combos
    decent = [c for c in combos if c["reliability"] >= 0.5]
    balanced = None
    if decent:
        balanced = max(decent, key=lambda c: c["reliability"] * (c["odd"] / MAX_ODD))

    # max odd: highest combined odd within the 4.0 cap (still reliable-ish)
    max_odd = None
    if decent:
        max_odd = max(decent, key=lambda c: c["odd"])

    # fallback: best single if no combo satisfies the constraints
    if recommended is None and candidates:
        best = candidates[0]
        recommended = {
            "legs": [best],
            "odd": round(best["odd"], 2),
            "reliability": best["reliability"],
            "avg_prob": best.get("prob"),
        }
        balanced = max_odd = recommended

    return {
        "recommended": recommended,
        "balanced": balanced,
        "max_odd_combo": max_odd,
        "alternatives": combos[1:8],
        "candidates": candidates[:20],
        "max_legs": MAX_LEGS,
        "max_odd": MAX_ODD,
    }
