import sys

import chess
import chess.engine
import pytest

from aichess.config import parse_player_spec
from aichess.elo import compute_ratings, expected, update
from aichess.players.base import MoveContext
from aichess.players.factory import build_player
from aichess.players.greedy import GreedyPlayer
from aichess.players.stockfish import StockfishPlayer


def test_spec_parsing():
    c = parse_player_spec("llm:claude-opus-5-5")
    assert (c.type, c.model) == ("llm", "claude-opus-5-5")
    c = parse_player_spec("stockfish:level=8,movetime=0.1")
    assert (c.skill_level, c.movetime) == (8, 0.1)
    assert parse_player_spec("stockfish:elo=1500").elo == 1500
    assert parse_player_spec("random:seed=3").seed == 3
    with pytest.raises(ValueError):
        parse_player_spec("random:oops")
    with pytest.raises(Exception):
        parse_player_spec("stockfish:level=99")
    with pytest.raises(Exception):
        parse_player_spec("alien")


def test_factory_builds_each_type(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert build_player(parse_player_spec("random")).name == "random"
    assert build_player(parse_player_spec("greedy")).name == "greedy"
    assert build_player(parse_player_spec("llm:claude-haiku-5-5")).name == "claude-haiku-5-5"


def test_greedy_takes_free_queen_and_mates():
    b = chess.Board("4k3/8/8/3q4/4P3/8/8/4K3 w - - 0 1")
    assert GreedyPlayer(0).choose_move(b, MoveContext(1, [])).move.uci() == "e4d5"
    mate = chess.Board("6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1")
    assert GreedyPlayer(0).choose_move(mate, MoveContext(1, [])).move.uci() == "a1a8"


def test_stockfish_missing_binary_gives_helpful_error(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(FileNotFoundError, match="brew install stockfish"):
        StockfishPlayer()


def test_stockfish_player_with_stub_engine(monkeypatch):
    class StubEngine:
        options = {"Threads": 1, "Skill Level": 1}

        def __init__(self): self.configured, self.quit_called = None, False
        def configure(self, o): self.configured = o
        def play(self, board, limit, info=None):
            return chess.engine.PlayResult(next(iter(board.legal_moves)), None,
                                           {"score": chess.engine.PovScore(chess.engine.Cp(35), chess.WHITE)})
        def quit(self): self.quit_called = True

    stub = StubEngine()
    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", staticmethod(lambda path: stub))
    with StockfishPlayer(path=sys.executable, skill_level=5) as p:
        res = p.choose_move(chess.Board(), MoveContext(1, []))
        assert res.info["eval_cp"] == 35
    assert stub.configured == {"Threads": 1, "Skill Level": 5}  # unsupported options filtered out
    assert stub.quit_called


def test_elo_math():
    assert expected(1000, 1000) == 0.5
    a, b = update(1000, 1000, 1.0, k=32)
    assert (a, b) == (1016, 984)
    r = compute_ratings([("a", "b", 1.0)] * 5 + [("b", "a", 0.0)] * 5)
    assert r["a"] > 1000 > r["b"]
    anchored = compute_ratings([("a", "sf", 0.0)] * 4, anchors={"sf": 1500})
    assert anchored["sf"] == pytest.approx(1500) and anchored["a"] < 1500
