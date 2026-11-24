from __future__ import annotations

import chess
from rich.console import Console

from ..events import Commentary, GameOver, GameStart, MoveEvent

console = Console()


class TerminalObserver:
    def __init__(self, show_board: bool = True) -> None:
        self.show_board = show_board

    def __call__(self, ev: object) -> None:
        if isinstance(ev, GameStart):
            console.rule(f"[bold]{ev.white}[/] (white)  vs  [bold]{ev.black}[/] (black)")
        elif isinstance(ev, MoveEvent):
            num = (ev.ply + 1) // 2
            dots = "." if ev.side == "white" else "..."
            extra = ""
            if ev.retries:
                extra += f" [yellow](retries: {ev.retries})[/]"
            if ev.fallback:
                extra += " [red](fallback move)[/]"
            console.print(f"{num}{dots} [bold]{ev.san}[/]  [dim]{ev.player} · {ev.seconds:.1f}s[/]{extra}")
            if self.show_board:
                board = chess.Board(ev.fen_after)
                console.print(board.unicode(borders=False, empty_square="·"), highlight=False)
        elif isinstance(ev, Commentary):
            console.print(f"  [italic cyan]🎙 {ev.text}[/]")
        elif isinstance(ev, GameOver):
            console.rule(f"[bold green]{ev.result}[/] — {ev.reason} after {ev.plies} plies")
