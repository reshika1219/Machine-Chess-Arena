"""Export saved games as supervised fine-tuning examples (chat format, one JSON object per move)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Optional

import chess
import chess.pgn

from .players.base import MoveContext
from .players.llm import SYSTEM_PROMPT, build_prompt


def iter_examples(
    pgn_path: Path, winners_only: bool = True, player: Optional[str] = None, include_legal_moves: bool = True,
) -> Iterator[dict]:
    """Yield {"messages": [system, user, assistant]} for the chosen side(s) of one game.
    winners_only: learn only from the winning side (draws are skipped); player: substring match on name."""
    with Path(pgn_path).open() as f:
        game = chess.pgn.read_game(f)
    if game is None:
        return
    h = game.headers
    result = h.get("Result", "*")
    wanted = {chess.WHITE, chess.BLACK}
    if winners_only:
        if result == "1-0":
            wanted = {chess.WHITE}
        elif result == "0-1":
            wanted = {chess.BLACK}
        else:
            return
    if player:
        names = {chess.WHITE: h.get("White", ""), chess.BLACK: h.get("Black", "")}
        wanted = {c for c in wanted if player.lower() in names[c].lower()}
    board, history = game.board(), []
    for node in game.mainline():
        move = node.move
        if board.turn in wanted:
            prompt = build_prompt(board, MoveContext(board.ply() + 1, list(history)), include_legal_moves)
            yield {"messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": f"<move>{move.uci()}</move>"},
            ], "meta": {"game": str(pgn_path), "ply": board.ply() + 1, "result": result}}
        history.append(board.san(move))
        board.push(move)


def export_dir(root: Path, out_file: Path, **kw) -> int:
    n = 0
    out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("w") as out:
        for pgn in sorted(Path(root).rglob("game.pgn")):
            for ex in iter_examples(pgn, **kw):
                out.write(json.dumps(ex) + "\n")
                n += 1
    return n
