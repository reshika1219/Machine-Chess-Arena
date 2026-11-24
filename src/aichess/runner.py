"""Glue: build players, wire observers, run one game."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Callable, Optional

from .config import GameConfig
from .events import EventBus
from .match import GameResult, Match
from .observers.jsonl_logger import JsonlLogger
from .observers.pgn_writer import PgnWriter
from .observers.terminal import TerminalObserver
from .players.base import Player
from .players.factory import build_player
from .players.llm import LLMPlayer


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")


def run_game(
    cfg: GameConfig,
    extra_observers: Optional[list[Callable]] = None,
    white: Optional[Player] = None,
    black: Optional[Player] = None,
) -> tuple[GameResult, Optional[Path]]:
    """Play one game. Pre-built players may be passed (tournaments reuse engines)."""
    own = white is None and black is None
    white = white or build_player(cfg.white)
    black = black or build_player(cfg.black)
    bus = EventBus()
    out_dir: Optional[Path] = None
    if cfg.output.save_pgn or cfg.output.save_jsonl:
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        out_dir = Path(cfg.output.dir) / f"{stamp}_{_slug(white.name)}_vs_{_slug(black.name)}"
        if cfg.output.save_pgn:
            bus.subscribe(PgnWriter(out_dir / "game.pgn"))
        if cfg.output.save_jsonl:
            bus.subscribe(JsonlLogger(out_dir))
    if cfg.output.display == "terminal":
        bus.subscribe(TerminalObserver(cfg.output.show_board))
    for obs in extra_observers or []:
        bus.subscribe(obs)
    if cfg.commentary:
        from .observers.commentator import Commentator
        c = cfg.commentary
        bus.subscribe(Commentator(bus.emit, LLMPlayer(model=c.model).client, c.model, c.every, c.style, c.max_tokens))
    try:
        return Match(white, black, cfg.match, bus).play(), out_dir
    finally:
        if own:
            white.close()
            black.close()
