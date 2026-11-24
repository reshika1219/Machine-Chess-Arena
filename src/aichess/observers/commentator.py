"""LLM commentator: narrates the game by publishing Commentary events (never blocks the game)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

import chess

from ..events import Commentary, GameOver, GameStart, MoveEvent

SYSTEM = ("You are {style}. Given a chess position and the move just played, write 1-2 vivid, "
          "accurate sentences for spectators. Mention only what is actually on the board. "
          "No move numbering lists, no markdown.")


class Commentator:
    def __init__(self, emit: Callable[[Commentary], None], client: Any, model: str = "claude-haiku-5-5",
                 every: int = 2, style: str = "an enthusiastic but insightful chess commentator",
                 max_tokens: int = 200) -> None:
        self.emit, self.client, self.model = emit, client, model
        self.every, self.max_tokens = every, max_tokens
        self.system = SYSTEM.format(style=style)
        self._pool = ThreadPoolExecutor(max_workers=1)   # one at a time keeps remarks in order
        self._recent: list[str] = []
        self._players = ("White", "Black")

    def _ask(self, prompt: str) -> Optional[str]:
        try:
            resp = self.client.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=self.system,
                messages=[{"role": "user", "content": prompt}])
            return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip() or None
        except Exception:      # commentary is decoration: an API hiccup must never affect the game
            return None

    def _job(self, ply: int, prompt: str, kind: str) -> None:
        text = self._ask(prompt)
        if text:
            self.emit(Commentary(ply, text, kind))

    def __call__(self, ev: object) -> None:
        if isinstance(ev, GameStart):
            self._players = (ev.white, ev.black)
        elif isinstance(ev, MoveEvent):
            self._recent.append(ev.san)
            if ev.ply % self.every == 0:
                board = chess.Board(ev.fen_after)
                note = "Check! " if board.is_check() else ""
                eval_note = f"Engine eval (White POV, centipawns): {ev.info['eval_cp']}\n" if "eval_cp" in ev.info else ""
                prompt = (f"{self._players[0]} (White) vs {self._players[1]} (Black).\n"
                          f"Last moves: {' '.join(self._recent[-8:])}\n"
                          f"{ev.player} just played {ev.san}. {note}\nFEN: {ev.fen_after}\n{eval_note}")
                self._pool.submit(self._job, ev.ply, prompt, "move")
        elif isinstance(ev, GameOver):
            prompt = (f"The game between {self._players[0]} and {self._players[1]} ended {ev.result} "
                      f"by {ev.reason.replace('_', ' ')} after {ev.plies} plies. Final moves: "
                      f"{' '.join(self._recent[-8:])}. Give a short closing summary.")
            self._pool.submit(self._job, ev.plies, prompt, "summary")
            self._pool.shutdown(wait=True)    # flush remaining remarks before the game ends
