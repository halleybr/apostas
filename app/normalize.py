"""Team name normalization + fuzzy matching between sources."""
from __future__ import annotations

import re
import unicodedata

STOP_WORDS = {
    "fc", "cf", "sc", "ac", "as", "cd", "cc", "ca", "ec", "clube", "club", "clup",
    "sociedade", "sport", "sports", "futebol", "futbol", "football", "de", "da",
    "do", "das", "dos", "the", "&", "e", "and", "real", "atletico", "atlético",
    "athletic", "athletico", "nacional", "x", "vs", "v", "rodada", "associacao",
    "associação", "assoc", "union", "unión", "uniao", "uniao",
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _strip_accents(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", s)
        if unicodedata.category(ch) != "Mn"
    )


def normalize_name(name: str) -> str:
    """Normalize a team name to comparable tokens."""
    n = _strip_accents(name.lower())
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    tokens = [t for t in n.split() if t and t not in STOP_WORDS and len(t) > 1]
    return " ".join(tokens)


def tokens(name: str) -> set[str]:
    return set(normalize_name(name).split())


def similarity(a: str, b: str) -> float:
    """0..1 similarity between two team names based on token overlap."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    return 2 * len(inter) / (len(ta) + len(tb))


def match_teams(home_a: str, away_a: str, home_b: str, away_b: str, threshold: float = 0.6) -> bool:
    """True if (home_a, away_a) matches (home_b, away_b) in either direction."""
    s_h = similarity(home_a, home_b)
    s_a = similarity(away_a, away_b)
    s_h_swap = similarity(home_a, away_b)
    s_a_swap = similarity(away_a, home_b)
    return (s_h >= threshold and s_a >= threshold) or (s_h_swap >= threshold and s_a_swap >= threshold)


def match_single(a: str, b: str, threshold: float = 0.6) -> bool:
    return similarity(a, b) >= threshold
