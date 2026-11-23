from __future__ import annotations

import random
from typing import Optional

import chess

from .base import MoveContext, MoveResult, Player


class RandomPlayer(Player):
    """Uniformly random legal move. The sanity-check baseline."""

    def __init__(self, seed: Optional[int] = None) -> None:
        self.name = "random"
        self.rng = random.Random(seed)

    def choose_move(self, board: chess.Board, ctx: MoveContext) -> MoveResult:
        return MoveResult(self.rng.choice(list(board.legal_moves)))
