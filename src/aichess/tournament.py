"""Round-robin tournament with alternating colours, Elo and a markdown leaderboard."""
from __future__ import annotations

import datetime as dt
import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .config import GameConfig, MatchConfig, OutputConfig, PlayerConfig
from .elo import compute_ratings, score_from_result
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


@dataclass
class TournamentResult:
    standings: list[Standing]
    games: list[dict] = field(default_factory=list)

    def leaderboard_md(self) -> str:
        rows = ["| # | Player | Elo | Pts | G | W | D | L |", "|---|---|---|---|---|---|---|---|"]
        for i, s in enumerate(self.standings, 1):
            rows.append(f"| {i} | {s.name} | {s.elo:.0f} | {s.points:g} | {s.games} | {s.wins} | {s.draws} | {s.losses} |")
        return "\n".join(rows) + "\n"


def load_players(path: str | Path) -> list[PlayerConfig]:
    data = yaml.safe_load(Path(path).read_text())
    cfgs = [PlayerConfig.model_validate(p) for p in data["players"]]
    for c in cfgs:  # give every entrant a unique, readable name
        c.name = c.name or (c.model if c.type == "llm" else
                            f"stockfish-lvl{c.skill_level}" if c.type == "stockfish" and c.skill_level is not None else
                            f"stockfish-elo{c.elo}" if c.type == "stockfish" and c.elo else c.type)
    names = [c.name for c in cfgs]
    if len(set(names)) != len(names):
        raise ValueError(f"player names must be unique, got {names}")
    return cfgs


def run_tournament(
    player_cfgs: list[PlayerConfig],
    games_per_pairing: int = 2,
    match_cfg: Optional[MatchConfig] = None,
    out_dir: str | Path = "games/tournaments",
    display: bool = False,
    anchors: Optional[dict[str, float]] = None,
    save_games: bool = True,
) -> TournamentResult:
    if games_per_pairing % 2:
        games_per_pairing += 1  # even count => each side gets white equally
    players: dict[str, Player] = {c.name: build_player(c) for c in player_cfgs}  # type: ignore[misc]
    records: list[dict] = []
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    root = Path(out_dir) / stamp
    try:
        for a, b in itertools.combinations(players, 2):
            for g in range(games_per_pairing):
                w, bl = (a, b) if g % 2 == 0 else (b, a)
                cfg = GameConfig(
                    match=match_cfg or MatchConfig(),
                    white=PlayerConfig(type="random"), black=PlayerConfig(type="random"),  # unused: players passed in
                    output=OutputConfig(dir=str(root / "games"), save_pgn=save_games, save_jsonl=save_games,
                                        display="terminal" if display else "none", show_board=False),
                )
                res, d = run_game(cfg, white=players[w], black=players[bl])
                records.append({"white": w, "black": bl, "result": res.result, "reason": res.reason,
                                "plies": res.plies, "dir": str(d) if d else None})
    finally:
        for p in players.values():
            p.close()

    scored = [(r["white"], r["black"], s) for r in records if (s := score_from_result(r["result"])) is not None]
    ratings = compute_ratings(scored, anchors=anchors)
    table = {n: Standing(n, elo=ratings.get(n, 1000.0)) for n in players}
    for w, b, s in scored:
        for name, pts in ((w, s), (b, 1 - s)):
            st = table[name]
            st.games += 1
            st.points += pts
            st.wins += pts == 1
            st.draws += pts == 0.5
            st.losses += pts == 0
    standings = sorted(table.values(), key=lambda s: (-s.points, -s.elo))
    result = TournamentResult(standings, records)
    root.mkdir(parents=True, exist_ok=True)
    (root / "leaderboard.md").write_text(result.leaderboard_md())
    (root / "results.json").write_text(json.dumps(records, indent=2))
    return result
