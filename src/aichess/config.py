"""Typed configuration (pydantic)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class MatchConfig(BaseModel):
    max_plies: int = 300
    move_timeout_seconds: float = 60
    illegal_move_retries: int = 3
    on_failure: Literal["forfeit", "random_move"] = "forfeit"
    start_fen: Optional[str] = None
    seed: Optional[int] = None
