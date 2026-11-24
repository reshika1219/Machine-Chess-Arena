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


def bootstrap_ci(
    games: list[tuple[str, str, float]], anchors: dict[str, float] | None = None,
    samples: int = 200, confidence: float = 0.95, seed: int = 0,
) -> dict[str, tuple[float, float]]:
    """Percentile bootstrap over games: resample the results with replacement, re-rate, and report
    the central `confidence` interval per player. Small samples give (honestly) wide intervals."""
    import random

    if not games:
        return {}
    rng = random.Random(seed)
    names = {n for w, b, _ in games for n in (w, b)}
    draws: dict[str, list[float]] = {n: [] for n in names}
    for _ in range(samples):
        sample = [games[rng.randrange(len(games))] for _ in games]
        r = compute_ratings(sample, anchors=anchors)
        for n, v in r.items():
            draws[n].append(v)
    lo_q, hi_q = (1 - confidence) / 2, 1 - (1 - confidence) / 2
    out: dict[str, tuple[float, float]] = {}
    for n, vals in draws.items():
        if not vals:
            continue
        vals.sort()
        out[n] = (vals[int(lo_q * (len(vals) - 1))], vals[int(round(hi_q * (len(vals) - 1)))])
    return out
