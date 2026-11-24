import pytest

from aichess.config import MatchConfig, PlayerConfig
from aichess.elo import bootstrap_ci, compute_ratings
from aichess.openings import load_openings
from aichess.tournament import anchors_from, run_tournament, swiss_pairs


def test_swiss_pairs_by_score_avoid_rematches_and_give_bye():
    scores = {"a": 2, "b": 2, "c": 1, "d": 0}
    pairs, bye = swiss_pairs(scores, set())
    assert pairs == [("a", "b"), ("c", "d")] and bye is None
    pairs, _ = swiss_pairs(scores, {frozenset("ab")})
    assert pairs == [("a", "c"), ("b", "d")]
    pairs, bye = swiss_pairs({"a": 1, "b": 1, "c": 0}, set())
    assert bye == "c" and pairs == [("a", "b")]
    _, bye2 = swiss_pairs({"a": 1, "b": 1, "c": 0}, set(), byes={"c"})
    assert bye2 == "b"


def _cfgs(n=4):
    kinds = ["random", "greedy", "random", "greedy"]
    return [PlayerConfig(type=kinds[i], seed=i, name=f"p{i}") for i in range(n)]


def test_swiss_tournament_plays_requested_rounds(tmp_path):
    res = run_tournament(_cfgs(4), 2, MatchConfig(max_plies=30), tmp_path, save_games=False,
                         fmt="swiss", rounds=3, ci_samples=0)
    assert res.format == "swiss" and {g["round"] for g in res.games} == {1, 2, 3}
    assert len(res.games) == 3 * 2 * 2          # 3 rounds x 2 pairings x 2 games
    assert sum(s.games for s in res.standings) == 2 * len(res.games)


def test_opening_suite_is_shared_by_colour_swapped_pair(tmp_path):
    ops = load_openings("builtin")
    res = run_tournament(_cfgs(3), 4, MatchConfig(max_plies=30), tmp_path, save_games=False,
                         openings=ops, seed=1, ci_samples=0)
    by_pair: dict = {}
    for g in res.games:
        by_pair.setdefault(frozenset((g["white"], g["black"])), []).append(g)
    for games in by_pair.values():
        assert games[0]["opening"] == games[1]["opening"] and games[2]["opening"] == games[3]["opening"]
        assert games[0]["white"] != games[1]["white"]            # colours swapped
        assert games[0]["opening"] != games[2]["opening"]        # next pair gets a new opening
    assert all(g["plies"] >= len(g["opening"]) for g in res.games)


def test_anchors_from_config_and_leaderboard_marks_them(tmp_path):
    cfgs = [PlayerConfig(type="random", seed=1, name="r", anchor_elo=800),
            PlayerConfig(type="greedy", seed=2, name="g")]
    assert anchors_from(cfgs) == {"r": 800}
    assert anchors_from([PlayerConfig(type="stockfish", elo=1500, name="sf")]) == {"sf": 1500.0}
    res = run_tournament(cfgs, 4, MatchConfig(max_plies=40), tmp_path, save_games=False, ci_samples=20)
    assert next(s for s in res.standings if s.name == "r").elo == pytest.approx(800)
    assert "800*" in res.leaderboard_md() and "95% CI" in res.leaderboard_md()


def test_bootstrap_ci_narrows_with_more_games_and_brackets_rating():
    few = [("a", "b", 1.0), ("b", "a", 0.0), ("a", "b", 0.0), ("b", "a", 0.5)]
    many = few * 25
    w = lambda g: (lambda ci: ci["a"][1] - ci["a"][0])(bootstrap_ci(g, samples=100, seed=1))
    assert w(many) < w(few)
    ci, r = bootstrap_ci(many, samples=100, seed=1), compute_ratings(many)
    assert ci["a"][0] <= r["a"] <= ci["a"][1]
    assert bootstrap_ci([]) == {}
