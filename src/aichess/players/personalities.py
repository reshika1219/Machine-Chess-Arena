"""Playing-style presets appended to the LLM system prompt."""
from __future__ import annotations

PERSONALITIES: dict[str, str] = {
    "balanced": "",
    "aggressive": "Play aggressively: favour initiative, piece activity, attacks on the king and "
                  "sound sacrifices over safe material.",
    "positional": "Play positionally: prefer structure, space, good piece placement and long-term "
                  "plans over early tactics. Avoid unnecessary risks.",
    "cautious": "Play very safely: before every move check what your opponent can capture or "
                "threaten in reply, and never leave a piece undefended.",
    "tactician": "Hunt for tactics: forks, pins, skewers, discovered attacks and combinations. "
                 "Check every forcing move (checks, captures, threats) before a quiet one.",
    "endgame": "Aim to simplify into favourable endgames: trade pieces when ahead, activate "
               "your king early, and create passed pawns.",
}


def style_prompt(name: str | None) -> str:
    if not name:
        return ""
    try:
        extra = PERSONALITIES[name.lower()]
    except KeyError:
        raise ValueError(f"unknown personality '{name}'. Choose from: {', '.join(PERSONALITIES)}") from None
    return f"\n\nYour style: {extra}" if extra else ""
