from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..events import Commentary, GameOver, GameStart, MoveEvent


class JsonlLogger:
    """One JSON line per move + a summary.json when the game ends."""

    def __init__(self, directory: Path) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.moves_path = self.dir / "moves.jsonl"
        self.moves_path.write_text("")
        self.players: tuple[str, str] = ("?", "?")
        self.total_seconds = 0.0
        self.tokens = {"input": 0, "output": 0}
        self.retries = 0
        self.cost = {"white": 0.0, "black": 0.0}

    def __call__(self, ev: object) -> None:
        if isinstance(ev, GameStart):
            self.players = (ev.white, ev.black)
        elif isinstance(ev, MoveEvent):
            self.total_seconds += ev.seconds
            self.retries += ev.retries
            self.tokens["input"] += ev.info.get("input_tokens", 0)
            self.tokens["output"] += ev.info.get("output_tokens", 0)
            self.cost[ev.side] += ev.info.get("cost_usd", 0.0)
            with self.moves_path.open("a") as f:
                f.write(json.dumps(asdict(ev)) + "\n")
        elif isinstance(ev, Commentary):
            with (self.dir / "commentary.jsonl").open("a") as f:
                f.write(json.dumps(asdict(ev)) + "\n")
        elif isinstance(ev, GameOver):
            summary = {
                "white": self.players[0], "black": self.players[1],
                "result": ev.result, "reason": ev.reason, "plies": ev.plies,
                "final_fen": ev.final_fen, "total_move_seconds": round(self.total_seconds, 2),
                "retries": self.retries, "tokens": self.tokens,
                "cost_usd": {**{k: round(v, 6) for k, v in self.cost.items()}, "total": round(sum(self.cost.values()), 6)},
            }
            (self.dir / "summary.json").write_text(json.dumps(summary, indent=2))
