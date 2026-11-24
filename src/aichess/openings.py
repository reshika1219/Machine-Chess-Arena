"""Opening books / suites: lists of opening lines used to vary (and balance) games."""
from __future__ import annotations

import random
from pathlib import Path
from typing import Optional

import chess
import chess.pgn

# Name -> SAN line. Small but varied; use a file for a bigger suite.
BUILTIN: dict[str, str] = {
    "Ruy Lopez": "e4 e5 Nf3 Nc6 Bb5 a6",
    "Italian Game": "e4 e5 Nf3 Nc6 Bc4 Bc5",
    "Sicilian Najdorf": "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6",
    "French Defence": "e4 e6 d4 d5 Nc3 Nf6",
    "Caro-Kann": "e4 c6 d4 d5 Nc3 dxe4 Nxe4",
    "Queen's Gambit Declined": "d4 d5 c4 e6 Nc3 Nf6",
    "Slav Defence": "d4 d5 c4 c6 Nf3 Nf6",
    "King's Indian": "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6",
    "Nimzo-Indian": "d4 Nf6 c4 e6 Nc3 Bb4",
    "English Opening": "c4 e5 Nc3 Nf6 Nf3 Nc6",
    "Reti Opening": "Nf3 d5 g3 Nf6 Bg2",
    "London System": "d4 d5 Bf4 Nf6 e3 e6 Nf3",
    "Scandinavian": "e4 d5 exd5 Qxd5 Nc3 Qa5",
    "Pirc Defence": "e4 d6 d4 Nf6 Nc3 g6",
}


def san_line_to_uci(line: str, start: Optional[chess.Board] = None) -> list[str]:
    board = start.copy() if start else chess.Board()
    out: list[str] = []
    for tok in line.replace("\n", " ").split():
        if tok.endswith(".") or tok[0].isdigit() and "." in tok.rstrip("."):
            tok = tok.split(".")[-1]
            if not tok:
                continue
        try:
            move = board.parse_san(tok)
        except ValueError:
            try:
                move = board.parse_uci(tok)
            except ValueError:
                raise ValueError(f"illegal or unreadable move '{tok}' in opening '{line}'") from None
        out.append(move.uci())
        board.push(move)
    return out


def load_openings(source: str, max_plies: Optional[int] = None) -> list[list[str]]:
    """source: 'builtin' | path to a .pgn (every game's mainline) | path to a text file with one
    SAN/UCI line per row (blank lines and '#' comments ignored; 'Name: moves' allowed)."""
    if source == "builtin":
        lines = [san_line_to_uci(v) for v in BUILTIN.values()]
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"opening file not found: {source}")
        if path.suffix.lower() == ".pgn":
            lines = []
            with path.open() as f:
                while (g := chess.pgn.read_game(f)) is not None:
                    lines.append([n.move.uci() for n in g.mainline()])
        else:
            lines = []
            for raw in path.read_text().splitlines():
                raw = raw.split("#", 1)[0].strip()
                if raw:
                    lines.append(san_line_to_uci(raw.split(":", 1)[1] if ":" in raw else raw))
    lines = [ln[:max_plies] if max_plies else ln for ln in lines if ln]
    if not lines:
        raise ValueError(f"no openings found in {source}")
    return lines


def pick_opening(openings: list[list[str]], index: int, seed: Optional[int] = None) -> list[str]:
    """Deterministic choice: the same (seed, index) always gives the same opening; a colour-swapped
    pair shares `index`, so both players face the same opening from both sides."""
    order = list(range(len(openings)))
    random.Random(seed).shuffle(order)
    return openings[order[index % len(openings)]]
