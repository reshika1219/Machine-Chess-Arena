from __future__ import annotations

import shutil
from typing import Optional

import chess
import chess.engine

from .base import MoveContext, MoveResult, Player


class StockfishPlayer(Player):
    """Any UCI engine (Stockfish by default). Strength via skill level, UCI_Elo or limits."""

    def __init__(
        self,
        path: Optional[str] = None,
        skill_level: Optional[int] = None,
        elo: Optional[int] = None,
        movetime: float = 0.2,
        depth: Optional[int] = None,
        threads: int = 1,
    ) -> None:
        exe = path or shutil.which("stockfish")
        if not exe:
            raise FileNotFoundError(
                "Stockfish not found. Install it (e.g. `brew install stockfish`) or set `path`."
            )
        self.path = exe
        self.skill_level, self.elo = skill_level, elo
        self.limit = chess.engine.Limit(depth=depth) if depth else chess.engine.Limit(time=movetime)
        self.threads = threads
        self.name = "stockfish" + (f"-elo{elo}" if elo else f"-lvl{skill_level}" if skill_level is not None else "")
        self._engine: Optional[chess.engine.SimpleEngine] = None

    def _start(self) -> chess.engine.SimpleEngine:
        eng = chess.engine.SimpleEngine.popen_uci(self.path)
        opts: dict = {"Threads": self.threads}
        if self.elo is not None:
            opts.update({"UCI_LimitStrength": True, "UCI_Elo": self.elo})
        elif self.skill_level is not None:
            opts["Skill Level"] = self.skill_level
        # only configure options the engine actually supports
        eng.configure({k: v for k, v in opts.items() if k in eng.options})
        return eng

    def choose_move(self, board: chess.Board, ctx: MoveContext) -> MoveResult:
        if self._engine is None:
            self._engine = self._start()
        res = self._engine.play(board, self.limit, info=chess.engine.INFO_SCORE)
        info: dict = {}
        score = res.info.get("score")
        if score is not None:
            info["eval_cp"] = score.white().score(mate_score=10000)
        return MoveResult(res.move, info)

    def close(self) -> None:
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:
                self._engine.close()
            self._engine = None
