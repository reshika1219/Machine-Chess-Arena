"""The referee: owns the board, validates every move, detects the end of the game."""
from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Optional

import chess
import chess.pgn

from .config import MatchConfig
from .events import EventBus, GameOver, GameStart, MoveEvent
from .players.base import MoveContext, MoveResult, Player

SIDE = {chess.WHITE: "white", chess.BLACK: "black"}


@dataclass
class GameResult:
    result: str
    reason: str
    plies: int
    final_fen: str
    illegal_attempts: dict[str, int]
    fallbacks: dict[str, int]


class Match:
    def __init__(
        self,
        white: Player,
        black: Player,
        config: Optional[MatchConfig] = None,
        bus: Optional[EventBus] = None,
    ) -> None:
        self.players = {chess.WHITE: white, chess.BLACK: black}
        self.cfg = config or MatchConfig()
        self.bus = bus or EventBus()
        self.rng = random.Random(self.cfg.seed)
        self.base_fen = self.cfg.start_fen or chess.STARTING_FEN
        if self.cfg.chess960 and not self.cfg.start_fen:
            pos = self.cfg.chess960_position
            self.chess960_position = self.rng.randrange(960) if pos is None else pos
            self.base_fen = chess.Board.from_chess960_pos(self.chess960_position).fen()
        self.board = chess.Board(self.base_fen, chess960=self.cfg.chess960)
        self.handicap = ""
        if self.cfg.material_odds:
            from .handicap import apply_material_odds
            apply_material_odds(self.board, self.cfg.material_odds)
            self.base_fen = self.board.fen()
            self.handicap = f"material odds {self.cfg.material_odds}"
        self._history_san: list[str] = []
        self.prior_moves: list[str] = []
        self._apply_prior_moves()
        self.clock = {
            "white": self.cfg.clock_seconds_white if self.cfg.clock_seconds_white is not None else self.cfg.clock_seconds,
            "black": self.cfg.clock_seconds_black if self.cfg.clock_seconds_black is not None else self.cfg.clock_seconds,
        }
        if self.clock["white"] != self.clock["black"]:
            note = f"time odds {self.clock['white']}s vs {self.clock['black']}s"
            self.handicap = f"{self.handicap}; {note}" if self.handicap else note
        self.start_clock = dict(self.clock)
        self.illegal = {"white": 0, "black": 0}
        self.fallbacks = {"white": 0, "black": 0}
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._abort = False

    def _push_prior(self, move: chess.Move) -> None:
        self._history_san.append(self.board.san(move))
        self.prior_moves.append(move.uci())
        self.board.push(move)

    def _apply_prior_moves(self) -> None:
        """Resume from a PGN and/or play a few random opening plies."""
        if self.cfg.start_pgn:
            with open(self.cfg.start_pgn) as f:
                game = chess.pgn.read_game(f)
            if game is None:
                raise ValueError(f"no game found in {self.cfg.start_pgn}")
            self.board = game.board()
            self.base_fen = self.board.fen()
            self.cfg.chess960 = self.board.chess960
            for node in game.mainline():
                self._push_prior(node.move)
        for uci in self.cfg.opening_moves:
            move = chess.Move.from_uci(uci)
            if move not in self.board.legal_moves:
                raise ValueError(f"opening move {uci} is illegal in {self.board.fen()}")
            self._push_prior(move)
        for _ in range(self.cfg.random_opening_plies):
            if self.board.is_game_over():
                break
            self._push_prior(self.rng.choice(list(self.board.legal_moves)))

    def abort(self) -> None:
        self._abort = True

    # ---- asking a player for a legal move -------------------------------------------------
    def _ask(self, player: Player, ctx: MoveContext) -> MoveResult:
        fut = self._pool.submit(player.choose_move, self.board.copy(stack=False), ctx)
        return fut.result(timeout=self.cfg.move_timeout_seconds)

    def _get_move(self, color: chess.Color) -> tuple[Optional[chess.Move], dict, int, bool]:
        """Returns (move or None if forfeit, info, retries, used_fallback)."""
        player = self.players[color]
        side = SIDE[color]
        feedback: Optional[str] = None
        info: dict = {}
        for attempt in range(self.cfg.illegal_move_retries + 1):
            ctx = MoveContext(
                ply=len(self.board.move_stack) + 1,
                history_san=list(self._history_san),
                feedback=feedback,
                attempt=attempt,
            )
            try:
                res = self._ask(player, ctx)
                info = res.info
                if res.move in self.board.legal_moves:
                    return res.move, info, attempt, False
                feedback = f"{res.move.uci()} is not a legal move in this position."
            except FutureTimeout:
                feedback = "You ran out of time for that move."
            except Exception as exc:  # parse errors, API errors, engine crashes
                feedback = f"Your reply could not be used: {exc}"
            self.illegal[side] += 1
        if self.cfg.on_failure == "random_move":
            self.fallbacks[side] += 1
            return self.rng.choice(list(self.board.legal_moves)), info, self.cfg.illegal_move_retries, True
        return None, info, self.cfg.illegal_move_retries, False

    # ---- the game loop ---------------------------------------------------------------------
    def play(self) -> GameResult:
        w, b = self.players[chess.WHITE].name, self.players[chess.BLACK].name
        self.bus.emit(GameStart(w, b, self.base_fen, list(self.prior_moves), self.board.fen(),
                                chess960=self.board.chess960, clock_seconds=dict(self.start_clock),
                                handicap=self.handicap))
        result, reason = "*", "unknown"
        try:
            while True:
                if self._abort:
                    result, reason = "*", "aborted"
                    break
                outcome = self.board.outcome(claim_draw=True)
                if outcome is not None:
                    result = outcome.result()
                    reason = outcome.termination.name.lower()
                    break
                if len(self.board.move_stack) >= self.cfg.max_plies:
                    result, reason = "1/2-1/2", "max_plies"
                    break

                color = self.board.turn
                t0 = time.monotonic()
                move, info, retries, fb = self._get_move(color)
                if move is None:
                    result = "0-1" if color == chess.WHITE else "1-0"
                    reason = "forfeit_illegal_moves"
                    break
                elapsed = time.monotonic() - t0
                if self.clock[SIDE[color]] is not None:
                    self.clock[SIDE[color]] -= elapsed
                    if self.clock[SIDE[color]] < 0:
                        result = "0-1" if color == chess.WHITE else "1-0"
                        reason = "timeout"
                        break
                    info = {**info, "clock_left": round(self.clock[SIDE[color]], 2)}
                fen_before = self.board.fen()
                san = self.board.san(move)
                self.board.push(move)
                self._history_san.append(san)
                self.bus.emit(MoveEvent(
                    ply=len(self.board.move_stack), side=SIDE[color], player=self.players[color].name,
                    fen_before=fen_before, uci=move.uci(), san=san, fen_after=self.board.fen(),
                    seconds=time.monotonic() - t0, retries=retries, fallback=fb, info=info,
                ))
        finally:
            self._pool.shutdown(wait=False, cancel_futures=True)
        plies = len(self.board.move_stack)
        self.bus.emit(GameOver(result, reason, plies, self.board.fen()))
        return GameResult(result, reason, plies, self.board.fen(), dict(self.illegal), dict(self.fallbacks))
