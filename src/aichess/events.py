"""Event types and a tiny pub/sub bus. Observers subscribe; the Match publishes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class GameStart:
    white: str
    black: str
    fen: str                                   # position the game record starts from
    prior_moves: list[str] = field(default_factory=list)   # UCI moves already played (opening / resumed PGN)
    fen_now: str = ""                          # position after prior_moves
    chess960: bool = False
    clock_seconds: dict[str, Optional[float]] = field(default_factory=dict)  # starting clock per side
    handicap: str = ""                         # human-readable handicap description


@dataclass
class MoveEvent:
    ply: int
    side: str  # "white" | "black"
    player: str
    fen_before: str
    uci: str
    san: str
    fen_after: str
    seconds: float = 0.0
    retries: int = 0
    fallback: bool = False
    info: dict[str, Any] = field(default_factory=dict)  # tokens, reasoning, ...


@dataclass
class GameOver:
    result: str  # "1-0" | "0-1" | "1/2-1/2" | "*"
    reason: str
    plies: int
    final_fen: str


class EventBus:
    def __init__(self) -> None:
        self._subs: list[Callable[[Any], None]] = []

    def subscribe(self, fn: Callable[[Any], None]) -> None:
        self._subs.append(fn)

    def emit(self, event: Any) -> None:
        for fn in self._subs:
            fn(event)
