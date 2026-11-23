import io

import chess
import chess.engine
import chess.pgn

from aichess.analysis import analyse_game, format_report, win_percent


class ScriptedEngine:
    """Returns pre-set White-POV centipawn evals in the order positions are analysed."""

    def __init__(self, evals):
        self.evals = list(evals)

    def analyse(self, board, limit):
        return {"score": chess.engine.PovScore(chess.engine.Cp(self.evals.pop(0)), chess.WHITE)}


def game(pgn: str) -> chess.pgn.Game:
    return chess.pgn.read_game(io.StringIO(pgn))


def test_blunder_is_detected_for_the_right_side():
    g = game("1. e4 e5 2. Qh5 Nc6 *")
    # start, after e4, after e5, after Qh5, after Nc6  (White POV)
    rep = analyse_game(g, ScriptedEngine([20, 20, 20, 20, 900]), chess.engine.Limit(time=0.01))
    assert rep.white.blunders == 0 and rep.white.acpl == 0
    assert rep.black.blunders == 1 and rep.black.acpl > 200   # Black's last move lost 880cp
    assert rep.black.accuracy < rep.white.accuracy
    assert "| Black |" in format_report(g, rep)


def test_perfect_play_is_100_accuracy():
    g = game("1. e4 e5 *")
    rep = analyse_game(g, ScriptedEngine([0, 0, 0]), chess.engine.Limit(time=0.01))
    assert rep.white.accuracy > 99 and rep.black.accuracy > 99


def test_game_over_positions_do_not_call_engine():
    g = game("1. f3 e5 2. g4 Qh4# 0-1")
    rep = analyse_game(g, ScriptedEngine([0, 0, 0, 0, 0]), chess.engine.Limit(time=0.01))  # mate pos not analysed
    assert rep.evals[-1] == -1000


def test_win_percent_is_monotonic_and_centered():
    assert abs(win_percent(0) - 50) < 1e-9
    assert win_percent(300) > win_percent(100) > 50 > win_percent(-100)
