import json

from aichess.config import GameConfig, MatchConfig, OutputConfig, PlayerConfig
from aichess.export import export_dir, iter_examples
from aichess.runner import run_game
from aichess.cli import main


def _game(tmp_path, moves_script=None):
    cfg = GameConfig(white=PlayerConfig(type="greedy", seed=1), black=PlayerConfig(type="random", seed=2),
                     match=MatchConfig(max_plies=6), output=OutputConfig(dir=str(tmp_path), display="none"))
    return run_game(cfg)[1] / "game.pgn"


def test_export_all_moves_and_filters(tmp_path):
    pgn = _game(tmp_path)                            # max_plies -> draw
    assert list(iter_examples(pgn)) == []            # winners_only skips draws
    exs = list(iter_examples(pgn, winners_only=False))
    assert len(exs) == 6
    assert exs[0]["messages"][2]["content"].startswith("<move>") and "Legal moves" in exs[0]["messages"][1]["content"]
    assert [e["meta"]["ply"] for e in exs] == [1, 2, 3, 4, 5, 6]
    assert len(list(iter_examples(pgn, winners_only=False, player="greedy"))) == 3
    assert "Legal moves" not in next(iter_examples(pgn, winners_only=False, include_legal_moves=False))["messages"][1]["content"]


def test_winner_only_export_and_cli(tmp_path, capsys):
    pgn = tmp_path / "x" / "game.pgn"
    pgn.parent.mkdir()
    pgn.write_text('[White "A"]\n[Black "B"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1\n')
    exs = list(iter_examples(pgn))
    assert [e["meta"]["ply"] for e in exs] == [2, 4]                 # Black's moves only
    assert exs[1]["messages"][2]["content"] == "<move>d8h4</move>"
    out = tmp_path / "ft.jsonl"
    assert main(["export", str(tmp_path), "--out", str(out)]) == 0
    assert len(out.read_text().splitlines()) == 2 and json.loads(out.read_text().splitlines()[0])["messages"]
    assert export_dir(tmp_path, out, winners_only=True, player="nobody") == 0
