from __future__ import annotations

import argparse
import sys
from pathlib import Path

import chess
import chess.pgn

from .config import GameConfig, MatchConfig, OutputConfig, load_game_config, parse_player_spec
from .runner import run_game


def _cmd_play(a: argparse.Namespace) -> int:
    if a.config:
        cfg = load_game_config(a.config)
    elif a.white and a.black:
        cfg = GameConfig(white=parse_player_spec(a.white), black=parse_player_spec(a.black))
    else:
        print("error: give --config, or both --white and --black", file=sys.stderr)
        return 2
    if a.max_plies:
        cfg.match.max_plies = a.max_plies
    if a.on_failure:
        cfg.match.on_failure = a.on_failure
    if a.quiet:
        cfg.output.display = "none"
    if a.no_board:
        cfg.output.show_board = False
    if a.out:
        cfg.output.dir = a.out
    observers = []
    if a.web:
        from .web.server import serve_game
        return serve_game(cfg, host=a.host, port=a.port)
    result, out_dir = run_game(cfg, observers)
    print(f"Result: {result.result} ({result.reason}) in {result.plies} plies")
    if out_dir:
        print(f"Saved to: {out_dir}")
    return 0


def _cmd_replay(a: argparse.Namespace) -> int:
    import time
    from rich.console import Console

    console = Console()
    with open(a.pgn) as f:
        game = chess.pgn.read_game(f)
    if game is None:
        print("error: no game found in PGN", file=sys.stderr)
        return 1
    h = game.headers
    console.rule(f"{h.get('White', '?')} vs {h.get('Black', '?')} — {h.get('Result', '*')}")
    board = game.board()
    for node in game.mainline():
        san = board.san(node.move)
        board.push(node.move)
        n = (board.ply() + 1) // 2
        console.print(f"{n}{'.' if board.turn == chess.BLACK else '...'} [bold]{san}[/]")
        console.print(board.unicode(borders=False, empty_square="·"), highlight=False)
        time.sleep(a.delay)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aichess", description="AI vs AI chess")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("play", help="play one game")
    pl.add_argument("--white", help="e.g. llm:claude-opus-5-5 | stockfish:level=8 | random | greedy")
    pl.add_argument("--black")
    pl.add_argument("--config", help="YAML game config")
    pl.add_argument("--max-plies", type=int)
    pl.add_argument("--on-failure", choices=["forfeit", "random_move"])
    pl.add_argument("--out", help="output directory (default: games)")
    pl.add_argument("--quiet", action="store_true", help="no terminal display")
    pl.add_argument("--no-board", action="store_true", help="moves only, no board drawings")
    pl.add_argument("--web", action="store_true", help="serve a live web UI instead of the terminal")
    pl.add_argument("--host", default="127.0.0.1")
    pl.add_argument("--port", type=int, default=8000)
    pl.set_defaults(fn=_cmd_play)

    rp = sub.add_parser("replay", help="replay a saved PGN in the terminal")
    rp.add_argument("pgn")
    rp.add_argument("--delay", type=float, default=0.5)
    rp.set_defaults(fn=_cmd_replay)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
