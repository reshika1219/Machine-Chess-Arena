"""Read-only access to saved games and tournaments (for the web UI's replay and tournament tabs)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import chess
import chess.pgn


class NotFound(Exception):
    pass


def _safe(root: Path, rel: str) -> Path:
    """Resolve `rel` under `root`, refusing anything that escapes it (path traversal)."""
    p = (root / rel).resolve()
    if root.resolve() not in p.parents and p != root.resolve():
        raise NotFound(rel)
    return p


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def list_games(root: Path, limit: int = 200) -> list[dict]:
    items = []
    for pgn in Path(root).rglob("game.pgn"):
        d = pgn.parent
        with pgn.open() as f:
            h = chess.pgn.read_headers(f)
        if h is None:
            continue
        items.append({
            "id": d.relative_to(root).as_posix(), "white": h.get("White", "?"), "black": h.get("Black", "?"),
            "result": h.get("Result", "*"), "termination": h.get("Termination", ""), "date": h.get("Date", ""),
            "variant": h.get("Variant", ""), "handicap": h.get("Handicap", ""), "mtime": pgn.stat().st_mtime,
            "has_log": (d / "moves.jsonl").exists(),
        })
    items.sort(key=lambda x: -x["mtime"])
    return items[:limit]


def load_game(root: Path, game_id: str) -> dict[str, Any]:
    d = _safe(Path(root), game_id)
    pgn = d / "game.pgn"
    if not pgn.is_file():
        raise NotFound(game_id)
    with pgn.open() as f:
        game = chess.pgn.read_game(f)
    if game is None:
        raise NotFound(game_id)
    log = {m["ply"]: m for m in _read_jsonl(d / "moves.jsonl")}
    board = game.board()
    start_fen = board.fen()
    moves = []
    for node in game.mainline():
        san = board.san(node.move)
        side = "white" if board.turn == chess.WHITE else "black"
        board.push(node.move)
        ply = len(board.move_stack)
        rec = log.get(ply, {})
        moves.append({"ply": ply, "side": side, "san": san, "uci": node.move.uci(), "fen_after": board.fen(),
                      "info": rec.get("info", {}), "seconds": rec.get("seconds"), "retries": rec.get("retries", 0),
                      "fallback": rec.get("fallback", False)})
    summary = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else {}
    analysis = json.loads((d / "analysis.json").read_text()) if (d / "analysis.json").exists() else None
    return {"id": game_id, "headers": dict(game.headers), "start_fen": start_fen, "chess960": board.chess960,
            "moves": moves, "summary": summary, "commentary": _read_jsonl(d / "commentary.jsonl"),
            "analysis": analysis}


def list_tournaments(root: Path) -> list[dict]:
    items = []
    for f in Path(root).rglob("results.json"):
        try:
            data = json.loads(f.read_text())
        except ValueError:
            continue
        if not isinstance(data, dict) or "standings" not in data:
            continue
        items.append({"id": f.parent.relative_to(root).as_posix(), "format": data.get("format", "round_robin"),
                      "players": len(data["standings"]), "games": len(data.get("games", [])),
                      "winner": data["standings"][0]["name"] if data["standings"] else None,
                      "mtime": f.stat().st_mtime})
    items.sort(key=lambda x: -x["mtime"])
    return items


def load_tournament(root: Path, tid: str) -> dict[str, Any]:
    d = _safe(Path(root), tid)
    f = d / "results.json"
    if not f.is_file():
        raise NotFound(tid)
    data = json.loads(f.read_text())
    root_resolved = Path(root).resolve()
    for g in data.get("games", []):          # make each game's folder addressable by the games API
        if g.get("dir"):
            try:
                g["game_id"] = Path(g["dir"]).resolve().relative_to(root_resolved).as_posix()
            except ValueError:
                g["game_id"] = None
    return {"id": tid, **data}


def analyse_saved_game(root: Path, game_id: str, engine_path: Optional[str], movetime: float = 0.1) -> dict:
    """Run Stockfish over a saved game (cached to analysis.json next to it)."""
    import dataclasses
    import shutil

    import chess.engine

    from ..analysis import analyse_game

    d = _safe(Path(root), game_id)
    cache = d / "analysis.json"
    if cache.exists():
        return json.loads(cache.read_text())
    exe = engine_path or shutil.which("stockfish")
    if not exe:
        raise FileNotFoundError("Stockfish not found")
    with (d / "game.pgn").open() as f:
        game = chess.pgn.read_game(f)
    with chess.engine.SimpleEngine.popen_uci(exe) as eng:
        rep = analyse_game(game, eng, chess.engine.Limit(time=movetime))
    out = {"evals": rep.evals, "white": dataclasses.asdict(rep.white), "black": dataclasses.asdict(rep.black)}
    cache.write_text(json.dumps(out))
    return out
