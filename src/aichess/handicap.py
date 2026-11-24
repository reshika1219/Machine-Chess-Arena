"""Handicaps: material odds applied to a start position."""
from __future__ import annotations

import chess

_PIECES = {"q": chess.QUEEN, "r": chess.ROOK, "b": chess.BISHOP, "n": chess.KNIGHT, "p": chess.PAWN}


def parse_material_odds(spec: str) -> tuple[chess.Color, list[chess.PieceType]]:
    """'black:q' -> (BLACK, [QUEEN]). Letters: q r b n p (repeat a letter to remove several)."""
    side, _, letters = spec.partition(":")
    colors = {"white": chess.WHITE, "black": chess.BLACK}
    if side.strip().lower() not in colors or not letters.strip():
        raise ValueError(f"material_odds must look like 'black:q' or 'white:rn', got '{spec}'")
    bad = [c for c in letters.lower() if c not in _PIECES]
    if bad:
        raise ValueError(f"unknown piece letter(s) {bad} in '{spec}' (use q r b n p)")
    return colors[side.strip().lower()], [_PIECES[c] for c in letters.lower()]


def apply_material_odds(board: chess.Board, spec: str) -> None:
    """Remove the given pieces from one side (the outermost files first, so castling rights are
    only dropped for rooks that are actually removed). Mutates `board`."""
    color, kinds = parse_material_odds(spec)
    for kind in kinds:
        squares = sorted(board.pieces(kind, color), key=lambda sq: (abs(chess.square_file(sq) - 3.5)), reverse=True)
        if kind == chess.QUEEN:
            squares = list(board.pieces(kind, color))
        if not squares:
            raise ValueError(f"{chess.piece_name(kind)} not available to remove for the odds '{spec}'")
        board.remove_piece_at(squares[0])
    board.castling_rights = board.clean_castling_rights()
