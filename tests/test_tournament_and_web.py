import pytest
from fastapi.testclient import TestClient

from aichess.config import GameConfig, MatchConfig, OutputConfig, PlayerConfig
from aichess.tournament import load_players, run_tournament
from aichess.web.server import create_app


def test_tournament_round_robin_alternates_colours(tmp_path):
    cfgs = [PlayerConfig(type="random", seed=1, name="r"), PlayerConfig(type="greedy", seed=2, name="g"),
            PlayerConfig(type="random", seed=3, name="r2")]
    res = run_tournament(cfgs, games_per_pairing=3, match_cfg=MatchConfig(max_plies=60),
                         out_dir=tmp_path, save_games=False)
    assert len(res.games) == 3 * 4  # 3 pairings x (3 -> rounded up to 4) games
    for a, b in [("r", "g"), ("r", "r2"), ("g", "r2")]:
        games = [x for x in res.games if {x["white"], x["black"]} == {a, b}]
        assert sum(x["white"] == a for x in games) == 2
    assert sum(s.games for s in res.standings) == 2 * len(res.games)
    assert "| Player |" in res.leaderboard_md()
    assert list(tmp_path.glob("*/leaderboard.md"))


def test_duplicate_player_names_rejected(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text("players:\n  - {type: random}\n  - {type: random}\n")
    with pytest.raises(ValueError, match="unique"):
        load_players(f)


def test_web_streams_full_game_and_serves_page():
    cfg = GameConfig(white=PlayerConfig(type="random", seed=1), black=PlayerConfig(type="greedy", seed=2),
                     output=OutputConfig(save_pgn=False, save_jsonl=False, display="none"),
                     match=MatchConfig(max_plies=16))
    with TestClient(create_app(cfg)) as c:
        assert "Machine Chess Arena" in c.get("/").text
        with c.websocket_connect("/ws") as ws:
            ws.send_json({"cmd": "speed", "value": 0})
            ws.send_json({"cmd": "play"})
            kinds = []
            while not kinds or kinds[-1] != "GameOver":
                kinds.append(ws.receive_json()["type"])
        assert kinds[0] == "GameStart" and kinds.count("MoveEvent") == 16


def test_missing_api_key_fails_fast(monkeypatch):
    from aichess.players.llm import LLMPlayer
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        LLMPlayer()


def test_web_reports_setup_errors_in_ui():
    cfg = GameConfig(white=PlayerConfig(type="stockfish", path="/nonexistent/sf"), black=PlayerConfig(type="random"),
                     output=OutputConfig(save_pgn=False, save_jsonl=False, display="none"))
    with TestClient(create_app(cfg)) as c:
        with c.websocket_connect("/ws") as ws:
            ws.send_json({"cmd": "play"})
            msg = ws.receive_json()
        assert msg["type"] == "Error"
