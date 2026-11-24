"""Tournaments: round-robin or Swiss, colour-balanced, opening-suite aware, with anchored Elo and CIs."""
from __future__ import annotations

import datetime as dt
import itertools
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yaml

from .config import GameConfig, MatchConfig, OutputConfig, PlayerConfig
from .elo import bootstrap_ci, compute_ratings, score_from_result
from .players.base import Player
from .players.factory import build_player
from .runner import run_game


@dataclass
class Standing:
    name: str
    games: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    points: float = 0.0
    elo: float = 1000.0
    elo_lo: Optional[float] = None
    elo_hi: Optional[float] = None


@dataclass
class TournamentResult:
    standings: list[Standing]
    games: list[dict] = field(default_factory=list)
    format: str = "round_robin"
    anchors: dict[str, float] = field(default_factory=dict)

    def leaderboard_md(self) -> str:
        rows = ["| # | Player | Elo (95% CI) | Pts | G | W | D | L |", "|---|---|---|---|---|---|---|---|"]
        for i, s in enumerate(self.standings, 1):
            ci = f" [{s.elo_lo:.0f}, {s.elo_hi:.0f}]" if s.elo_lo is not None else ""
            anchor = "*" if s.name in self.anchors else ""
            rows.append(f"| {i} | {s.name} | {s.elo:.0f}{anchor}{ci} | {s.points:g} | {s.games} | {s.wins} | {s.draws} | {s.losses} |")
        md = "\n".join(rows) + "\n"
        return md + ("\n\\* anchored rating (known strength)\n" if self.anchors else "")

    def to_json(self) -> dict:
        return {"format": self.format, "anchors": self.anchors,
                "standings": [asdict(s) for s in self.standings], "games": self.games}


def default_name(c: PlayerConfig) -> str:
    if c.name:
        return c.name
    if c.type == "llm":
        base = c.model + (f"-{c.personality}" if c.personality else "")
        return base + ("+coach" if c.coach else "")
    if c.type == "stockfish":
        return f"stockfish-elo{c.elo}" if c.elo else f"stockfish-lvl{c.skill_level}" if c.skill_level is not None else "stockfish"
    return c.type


def load_players(path: str | Path) -> list[PlayerConfig]:
    data = yaml.safe_load(Path(path).read_text())
    cfgs = [PlayerConfig.model_validate(p) for p in data["players"]]
    for c in cfgs:  # give every entrant a unique, readable name
        c.name = default_name(c)
    names = [c.name for c in cfgs]
    if len(set(names)) != len(names):
        raise ValueError(f"player names must be unique, got {names}")
    return cfgs


def anchors_from(cfgs: list[PlayerConfig]) -> dict[str, float]:
    """Explicit `anchor_elo` wins; Stockfish players limited by UCI_Elo anchor at that Elo."""
    out: dict[str, float] = {}
    for c in cfgs:
        if c.anchor_elo is not None:
            out[c.name or default_name(c)] = c.anchor_elo
        elif c.type == "stockfish" and c.elo:
            out[c.name or default_name(c)] = float(c.elo)
    return out


# ---- pairing -----------------------------------------------------------------------------
def round_robin_pairs(names: list[str]) -> list[tuple[str, str]]:
    return list(itertools.combinations(names, 2))


def swiss_pairs(scores: dict[str, float], played: set[frozenset[str]],
                byes: Optional[set[str]] = None) -> tuple[list[tuple[str, str]], Optional[str]]:
    """Pair players by score (highest first), avoiding rematches when possible.
    Returns (pairs, bye) where bye is the lowest-ranked player who has not had one (odd fields)."""
    byes = byes or set()
    order = sorted(scores, key=lambda n: (-scores[n], n))
    bye: Optional[str] = None
    if len(order) % 2:
        bye = next((n for n in reversed(order) if n not in byes), order[-1])
        order.remove(bye)
    pairs: list[tuple[str, str]] = []
    pool = order[:]
    while pool:
        a = pool.pop(0)
        partner = next((b for b in pool if frozenset((a, b)) not in played), pool[0])
        pool.remove(partner)
        pairs.append((a, partner))
    return pairs, bye


# ---- running -----------------------------------------------------------------------------
def run_tournament(
    player_cfgs: list[PlayerConfig],
    games_per_pairing: int = 2,
    match_cfg: Optional[MatchConfig] = None,
    out_dir: str | Path = "games/tournaments",
    display: bool = False,
    anchors: Optional[dict[str, float]] = None,
    save_games: bool = True,
    fmt: str = "round_robin",
    rounds: Optional[int] = None,
    openings: Optional[list[list[str]]] = None,
    seed: Optional[int] = None,
    ci_samples: int = 200,
    on_game: Optional[Callable[[dict], None]] = None,
) -> TournamentResult:
    if fmt not in ("round_robin", "swiss"):
        raise ValueError(f"unknown tournament format '{fmt}'")
    if games_per_pairing % 2:
        games_per_pairing += 1  # even count => each side gets white equally
    for c in player_cfgs:
        c.name = c.name or default_name(c)
    anchors = {**anchors_from(player_cfgs), **(anchors or {})}
    players: dict[str, Player] = {c.name: build_player(c) for c in player_cfgs}  # type: ignore[misc]
    names = list(players)
    records: list[dict] = []
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    root = Path(out_dir) / stamp
    pairing_no = 0

    def play_pairing(a: str, b: str, rnd: int) -> None:
        nonlocal pairing_no
        from .openings import pick_opening
        for g in range(games_per_pairing):
            w, bl = (a, b) if g % 2 == 0 else (b, a)
            mc = (match_cfg or MatchConfig()).model_copy(deep=True)
            if openings:   # the colour-swapped pair of games shares one opening
                mc.opening_moves = pick_opening(openings, pairing_no * (games_per_pairing // 2) + g // 2, seed)
            cfg = GameConfig(
                match=mc,
                white=PlayerConfig(type="random"), black=PlayerConfig(type="random"),  # unused: players passed in
                output=OutputConfig(dir=str(root / "games"), save_pgn=save_games, save_jsonl=save_games,
                                    display="terminal" if display else "none", show_board=False),
            )
            res, d = run_game(cfg, white=players[w], black=players[bl])
            rec = {"round": rnd, "white": w, "black": bl, "result": res.result, "reason": res.reason,
                   "plies": res.plies, "opening": mc.opening_moves, "dir": str(d) if d else None}
            records.append(rec)
            if on_game:
                on_game(rec)
        pairing_no += 1

    try:
        if fmt == "round_robin":
            for a, b in round_robin_pairs(names):
                play_pairing(a, b, 1)
        else:
            n_rounds = rounds or max(1, min(len(names) - 1, 5))
            played: set[frozenset[str]] = set()
            byes: set[str] = set()
            scores = {n: 0.0 for n in names}
            for rnd in range(1, n_rounds + 1):
                pairs, bye = swiss_pairs(scores, played, byes)
                if bye:
                    byes.add(bye)
                for a, b in pairs:
                    before = len(records)
                    play_pairing(a, b, rnd)
                    played.add(frozenset((a, b)))
                    for r in records[before:]:
                        s = score_from_result(r["result"])
                        if s is not None:
                            scores[r["white"]] += s
                            scores[r["black"]] += 1 - s
    finally:
        for p in players.values():
            p.close()

    scored = [(r["white"], r["black"], s) for r in records if (s := score_from_result(r["result"])) is not None]
    ratings = compute_ratings(scored, anchors=anchors)
    cis = bootstrap_ci(scored, anchors=anchors, samples=ci_samples, seed=seed or 0) if ci_samples else {}
    table = {n: Standing(n, elo=ratings.get(n, 1000.0)) for n in players}
    for n, (lo, hi) in cis.items():
        table[n].elo_lo, table[n].elo_hi = lo, hi
    for w, b, s in scored:
        for name, pts in ((w, s), (b, 1 - s)):
            st = table[name]
            st.games += 1
            st.points += pts
            st.wins += pts == 1
            st.draws += pts == 0.5
            st.losses += pts == 0
    standings = sorted(table.values(), key=lambda s: (-s.points, -s.elo))
    result = TournamentResult(standings, records, fmt, anchors)
    root.mkdir(parents=True, exist_ok=True)
    (root / "leaderboard.md").write_text(result.leaderboard_md())
    (root / "results.json").write_text(json.dumps(result.to_json(), indent=2))
    result.dir = str(root)  # type: ignore[attr-defined]
    return result
