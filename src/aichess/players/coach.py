"""A chess engine exposed to an LLM as a tool (the "coached LLM")."""
from __future__ import annotations

import shutil
from typing import Any, Optional

import chess
import chess.engine

TOOL_SPEC: dict[str, Any] = {
    "name": "engine_analysis",
    "description": (
        "Ask a chess engine for its best lines in the CURRENT position. Returns the top candidate "
        "moves (UCI), evaluation in pawns from the side-to-move's point of view (positive = good "
        "for you), and a short principal variation. Use it to check tactics or compare candidates "
        "before committing; the final decision is still yours."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "lines": {"type": "integer", "minimum": 1, "maximum": 5, "description": "How many candidate lines (default 3)."},
        },
    },
}


def format_lines(board: chess.Board, infos: list[dict]) -> str:
    out = []
    for i, info in enumerate(infos, 1):
        pv = info.get("pv") or []
        if not pv:
            continue
        score = info["score"].pov(board.turn)
        if score.is_mate():
            ev = f"mate in {score.mate()}"
        else:
            ev = f"{score.score() / 100:+.2f}"
        b, san = board.copy(), []
        for m in pv[:6]:
            san.append(b.san(m))
            b.push(m)
        out.append(f"{i}. {pv[0].uci()} (eval {ev}) line: {' '.join(san)}")
    return "\n".join(out) or "no analysis available"


class EngineCoach:
    """Wraps a UCI engine; `analyse(board, lines)` returns text for the tool result."""

    def __init__(self, path: Optional[str] = None, movetime: float = 0.3, depth: Optional[int] = None,
                 engine: Any = None) -> None:
        self.limit = chess.engine.Limit(depth=depth) if depth else chess.engine.Limit(time=movetime)
        self._engine = engine
        self.path = path or (None if engine else shutil.which("stockfish"))
        if self._engine is None and not self.path:
            raise FileNotFoundError("Stockfish not found for the coach. Install it or set `coach_path`.")

    def analyse(self, board: chess.Board, lines: int = 3) -> str:
        if self._engine is None:
            self._engine = chess.engine.SimpleEngine.popen_uci(self.path)
        lines = max(1, min(5, int(lines or 3)))
        infos = self._engine.analyse(board, self.limit, multipv=lines)
        return format_lines(board, infos if isinstance(infos, list) else [infos])

    def close(self) -> None:
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None
