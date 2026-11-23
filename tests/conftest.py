from __future__ import annotations

import chess
import pytest

from aichess.players.base import MoveContext, MoveResult, Player


class ScriptedPlayer(Player):
    """Plays a fixed list of UCI moves, then falls back to the first legal move."""

    def __init__(self, moves: list[str], name: str = "scripted") -> None:
        self.moves, self.name, self.i = list(moves), name, 0
        self.calls = 0

    def choose_move(self, board: chess.Board, ctx: MoveContext) -> MoveResult:
        self.calls += 1
        if self.i < len(self.moves):
            m = chess.Move.from_uci(self.moves[self.i])
            self.i += 1
            return MoveResult(m)
        return MoveResult(next(iter(board.legal_moves)))


class BrokenPlayer(Player):
    """Always proposes an illegal move (or raises), to test the referee."""

    def __init__(self, raises: bool = False) -> None:
        self.name, self.raises, self.calls = "broken", raises, 0
        self.feedback_seen: list[str | None] = []

    def choose_move(self, board: chess.Board, ctx: MoveContext) -> MoveResult:
        self.calls += 1
        self.feedback_seen.append(ctx.feedback)
        if self.raises:
            raise ValueError("no <move> tag")
        return MoveResult(chess.Move.from_uci("a1a8"))  # illegal at the start


@pytest.fixture
def scripted():
    return ScriptedPlayer
