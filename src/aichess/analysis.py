"""Post-game analysis: average centipawn loss and a 0-100 accuracy score per side."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import chess
import chess.engine
import chess.pgn

CLAMP = 1000  # ignore swings beyond +-10 pawns (mate scores are mapped to +-10000 then clamped)


@dataclass
class SideReport:
    moves: int = 0
    acpl: float = 0.0         # average centipawn loss (lower is better)
    accuracy: float = 0.0     # 0-100 (higher is better), Lichess-style win% formula
    blunders: int = 0         # win% drop >= 20 points
    mistakes: int = 0         # win% drop 10-20
    inaccuracies: int = 0     # win% drop 5-10


@dataclass
class GameReport:
    white: SideReport
    black: SideReport
    evals: list[int]          # White-POV centipawns after each ply (index 0 = start position)


def win_percent(cp: float) -> float:
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def _move_accuracy(drop: float) -> float:
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * drop) - 3.1669))


def analyse_game(game: chess.pgn.Game, engine: Any, limit: chess.engine.Limit) -> GameReport:
    board = game.board()
    evals: list[int] = []

    def evaluate(b: chess.Board) -> int:
        if b.is_game_over():
            o = b.outcome()
            return 0 if o.winner is None else (CLAMP if o.winner == chess.WHITE else -CLAMP)
        info = engine.analyse(b, limit)
        cp = info["score"].white().score(mate_score=10000)
        return max(-CLAMP, min(CLAMP, cp))

    evals.append(evaluate(board))
    movers: list[chess.Color] = []
    for node in game.mainline():
        movers.append(board.turn)
        board.push(node.move)
        evals.append(evaluate(board))

    sides = {chess.WHITE: SideReport(), chess.BLACK: SideReport()}
    totals = {chess.WHITE: [0.0, 0.0], chess.BLACK: [0.0, 0.0]}  # cp loss sum, accuracy sum
    for i, color in enumerate(movers):
        before, after = evals[i], evals[i + 1]
        sign = 1 if color == chess.WHITE else -1
        cp_loss = max(0, sign * (before - after))
        drop = max(0.0, sign * (win_percent(before) - win_percent(after)))
        r = sides[color]
        r.moves += 1
        totals[color][0] += cp_loss
        totals[color][1] += _move_accuracy(drop)
        if drop >= 20:
            r.blunders += 1
        elif drop >= 10:
            r.mistakes += 1
        elif drop >= 5:
            r.inaccuracies += 1
    for color, r in sides.items():
        if r.moves:
            r.acpl = totals[color][0] / r.moves
            r.accuracy = totals[color][1] / r.moves
    return GameReport(sides[chess.WHITE], sides[chess.BLACK], evals)


def format_report(game: chess.pgn.Game, rep: GameReport) -> str:
    h = game.headers
    rows = [f"| Side | Player | Moves | ACPL | Accuracy | Blunders | Mistakes | Inaccuracies |",
            "|---|---|---|---|---|---|---|---|"]
    for side, name, r in (("White", h.get("White", "?"), rep.white), ("Black", h.get("Black", "?"), rep.black)):
        rows.append(f"| {side} | {name} | {r.moves} | {r.acpl:.0f} | {r.accuracy:.1f} | {r.blunders} | {r.mistakes} | {r.inaccuracies} |")
    return "\n".join(rows)
