from __future__ import annotations

import math


def expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def update(ra: float, rb: float, score_a: float, k: float = 32.0) -> tuple[float, float]:
    ea = expected(ra, rb)
    return ra + k * (score_a - ea), rb + k * ((1 - score_a) - (1 - ea))


def score_from_result(result: str) -> float | None:
    """White's score, or None if the game was unfinished."""
    return {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}.get(result)


def compute_ratings(
    games: list[tuple[str, str, float]], start: float = 1000.0, k: float = 32.0,
    passes: int = 20, anchors: dict[str, float] | None = None,
) -> dict[str, float]:
    """games: (white, black, white_score). Order-independent: sweep several passes with a
    shrinking K so ratings settle, then optionally shift so anchors keep their known rating."""
    names = {n for w, b, _ in games for n in (w, b)}
    r = {n: start for n in names}
    for i in range(passes):
        kk = k * (1 - i / (passes + 1))
        for w, b, s in games:
            r[w], r[b] = update(r[w], r[b], s, kk)
    if anchors:
        known = [n for n in anchors if n in r]
        if known:
            shift = sum(anchors[n] - r[n] for n in known) / len(known)
            r = {n: v + shift for n, v in r.items()}
    return r
