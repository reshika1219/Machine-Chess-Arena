"""LLM player (Anthropic/Claude). Stateless prompts: full position every turn."""
from __future__ import annotations

import os
import re
from typing import Any, Optional

import chess

from .base import MoveContext, MoveResult, Player

SYSTEM_PROMPT = """You are a strong chess player. You will be shown the current position and must \
choose exactly one legal move.

Rules for your reply:
- You may think briefly first, but keep it short.
- End with your chosen move in UCI notation inside tags, e.g. <move>e2e4</move> \
(promotions like <move>e7e8q</move>, castling as the king move like <move>e1g1</move>).
- The move MUST be one of the legal moves listed. Never invent moves."""

MOVE_TAG = re.compile(r"<move>\s*([^<\s]+)\s*</move>", re.IGNORECASE)


def build_prompt(board: chess.Board, ctx: MoveContext, show_legal_moves: bool = True) -> str:
    color = "White" if board.turn == chess.WHITE else "Black"
    # SAN history with move numbers
    parts = []
    for i, san in enumerate(ctx.history_san):
        if i % 2 == 0:
            parts.append(f"{i // 2 + 1}.")
        parts.append(san)
    history = " ".join(parts) if parts else "(game start)"
    lines = [
        f"You are playing {color}.",
        f"FEN: {board.fen()}",
        "Board (uppercase = White, lowercase = Black):",
        str(board),
        f"Moves so far: {history}",
    ]
    if board.is_check():
        lines.append("You are in check.")
    if show_legal_moves:
        lines.append("Legal moves (UCI): " + " ".join(m.uci() for m in board.legal_moves))
    if ctx.feedback:
        lines.append(f"\nYour previous answer was rejected: {ctx.feedback} Choose again.")
    lines.append("\nWhat is your move?")
    return "\n".join(lines)


def parse_move(text: str, board: chess.Board) -> chess.Move:
    """Extract a move from the reply. Accepts UCI (preferred) or SAN inside <move> tags."""
    tags = MOVE_TAG.findall(text)
    if not tags:
        raise ValueError("no <move>...</move> tag found")
    raw = tags[-1]  # the last tag is the final decision
    try:
        return board.parse_uci(raw)
    except ValueError:
        pass
    try:
        return board.parse_san(raw)
    except ValueError:
        raise ValueError(f"could not interpret '{raw}' as a legal move") from None


class LLMPlayer(Player):
    def __init__(
        self,
        model: str = "claude-sonnet-5-5",
        temperature: Optional[float] = None,
        max_tokens: int = 1024,
        show_legal_moves: bool = True,
        system_prompt: str = SYSTEM_PROMPT,
        client: Any = None,
        name: Optional[str] = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.show_legal_moves = show_legal_moves
        self.system_prompt = system_prompt
        self.name = name or model
        self._client = client
        if client is None:
            self.client  # fail fast (missing key / package) instead of forfeiting mid-game

    @property
    def client(self) -> Any:
        if self._client is None:
            from dotenv import load_dotenv
            import anthropic

            load_dotenv()
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")
            self._client = anthropic.Anthropic(max_retries=5)  # reads ANTHROPIC_API_KEY; SDK backs off on 429/5xx
        return self._client

    def choose_move(self, board: chess.Board, ctx: MoveContext) -> MoveResult:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=[{"role": "user", "content": build_prompt(board, ctx, self.show_legal_moves)}],
        )
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        resp = self.client.messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        move = parse_move(text, board)
        usage = getattr(resp, "usage", None)
        return MoveResult(move, {
            "raw_reply": text,
            "input_tokens": getattr(usage, "input_tokens", 0),
            "output_tokens": getattr(usage, "output_tokens", 0),
        })
