"""Typed configuration (pydantic) + the `type:arg,key=val` player shorthand used by the CLI."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field


class MatchConfig(BaseModel):
    max_plies: int = 300
    move_timeout_seconds: float = 60
    illegal_move_retries: int = 3
    on_failure: Literal["forfeit", "random_move"] = "forfeit"
    start_fen: Optional[str] = None
    seed: Optional[int] = None
    clock_seconds: Optional[float] = None      # total thinking time per side (flag = loss on time)
    random_opening_plies: int = 0              # play N random legal plies first so games differ
    start_pgn: Optional[str] = None            # resume/continue from a saved PGN (mainline)
    chess960: bool = False                     # Fischer Random start position
    chess960_position: Optional[int] = Field(default=None, ge=0, le=959)  # None = random (seeded)
    # Handicaps. clock_seconds_{white,black} override clock_seconds for that side (time odds).
    clock_seconds_white: Optional[float] = None
    clock_seconds_black: Optional[float] = None
    # Material odds: "black:q" removes Black's queen; letters q r b n p, e.g. "white:qn".
    material_odds: Optional[str] = None


class PlayerConfig(BaseModel):
    type: Literal["llm", "stockfish", "random", "greedy"]
    name: Optional[str] = None
    # llm
    model: str = "claude-sonnet-5-5"
    temperature: Optional[float] = None
    max_tokens: int = 1024
    show_legal_moves: bool = True
    personality: Optional[str] = None          # balanced | aggressive | positional | cautious | tactician | endgame
    price_in_per_mtok: Optional[float] = None  # USD per million input tokens (enables cost tracking)
    price_out_per_mtok: Optional[float] = None
    coach: bool = False                        # let the LLM call Stockfish as a tool
    coach_movetime: float = 0.3
    coach_path: Optional[str] = None
    max_tool_calls: int = 4
    budget_usd: Optional[float] = None         # stop (forfeit) once this player has spent this much
    # stockfish
    path: Optional[str] = None
    skill_level: Optional[int] = Field(default=None, ge=0, le=20)
    elo: Optional[int] = None
    movetime: float = 0.2
    depth: Optional[int] = None
    # random / greedy
    seed: Optional[int] = None


class OutputConfig(BaseModel):
    dir: str = "games"
    save_pgn: bool = True
    save_jsonl: bool = True
    display: Literal["terminal", "web", "none"] = "terminal"
    show_board: bool = True


class GameConfig(BaseModel):
    match: MatchConfig = MatchConfig()
    white: PlayerConfig
    black: PlayerConfig
    output: OutputConfig = OutputConfig()


def load_game_config(path: str | Path) -> GameConfig:
    return GameConfig.model_validate(yaml.safe_load(Path(path).read_text()))


_ALIASES = {"level": "skill_level", "lvl": "skill_level"}


def parse_player_spec(spec: str) -> PlayerConfig:
    """'llm:claude-opus-5-5' | 'stockfish:level=8' | 'stockfish:elo=1500,movetime=0.1' | 'random'"""
    kind, _, rest = spec.partition(":")
    data: dict = {"type": kind.strip()}
    for item in filter(None, (s.strip() for s in rest.split(","))):
        if "=" in item:
            k, v = item.split("=", 1)
            data[_ALIASES.get(k.strip(), k.strip())] = v.strip()
        elif kind == "llm":
            data["model"] = item
        elif kind == "stockfish":
            data["path"] = item
        else:
            raise ValueError(f"unexpected positional argument '{item}' in '{spec}'")
    return PlayerConfig.model_validate(data)  # pydantic coerces "8" -> 8
