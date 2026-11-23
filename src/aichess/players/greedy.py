from __future__ import annotations

import random
from typing import Optional

import chess

from .base import MoveContext, MoveResult, Player

VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


class GreedyPlayer(Player):
    """Maximises immediate material gain; mates when it sees one; otherwise random."""

    def __init__(self, seed: Optional[int] = None) -> None:
        self.name = "greedy"
        self.rng = random.Random(seed)

    def _score(self, board: chess.Board, move: chess.Move) -> float:
        score = 0.0
        if board.is_capture(move):
            if board.is_en_passant(move):
                score += 1
            else:
                score += VALUES[board.piece_at(move.to_square).piece_type]
        if move.promotion:
            score += VALUES[move.promotion] - 1
        board.push(move)
        try:
            if board.is_checkmate():
                score += 1000
            elif board.is_check():
                score += 0.5
            # don't hang the moved piece to a cheaper attacker
            elif board.is_attacked_by(board.turn, move.to_square):
                moved = board.piece_at(move.to_square)
                if moved:
                    score -= VALUES[moved.piece_type] * 0.5
        finally:
            board.pop()
        return score

    def choose_move(self, board: chess.Board, ctx: MoveContext) -> MoveResult:
        moves = list(board.legal_moves)
        scored = [(self._score(board, m), m) for m in moves]
        best = max(s for s, _ in scored)
        return MoveResult(self.rng.choice([m for s, m in scored if s == best]))
