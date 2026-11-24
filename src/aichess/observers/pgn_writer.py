from __future__ import annotations

import datetime as dt
from pathlib import Path

import chess
import chess.pgn

from ..events import GameOver, GameStart, MoveEvent


class PgnWriter:
    """Builds a PGN game from events and writes it when the game ends."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.game: chess.pgn.Game | None = None
        self.node: chess.pgn.GameNode | None = None

    def __call__(self, ev: object) -> None:
        if isinstance(ev, GameStart):
            g = chess.pgn.Game()
            g.headers["Event"] = "Machine-Chess-Arena"
            g.headers["Date"] = dt.date.today().strftime("%Y.%m.%d")
            g.headers["White"], g.headers["Black"] = ev.white, ev.black
            if ev.fen != chess.STARTING_FEN or ev.chess960:
                g.setup(chess.Board(ev.fen, chess960=ev.chess960))  # sets FEN/SetUp (+Variant for 960)
            if ev.handicap:
                g.headers["Handicap"] = ev.handicap
            self.game, self.node = g, g
            for uci in ev.prior_moves:   # opening / resumed moves are part of the record
                self.node = self.node.add_variation(chess.Move.from_uci(uci))
        elif isinstance(ev, MoveEvent) and self.node is not None:
            self.node = self.node.add_variation(chess.Move.from_uci(ev.uci))
        elif isinstance(ev, GameOver) and self.game is not None:
            self.game.headers["Result"] = ev.result
            self.game.headers["Termination"] = ev.reason
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(str(self.game) + "\n")
