import json

import pytest
from fastapi.testclient import TestClient

from aichess.config import GameConfig, MatchConfig, OutputConfig, PlayerConfig
from aichess.runner import run_game
from aichess.tournament import run_tournament
from aichess.web import archive
from aichess.web.server import create_app


@pytest.fixture
def root(tmp_path):
    cfg = GameConfig(white=PlayerConfig(type="greedy", seed=1), black=PlayerConfig(type="random", seed=2),
                     match=MatchConfig(max_plies=20, material_odds="black:q"),
                     output=OutputConfig(dir=str(tmp_path), display="none"))
    _, d = run_game(cfg)
    run_tournament([PlayerConfig(type="random", seed=1, name="a"), PlayerConfig(type="greedy", seed=2, name="b")],
                   2, MatchConfig(max_plies=20), tmp_path / "tournaments", ci_samples=10)
    return tmp_path, d


def test_list_and_load_game(root):
    path, d = root
    games = archive.list_games(path)
    assert len(games) == 3 and any(g["handicap"] for g in games)   # 1 single game + 2 tournament games
    g = archive.load_game(path, d.relative_to(path).as_posix())
    assert len(g["moves"]) == 20 and g["moves"][0]["fen_after"] and g["moves"][0]["info"] is not None
    assert g["headers"]["White"] == "greedy" and g["summary"]["plies"] == 20


def test_tournament_listing_and_game_links(root):
    path, _ = root
    ts = archive.list_tournaments(path)
    assert len(ts) == 1 and ts[0]["players"] == 2 and ts[0]["games"] == 2
    t = archive.load_tournament(path, ts[0]["id"])
    assert all(g["game_id"] and archive.load_game(path, g["game_id"]) for g in t["games"])


@pytest.mark.parametrize("bad", ["../../etc", "..", "/etc/passwd", "nope"])
def test_path_traversal_and_missing_are_404(root, bad):
    path, _ = root
    with pytest.raises(archive.NotFound):
        archive.load_game(path, bad)
    with pytest.raises(archive.NotFound):
        archive.load_tournament(path, bad)


def test_http_endpoints(root):
    path, d = root
    cfg = GameConfig(white=PlayerConfig(type="random"), black=PlayerConfig(type="random"),
                     output=OutputConfig(dir=str(path), display="none"))
    with TestClient(create_app(cfg, autostart=False)) as c:
        assert len(c.get("/api/games").json()) == 3
        assert c.get(f"/api/games/{d.relative_to(path).as_posix()}").json()["summary"]["plies"] == 20
        assert c.get("/api/games/%2e%2e/%2e%2e/etc").status_code == 404
        assert c.get("/api/games/missing").status_code == 404
        tid = c.get("/api/tournaments").json()[0]["id"]
        assert c.get(f"/api/tournament/{tid}").json()["standings"]
        assert c.get("/api/info").json()["chess960"] is False


def test_analysis_cached_and_missing_engine_is_501(root, monkeypatch):
    path, d = root
    gid = d.relative_to(path).as_posix()
    (d / "analysis.json").write_text(json.dumps({"evals": [0, 10], "white": {}, "black": {}}))
    assert archive.analyse_saved_game(path, gid, None)["evals"] == [0, 10]
    (d / "analysis.json").unlink()
    monkeypatch.setattr("shutil.which", lambda _: None)
    cfg = GameConfig(white=PlayerConfig(type="random"), black=PlayerConfig(type="random"),
                     output=OutputConfig(dir=str(path), display="none"))
    with TestClient(create_app(cfg, autostart=False)) as c:
        assert c.get(f"/api/games/{gid}/analysis").status_code == 501


def test_ui_assets_are_served():
    cfg = GameConfig(white=PlayerConfig(type="random"), black=PlayerConfig(type="random"),
                     output=OutputConfig(save_pgn=False, save_jsonl=False, display="none"))
    with TestClient(create_app(cfg, autostart=False)) as c:
        page = c.get("/").text
        assert "/static/app.js" in page and "/static/app.css" in page
        js = c.get("/static/app.js")
        assert js.status_code == 200 and "textContent" in js.text and "innerHTML" not in js.text
        assert c.get("/static/app.css").status_code == 200
