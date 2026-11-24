from __future__ import annotations

from ..config import PlayerConfig
from .base import Player
from .greedy import GreedyPlayer
from .llm import LLMPlayer
from .random_player import RandomPlayer
from .stockfish import StockfishPlayer


def build_player(cfg: PlayerConfig) -> Player:
    if cfg.type == "random":
        p: Player = RandomPlayer(cfg.seed)
    elif cfg.type == "greedy":
        p = GreedyPlayer(cfg.seed)
    elif cfg.type == "stockfish":
        p = StockfishPlayer(cfg.path, cfg.skill_level, cfg.elo, cfg.movetime, cfg.depth)
    elif cfg.type == "llm":
        p = LLMPlayer(cfg.model, cfg.temperature, cfg.max_tokens, cfg.show_legal_moves,
                      personality=cfg.personality, price_in_per_mtok=cfg.price_in_per_mtok,
                      price_out_per_mtok=cfg.price_out_per_mtok, budget_usd=cfg.budget_usd)
    else:  # pragma: no cover
        raise ValueError(f"unknown player type {cfg.type}")
    if cfg.name:
        p.name = cfg.name
    return p
