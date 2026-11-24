import chess
import pytest

from aichess.config import MatchConfig
from aichess.match import Match
from aichess.openings import BUILTIN, load_openings, pick_opening, san_line_to_uci
from aichess.players.random_player import RandomPlayer


def test_builtin_book_is_legal_and_varied():
    lines = load_openings("builtin")
    assert len(lines) == len(BUILTIN)
    for ln in lines:
        b = chess.Board()
        for u in ln:
            b.push_uci(u)          # raises if illegal
    assert len({tuple(l) for l in lines}) == len(lines)


def test_san_parsing_accepts_move_numbers_and_uci():
    assert san_line_to_uci("1. e4 e5 2. Nf3") == ["e2e4", "e7e5", "g1f3"]
    assert san_line_to_uci("e2e4 e7e5") == ["e2e4", "e7e5"]
    with pytest.raises(ValueError):
        san_line_to_uci("e4 e5 Qh8")


def test_file_formats(tmp_path):
    t = tmp_path / "book.txt"
    t.write_text("# my book\nSicilian: e4 c5\n\nd4 d5 c4  # QG\n")
    assert load_openings(str(t)) == [["e2e4", "c7c5"], ["d2d4", "d7d5", "c2c4"]]
    assert load_openings(str(t), max_plies=2)[1] == ["d2d4", "d7d5"]
    p = tmp_path / "s.pgn"
    p.write_text('[Event "x"]\n\n1. e4 e5 2. Nf3 *\n\n[Event "y"]\n\n1. c4 *\n')
    assert load_openings(str(p)) == [["e2e4", "e7e5", "g1f3"], ["c2c4"]]
    with pytest.raises(FileNotFoundError):
        load_openings(str(tmp_path / "nope.txt"))


def test_pick_is_deterministic_and_cycles():
    ops = load_openings("builtin")
    assert pick_opening(ops, 3, seed=5) == pick_opening(ops, 3, seed=5)
    assert pick_opening(ops, 0, 5) == pick_opening(ops, len(ops), 5)
    assert len({tuple(pick_opening(ops, i, 5)) for i in range(len(ops))}) == len(ops)


def test_match_plays_opening_then_players_continue():
    cfg = MatchConfig(opening_moves=["e2e4", "e7e5", "g1f3"], max_plies=8)
    m = Match(RandomPlayer(1), RandomPlayer(2), cfg)
    assert m.prior_moves == ["e2e4", "e7e5", "g1f3"] and m.board.turn == chess.BLACK
    assert m.play().plies == 8
    with pytest.raises(ValueError):
        Match(RandomPlayer(), RandomPlayer(), MatchConfig(opening_moves=["e2e5"]))
