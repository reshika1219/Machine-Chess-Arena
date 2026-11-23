import chess
import chess.pgn
import io

from aichess.config import MatchConfig
from aichess.events import EventBus, GameOver, MoveEvent
from aichess.match import Match
from aichess.observers.pgn_writer import PgnWriter
from aichess.players.greedy import GreedyPlayer
from aichess.players.random_player import RandomPlayer
from conftest import BrokenPlayer, ScriptedPlayer


def test_fools_mate_black_wins():
    w = ScriptedPlayer(["f2f3", "g2g4"], "w")
    b = ScriptedPlayer(["e7e5", "d8h4"], "b")
    r = Match(w, b).play()
    assert (r.result, r.reason, r.plies) == ("0-1", "checkmate", 4)


def test_stalemate_detected():
    start = "7k/8/6K1/8/8/8/8/5Q2 w - - 0 1"  # Qf1-f7 stalemates the black king on h8
    r = Match(ScriptedPlayer(["f1f7"]), ScriptedPlayer([]), MatchConfig(start_fen=start)).play()
    assert r.result == "1/2-1/2" and r.reason == "stalemate"


def test_threefold_repetition():
    w = ScriptedPlayer(["g1f3", "f3g1"] * 3)
    b = ScriptedPlayer(["g8f6", "f6g8"] * 3)
    r = Match(w, b).play()
    assert r.result == "1/2-1/2" and r.reason == "threefold_repetition"


def test_insufficient_material():
    r = Match(ScriptedPlayer([]), ScriptedPlayer([]),
              MatchConfig(start_fen="8/8/4k3/8/8/4K3/8/8 w - - 0 1")).play()
    assert r.result == "1/2-1/2" and r.reason == "insufficient_material"


def test_promotion_is_playable():
    start = "8/P6k/8/8/8/8/8/K7 w - - 0 1"
    events = []
    bus = EventBus(); bus.subscribe(events.append)
    Match(ScriptedPlayer(["a7a8q"]), ScriptedPlayer([]), MatchConfig(start_fen=start, max_plies=2), bus).play()
    moves = [e for e in events if isinstance(e, MoveEvent)]
    assert moves[0].san.startswith("a8=Q")


def test_max_plies_draw():
    r = Match(RandomPlayer(1), RandomPlayer(2), MatchConfig(max_plies=10)).play()
    assert r.plies <= 10 and (r.reason == "max_plies" or r.result != "*")


def test_illegal_moves_forfeit_after_retries():
    bad = BrokenPlayer()
    r = Match(bad, RandomPlayer(1), MatchConfig(illegal_move_retries=2, on_failure="forfeit")).play()
    assert r.result == "0-1" and r.reason == "forfeit_illegal_moves"
    assert bad.calls == 3 and r.illegal_attempts["white"] == 3
    assert bad.feedback_seen[0] is None and "not a legal move" in bad.feedback_seen[1]


def test_unparseable_reply_is_retried_then_random_fallback():
    bad = BrokenPlayer(raises=True)
    events = []
    bus = EventBus(); bus.subscribe(events.append)
    r = Match(bad, RandomPlayer(1), MatchConfig(illegal_move_retries=1, on_failure="random_move", max_plies=4, seed=1), bus).play()
    first = [e for e in events if isinstance(e, MoveEvent)][0]
    assert first.fallback is True and r.fallbacks["white"] >= 1 and r.result != "0-1"


def test_player_cannot_corrupt_board():
    class Mutator(RandomPlayer):
        def choose_move(self, board, ctx):
            res = super().choose_move(board, ctx)
            board.push(list(board.legal_moves)[0])  # tamper with the copy we were handed
            return res
    r = Match(Mutator(1), RandomPlayer(2), MatchConfig(max_plies=6)).play()
    assert r.plies == 6


def test_timeout_counts_as_failed_attempt():
    import time

    class Slow(RandomPlayer):
        def choose_move(self, board, ctx):
            time.sleep(0.3)
            return super().choose_move(board, ctx)

    r = Match(Slow(1), RandomPlayer(2),
              MatchConfig(move_timeout_seconds=0.05, illegal_move_retries=0, on_failure="forfeit")).play()
    assert r.reason == "forfeit_illegal_moves" and r.result == "0-1"


def test_pgn_replay_reproduces_final_fen(tmp_path):
    for seed in range(5):
        path = tmp_path / f"g{seed}.pgn"
        bus = EventBus(); bus.subscribe(PgnWriter(path))
        r = Match(GreedyPlayer(seed), RandomPlayer(seed + 100), bus=bus).play()
        game = chess.pgn.read_game(io.StringIO(path.read_text()))
        assert game.end().board().fen() == r.final_fen
        assert game.headers["Result"] == r.result


def test_random_vs_random_always_terminates_validly():
    for seed in range(25):
        r = Match(RandomPlayer(seed), RandomPlayer(seed + 1000), MatchConfig(max_plies=400)).play()
        assert r.result in {"1-0", "0-1", "1/2-1/2"}


def test_clock_flag_loses_on_time():
    import time

    class Slow(RandomPlayer):
        def choose_move(self, board, ctx):
            time.sleep(0.06)
            return super().choose_move(board, ctx)

    r = Match(Slow(1), RandomPlayer(2), MatchConfig(clock_seconds=0.1)).play()
    assert r.reason == "timeout" and r.result == "0-1"


def test_random_opening_is_in_pgn_and_seeded(tmp_path):
    results = []
    for _ in range(2):
        path = tmp_path / "o.pgn"
        bus = EventBus(); bus.subscribe(PgnWriter(path))
        m = Match(RandomPlayer(1), RandomPlayer(2), MatchConfig(random_opening_plies=6, seed=7, max_plies=10), bus)
        r = m.play()
        game = chess.pgn.read_game(io.StringIO(path.read_text()))
        assert game.end().board().fen() == r.final_fen
        assert "FEN" not in game.headers          # record starts from the normal start position
        results.append(m.prior_moves)
    assert len(results[0]) == 6 and results[0] == results[1]


def test_resume_from_pgn(tmp_path):
    path = tmp_path / "first.pgn"
    bus = EventBus(); bus.subscribe(PgnWriter(path))
    Match(RandomPlayer(1), RandomPlayer(2), MatchConfig(max_plies=8), bus).play()
    events = []
    bus2 = EventBus(); bus2.subscribe(events.append)
    r = Match(RandomPlayer(3), RandomPlayer(4), MatchConfig(start_pgn=str(path), max_plies=12), bus2).play()
    start = events[0]
    assert len(start.prior_moves) == 8 and r.plies <= 12
    assert [e for e in events if isinstance(e, MoveEvent)][0].ply == 9
