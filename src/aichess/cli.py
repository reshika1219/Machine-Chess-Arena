from __future__ import annotations

import argparse
import sys
from pathlib import Path

import chess
import chess.engine
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
    if a.clock:
        cfg.match.clock_seconds = a.clock
    if a.random_opening:
        cfg.match.random_opening_plies = a.random_opening
    if a.resume:
        cfg.match.start_pgn = a.resume
    if a.seed is not None:
        cfg.match.seed = a.seed
    if a.chess960 or a.position is not None:
        cfg.match.chess960 = True
        if a.position is not None:
            cfg.match.chess960_position = a.position
    if a.commentary:
        from .config import CommentaryConfig
        cfg.commentary = CommentaryConfig(model=a.commentary if a.commentary != "default" else "claude-haiku-5-5")
    if a.odds:
        cfg.match.material_odds = a.odds
    if a.clock_white is not None:
        cfg.match.clock_seconds_white = a.clock_white
    if a.clock_black is not None:
        cfg.match.clock_seconds_black = a.clock_black
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


def _cmd_tournament(a: argparse.Namespace) -> int:
    from .tournament import load_players, run_tournament

    cfgs = load_players(a.players)
    res = run_tournament(cfgs, a.games, MatchConfig(max_plies=a.max_plies or 300), a.out, display=a.verbose)
    print(res.leaderboard_md())
    return 0


def _cmd_analyze(a: argparse.Namespace) -> int:
    import shutil

    from .analysis import analyse_game, format_report

    exe = a.engine or shutil.which("stockfish")
    if not exe:
        print("error: Stockfish not found. Install it (`brew install stockfish`) or pass --engine.", file=sys.stderr)
        return 1
    with open(a.pgn) as f:
        game = chess.pgn.read_game(f)
    if game is None:
        print("error: no game found in PGN", file=sys.stderr)
        return 1
    with chess.engine.SimpleEngine.popen_uci(exe) as eng:
        rep = analyse_game(game, eng, chess.engine.Limit(time=a.movetime))
    print(format_report(game, rep))
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
    pl.add_argument("--clock", type=float, help="total thinking seconds per side (flag = loss on time)")
    pl.add_argument("--chess960", action="store_true", help="Fischer Random start position")
    pl.add_argument("--position", type=int, metavar="0-959", help="Chess960 start position number (implies --chess960)")
    pl.add_argument("--commentary", nargs="?", const="default", metavar="MODEL",
                    help="LLM commentator narrates the game (optionally give the model)")
    pl.add_argument("--odds", metavar="SIDE:PIECES", help="material odds, e.g. black:q removes Black's queen")
    pl.add_argument("--clock-white", type=float, help="White's clock in seconds (time odds)")
    pl.add_argument("--clock-black", type=float, help="Black's clock in seconds (time odds)")
    pl.add_argument("--random-opening", type=int, metavar="PLIES", help="play N random plies first")
    pl.add_argument("--resume", metavar="PGN", help="continue a saved game from its last position")
    pl.add_argument("--seed", type=int, help="seed for opening/fallback randomness")
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

    an = sub.add_parser("analyze", help="centipawn loss / accuracy per player (needs Stockfish)")
    an.add_argument("pgn")
    an.add_argument("--engine", help="path to Stockfish (default: on PATH)")
    an.add_argument("--movetime", type=float, default=0.1, help="seconds per position")
    an.set_defaults(fn=_cmd_analyze)

    tp = sub.add_parser("tournament", help="round-robin between several players")
    tp.add_argument("--players", required=True, help="YAML file with a `players:` list")
    tp.add_argument("--games", type=int, default=2, help="games per pairing (rounded up to even)")
    tp.add_argument("--max-plies", type=int)
    tp.add_argument("--out", default="games/tournaments")
    tp.add_argument("--verbose", action="store_true", help="show every game in the terminal")
    tp.set_defaults(fn=_cmd_tournament)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
