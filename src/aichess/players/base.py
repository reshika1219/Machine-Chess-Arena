"""The Player interface: the only thing the referee knows about an AI."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

import chess


@dataclass
class MoveContext:
    """Extra info passed to a player on each turn."""
    ply: int
    history_san: list[str]
    # Feedback from rejected attempts this turn (used by LLM players to correct themselves)
    feedback: Optional[str] = None
    attempt: int = 0


@dataclass
class MoveResult:
    move: chess.Move
    info: dict[str, Any] = field(default_factory=dict)  # tokens, raw reply, ...


class Player(ABC):
    name: str = "player"

    @abstractmethod
    def choose_move(self, board: chess.Board, ctx: MoveContext) -> MoveResult:
        """Return a proposed move. The referee validates it; never mutate `board`."""

    def close(self) -> None:  # engines/clients override
        pass

    def __enter__(self) -> "Player":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
