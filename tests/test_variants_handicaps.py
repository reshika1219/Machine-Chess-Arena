import chess
import chess.pgn
import pytest

from aichess.config import MatchConfig
from aichess.events import EventBus, GameStart
from aichess.handicap import apply_material_odds, parse_material_odds
from aichess.match import Match
from aichess.observers.pgn_writer import PgnWriter
from aichess.players.greedy import GreedyPlayer
from aichess.players.random_player import RandomPlayer


def test_chess960_fixed_position_and_pgn_roundtrip(tmp_path):
    path = tmp_path / "g.pgn"
    bus = EventBus(); bus.subscribe(PgnWriter(path))
    cfg = MatchConfig(chess960=True, chess960_position=518, max_plies=40)  # 518 = standard setup
    res = Match(RandomPlayer(1), RandomPlayer(2), cfg, bus).play()
    game = chess.pgn.read_game(open(path))
    assert game.headers["Variant"] == "Chess960"
    board = game.board()
    assert board.chess960
    for n in game.mainline():
        board.push(n.move)
    assert board.fen() == res.final_fen


def test_chess960_random_position_is_seeded_and_varies():
    fen = lambda seed: Match(RandomPlayer(), RandomPlayer(), MatchConfig(chess960=True, seed=seed)).base_fen
    assert fen(1) == fen(1)
    assert len({fen(s) for s in range(10)}) > 1


def test_chess960_games_terminate_validly():
    for s in range(5):
        res = Match(RandomPlayer(s), GreedyPlayer(s), MatchConfig(chess960=True, seed=s, max_plies=120)).play()
        assert res.result in {"1-0", "0-1", "1/2-1/2"}


def test_material_odds_removes_pieces():
    b = chess.Board()
    apply_material_odds(b, "black:q")
    assert not b.pieces(chess.QUEEN, chess.BLACK) and b.pieces(chess.QUEEN, chess.WHITE)
    b = chess.Board()
    apply_material_odds(b, "white:rn")   # outermost rook -> a1, castling right dropped
    assert len(b.pieces(chess.ROOK, chess.WHITE)) == 1 and len(b.pieces(chess.KNIGHT, chess.WHITE)) == 1
    assert b.is_valid()


@pytest.mark.parametrize("spec", ["black", "grey:q", "black:x", ""])
def test_bad_odds_rejected(spec):
    with pytest.raises(ValueError):
        parse_material_odds(spec)


def test_odds_and_time_odds_reported_in_start_event_and_pgn(tmp_path):
    events = []
    bus = EventBus(); bus.subscribe(events.append); bus.subscribe(PgnWriter(tmp_path / "g.pgn"))
    cfg = MatchConfig(material_odds="black:q", clock_seconds=100, clock_seconds_black=20, max_plies=6)
    Match(RandomPlayer(1), RandomPlayer(2), cfg, bus).play()
    start = next(e for e in events if isinstance(e, GameStart))
    assert start.clock_seconds == {"white": 100, "black": 20}
    assert "material odds" in start.handicap and "time odds" in start.handicap
    game = chess.pgn.read_game(open(tmp_path / "g.pgn"))
    assert "Handicap" in game.headers and "FEN" in game.headers
