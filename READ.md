# Machine-Chess-Arena — AI vs AI Chess

A project where two AI players play a full game of chess against each other. Players are pluggable: each side can be an LLM (e.g. Claude), a classical engine (Stockfish), or a simple baseline (random / greedy). The system referees the game, enforces the rules, records everything, and shows the game live.

This README is both the **design document** (how to build it the best way) and the **user guide** (how to run it once built).

---

## 1. Goals

1. Run a complete, rules-correct chess game between two AIs, start to finish.
2. Make players interchangeable: LLM vs LLM, LLM vs Stockfish, Stockfish vs Stockfish, etc.
3. Never let an AI cheat or corrupt the game (illegal moves are caught, not trusted).
4. Record every game (PGN + structured log) so it can be replayed and analysed.
5. Let us watch games live (terminal first, web UI later).
6. Support tournaments and rating (Elo) to compare AIs fairly.

**Non-goals (for v1):** training our own chess neural network, online matchmaking, user accounts.

---

## 2. The key design decision: don't write chess rules yourself

Chess rules (castling, en passant, promotion, pins, check, checkmate, stalemate, threefold repetition, fifty-move rule, insufficient material) are easy to get subtly wrong. Use a proven library as the **single source of truth**.

| Need | Choice | Why |
|---|---|---|
| Language | **Python 3.11+** | Best chess + AI ecosystem |
| Rules / board / PGN | **[python-chess](https://python-chess.readthedocs.io/)** | Complete, well-tested, handles UCI/SAN/PGN/FEN |
| Strong classical AI | **[Stockfish](https://stockfishchess.org/)** via UCI | Gold-standard engine, adjustable strength |
| LLM AI | **Anthropic API** (Claude) | Plays by reasoning in text |
| Web UI (later) | **FastAPI + WebSocket + chessboard.js** | Live board in the browser |
| Tests | **pytest** | Standard |
| Config | **YAML + pydantic** | Typed, validated settings |

**Golden rule:** the AI *proposes* a move; the referee (python-chess) *decides* if it is legal. AIs never mutate the board directly.

---

## 3. Architecture

```
            ┌──────────────────────────────────────────┐
            │                  Match                   │
            │  (referee loop, clock, termination)      │
            └───────┬──────────────────────┬───────────┘
                    │ asks for move        │ asks for move
             ┌──────▼──────┐        ┌──────▼──────┐
             │ Player WHITE│        │ Player BLACK│
             │ (interface) │        │ (interface) │
             └──────┬──────┘        └──────┬──────┘
        ┌───────────┼───────────┐          │ (same options)
 ┌──────▼─────┐ ┌───▼────┐ ┌────▼─────┐
 │ LLMPlayer  │ │Stockfish│ │ Random / │
 │ (Claude)   │ │ Player  │ │ Greedy   │
 └────────────┘ └────────┘ └──────────┘
                    │
        ┌───────────▼───────────┐
        │   Board (python-chess)│  ← single source of truth
        └───────────┬───────────┘
                    │ events (move made, game over…)
        ┌───────────▼───────────────────────────┐
        │ Observers: Terminal UI · PGN writer ·  │
        │ JSONL logger · Web UI (WebSocket)      │
        └────────────────────────────────────────┘
```

### Components

- **Player (interface):** one method, `choose_move(board, context) -> chess.Move`. Everything else is an implementation detail. This is what makes the project flexible.
- **Match / Referee:** owns the board, alternates turns, validates every move, enforces time and retry limits, detects game end, publishes events.
- **Observers:** subscribe to events (move played, game over). Terminal renderer, PGN writer, logger and web UI are all just observers, so adding one never touches game logic.
- **Tournament runner:** plays many matches (swapping colours), collects results, computes Elo.

---

## 4. Player types

### 4.1 LLMPlayer (Claude)
LLMs are weak at tracking board state from memory, so we help them:

**Prompt contents (every turn):**
- The current position as **FEN** (exact, unambiguous).
- An ASCII board diagram (helps the model "see" it).
- The **move history in SAN** (e.g. `1. e4 e5 2. Nf3 Nc6`).
- The **list of legal moves** (in UCI or SAN). This removes most illegal-move errors.
- Which colour it is playing, and a short instruction on the output format.

**Output format:** ask for a single move in UCI (`e2e4`) inside a tag, e.g. `<move>e2e4</move>`, optionally with brief reasoning before it. Parse strictly with a regex.

**Illegal / unparseable move handling:**
1. Reject the move, tell the model *why* and re-list the legal moves.
2. Retry up to N times (default 3).
3. If it still fails, apply the configured **fallback policy**: forfeit (strict) or play a random legal move (lenient). Always log that it happened.

**Tuning knobs:** model name, temperature, max tokens, whether to allow "thinking" before the move, personality/system prompt.

Use the `claude-api` guidance / latest model IDs when wiring this up (e.g. `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`). Cheaper models make faster, weaker players, which is useful for Elo ladders.

### 4.2 StockfishPlayer
- Launch Stockfish with `chess.engine.SimpleEngine.popen_uci(path)`.
- Control strength via `Skill Level` (0–20), `UCI_LimitStrength` + `UCI_Elo`, or a time/depth limit per move.
- Close the engine process cleanly at the end (context manager).

### 4.3 Baseline players
- **RandomPlayer:** uniformly random legal move. Sanity-check baseline; every serious AI must crush it.
- **GreedyPlayer:** picks the capture with the best material gain (else random). A slightly harder baseline.

### 4.4 Adding your own
Implement the `Player` interface (e.g. another LLM provider, a local model, your own minimax) and register it in the player factory. Nothing else changes.

---

## 5. The game loop (referee logic)

```
board = Board()
while not board.is_game_over(claim_draw=True):
    player = players[board.turn]
    move = ask_with_retries(player, board)     # validates legality
    board.push(move)
    emit(MoveEvent(...))
result = board.result(claim_draw=True)
emit(GameOverEvent(result, reason))
```

**Termination reasons to report:** checkmate, stalemate, insufficient material, threefold repetition, fifty-move rule, timeout, forfeit (illegal moves), max-move-limit (safety cap, e.g. 300 plies → draw), manual abort.

**Safety limits (important for LLM games, which cost money):**
- Max plies per game.
- Max tokens / max cost budget per game.
- Per-move timeout.
- Optional per-side chess clock.

---

## 6. Logging & output

Every game produces, in `games/<timestamp>_<white>_vs_<black>/`:

- `game.pgn` — standard PGN with headers (players, date, result, termination). Opens in Lichess/ChessBase.
- `moves.jsonl` — one JSON line per move: ply, side, FEN before, move (UCI+SAN), time taken, tokens used, number of retries, raw model reply.
- `summary.json` — result, reason, totals, illegal-move counts, cost.

This makes games reproducible, debuggable and analysable (e.g. feed the PGN to Stockfish to compute **accuracy / centipawn loss** per player).

---

## 7. Display

**v1 — Terminal:** print the board after every move using python-chess's Unicode board (or `rich` for colour), plus the move list and a status line.

**v2 — Web UI:** FastAPI backend streams events over WebSocket; the browser renders a board with chessboard.js, shows the move list, eval bar and each AI's reasoning text. Includes pause / step / speed controls.

---

## 8. Tournaments & rating

- Round-robin or ladder between configured players.
- **Alternate colours** and play an even number of games per pairing (white has an edge).
- Compute **Elo** from results; optionally anchor against Stockfish at known strengths so ratings mean something.
- Output a leaderboard table (`leaderboard.md`).

---

## 9. Testing strategy

- **Unit tests:** move parsing (UCI/SAN), illegal-move retry path, fallback policy, PGN output.
- **Fake players:** a scripted player returning a fixed move list lets us test the referee deterministically (e.g. Fool's mate, stalemate, repetition, promotion).
- **Mock the LLM:** inject a fake API client that returns garbage/illegal moves to verify robustness, so tests are free and offline.
- **Integration:** Random vs Random for 100 games must always terminate with a valid result.
- **Property check:** after every game, replaying the PGN from the start must reproduce the final FEN.

---

## 10. Project structure

```
BetterOne/
├── README.md
├── pyproject.toml
├── config.example.yaml
├── .env.example                # ANTHROPIC_API_KEY=...
├── src/aichess/
│   ├── __init__.py
│   ├── players/
│   │   ├── base.py             # Player interface
│   │   ├── llm.py              # Claude player (prompting, parsing, retries)
│   │   ├── stockfish.py
│   │   ├── random_player.py
│   │   ├── greedy.py
│   │   └── factory.py          # build player from config
│   ├── match.py                # referee loop, limits, termination
│   ├── events.py               # event types + simple pub/sub
│   ├── observers/
│   │   ├── terminal.py
│   │   ├── pgn_writer.py
│   │   └── jsonl_logger.py
│   ├── tournament.py           # many games + Elo
│   ├── elo.py
│   ├── config.py               # pydantic models
│   ├── cli.py                  # entry point
│   └── web/                    # (phase 3) FastAPI app + static frontend
├── tests/
│   ├── test_match.py
│   ├── test_llm_parsing.py
│   ├── test_players.py
│   └── test_tournament.py
└── games/                      # generated output (gitignored)
```

---

## 11. Configuration (example)

```yaml
# config.example.yaml
match:
  max_plies: 300
  move_timeout_seconds: 60
  illegal_move_retries: 3
  on_failure: forfeit          # forfeit | random_move

white:
  type: llm
  provider: anthropic
  model: claude-opus-5-5
  temperature: 0.3
  show_legal_moves: true

black:
  type: stockfish
  path: /opt/homebrew/bin/stockfish
  skill_level: 8               # 0-20

output:
  dir: games
  save_pgn: true
  save_jsonl: true
  display: terminal            # terminal | web | none
```

---

## 12. Setup (once implemented)

```bash
# 1. Python environment
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Stockfish (macOS)
brew install stockfish

# 3. API key
cp .env.example .env           # then put your ANTHROPIC_API_KEY in it
```

## 13. Usage (planned CLI)

```bash
# One game, LLM vs Stockfish
aichess play --white llm:claude-opus-5-5 --black stockfish:level=8

# LLM vs LLM
aichess play --white llm:claude-opus-5-5 --black llm:claude-haiku-5-5

# From a config file
aichess play --config config.yaml

# Tournament (10 games per pairing, alternating colours)
aichess tournament --players configs/players.yaml --games 10

# Replay a saved game in the terminal
aichess replay games/2026-11-23_.../game.pgn
```

---

## 14. Roadmap

| Phase | Deliverable | Done when |
|---|---|---|
| **1 — Core** | Board wrapper, `Player` interface, Random/Greedy players, Match loop, terminal display, PGN output | Random vs Random plays 100 valid games |
| **2 — Engines & LLMs** | StockfishPlayer, LLMPlayer with retry/fallback, JSONL logging, config + CLI | Claude vs Stockfish finishes a game with every illegal move handled |
| **3 — Experience** | Web UI with live board, reasoning panel, pause/step/speed | Game watchable in the browser |
| **4 — Competition** | Tournament runner, Elo, leaderboard, accuracy analysis via Stockfish | Leaderboard generated from a batch of games |
| **5 — Polish** | Clocks, opening books, personalities, cost tracking, Docker | One-command run on a fresh machine |

---

## 15. Risks & how we handle them

| Risk | Mitigation |
|---|---|
| LLM plays illegal moves | Provide legal-move list; validate; retry with feedback; fallback policy |
| LLM "forgets" the position | Send FEN + history + ASCII board every turn (stateless prompts) |
| Games never end / cost explosion | Max plies, token/cost budget, move timeout |
| Unparseable replies | Strict tag format + regex, retry on failure |
| Stockfish process leaks | Context manager, always `quit()` in `finally` |
| Unfair comparisons | Alternate colours, even game counts, fixed seeds/openings |
| API outages / rate limits | Exponential backoff, resume-from-PGN support |
| API key leaks | `.env` only, gitignored, never logged |

---

## 16. Ideas for later

- Opening book / randomised openings so repeated matches differ.
- LLM "commentator" that narrates the game.
- Let the LLM call Stockfish as a *tool* (a "coached" LLM) vs a pure LLM — compare ratings.
- Self-play data collection for fine-tuning.
- Chess960 (Fischer Random) support.
- Time-odds handicaps.
- Spectator mode with shareable replay links.

---

## 17. Glossary

- **FEN:** a one-line text snapshot of a position.
- **PGN:** standard text format for a whole game.
- **SAN:** human move notation (`Nf3`, `exd5`, `O-O`).
- **UCI (moves):** machine move notation (`g1f3`, `e7e8q`). Also the protocol engines speak.
- **Ply:** one half-move (one side's move). 2 plies = 1 full move.
- **Elo:** rating system estimating relative playing strength.
- **Centipawn loss:** how much worse a move was than the best one, in 1/100 pawn units.

---

## 18. Status

📝 Design complete — implementation not started. Next step: Phase 1 (core + baseline players).
