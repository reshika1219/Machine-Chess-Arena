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

Model IDs: `claude-opus-5-5`, `claude-sonnet-5-5` (default), `claude-haiku-5-5`. Cheaper models make faster, weaker players, which is useful for Elo ladders.

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
Machine-Chess-Arena/
├── READ.md                     # this file
├── pyproject.toml
├── Dockerfile · docker-compose.yml
├── config.example.yaml         # one game
├── configs/players.example.yaml# a tournament line-up
├── .env.example                # ANTHROPIC_API_KEY=...
├── src/aichess/
│   ├── players/
│   │   ├── base.py             # Player interface (choose_move)
│   │   ├── llm.py              # Claude player: prompt, strict parser, token accounting
│   │   ├── stockfish.py        # any UCI engine
│   │   ├── random_player.py · greedy.py
│   │   └── factory.py          # PlayerConfig -> Player
│   ├── match.py                # referee: validation, retries, timeout, clock, openings, resume
│   ├── events.py               # GameStart / MoveEvent / GameOver + EventBus
│   ├── observers/              # terminal.py · pgn_writer.py · jsonl_logger.py
│   ├── runner.py               # build players, wire observers, run one game
│   ├── tournament.py · elo.py  # round-robin, Elo, leaderboard
│   ├── analysis.py             # centipawn loss / accuracy from a PGN
│   ├── config.py               # pydantic models + `type:arg,key=val` shorthand
│   ├── cli.py                  # `aichess` entry point
│   └── web/                    # server.py (FastAPI + WebSocket) · static/index.html
├── tests/                      # pytest suite (no network, no Stockfish required)
└── games/                      # generated output (gitignored)
```

---

## 11. Configuration

A full example lives in [config.example.yaml](config.example.yaml):

```yaml
match:
  max_plies: 300
  move_timeout_seconds: 60
  illegal_move_retries: 3
  on_failure: forfeit          # forfeit | random_move
  # clock_seconds: 300         # total thinking time per side; flagging loses
  # random_opening_plies: 4    # seeded random opening so repeat games differ
  # start_pgn: games/old/game.pgn   # resume a saved game
  # start_fen: "..."
  # seed: 42

white:
  type: llm
  model: claude-opus-5-5
  show_legal_moves: true
  # temperature: 0.3           # optional; omitted = model default

black:
  type: stockfish
  skill_level: 8               # 0-20, or `elo: 1500`
  movetime: 0.2

output:
  dir: games
  save_pgn: true
  save_jsonl: true
  display: terminal            # terminal | none  (use --web for the browser UI)
  show_board: true
```

Player shorthand for the CLI: `llm:<model>` · `stockfish:level=8` · `stockfish:elo=1500,movetime=0.1` · `random[:seed=1]` · `greedy`.

---

## 12. Setup

```bash
# 1. Python 3.10+ environment (3.12 recommended)
python3 -m venv .venv && source .venv/bin/activate      # or: uv venv --python 3.12
pip install -e ".[web,dev]"                              # or: uv pip install -e ".[web,dev]"

# 2. Stockfish (macOS) - optional, needed for stockfish players and `analyze`
brew install stockfish

# 3. API key - only for LLM players
cp .env.example .env            # then put your ANTHROPIC_API_KEY in it

# 4. Check everything works (offline)
pytest
```

Misconfiguration fails immediately with a clear message (missing key, bad Stockfish path) instead of forfeiting mid-game.

## 13. Usage

```bash
# One game, no API key or engine needed
aichess play --white greedy --black random

# LLM vs Stockfish (moves only, no board drawing)
aichess play --white llm:claude-opus-5-5 --black stockfish:level=8 --no-board

# LLM vs LLM with a 5-minute clock each, varied opening, lenient fallback
aichess play --white llm:claude-opus-5-5 --black llm:claude-haiku-5-5 \
    --clock 300 --random-opening 4 --seed 7 --on-failure random_move

# Watch live in the browser (open http://127.0.0.1:8000 and press Play)
aichess play --white llm:claude-opus-5-5 --black stockfish:elo=1500 --web

# From a config file
aichess play --config config.yaml

# Continue an interrupted/saved game
aichess play --white greedy --black random --resume games/<run>/game.pgn

# Tournament: round robin, alternating colours, Elo + leaderboard
aichess tournament --players configs/players.yaml --games 10

# Replay a saved game in the terminal
aichess replay games/<run>/game.pgn --delay 0.3

# Accuracy report for a saved game (needs Stockfish)
aichess analyze games/<run>/game.pgn
```

Each game writes `game.pgn`, `moves.jsonl` and `summary.json` into `games/<timestamp>_<white>_vs_<black>/`; tournaments also write `leaderboard.md` and `results.json`.

**Docker:** `docker compose run --rm arena play --white random --black greedy` (image bundles Stockfish).

**Web UI controls:** Play / Pause / Step buttons, a delay slider, move list, the last move's reasoning text (LLM players) and an eval bar (Stockfish players).

---

## 14. Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| **1 - Core** | Board wrapper, `Player` interface, Random/Greedy players, Match loop, terminal display, PGN output | Done |
| **2 - Engines & LLMs** | StockfishPlayer, LLMPlayer with retry/fallback, JSONL logging, config + CLI | Done |
| **3 - Experience** | Web UI with live board, reasoning panel, pause/step/speed | Done |
| **4 - Competition** | Tournament runner, Elo, leaderboard, accuracy analysis via Stockfish | Done |
| **5 - Polish** | Clocks, random openings, resume-from-PGN, API backoff, Docker | Done (opening *books* and personalities still open) |

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

Phases 1-5 are implemented and covered by an offline test suite (`pytest`, 39 tests): referee edge cases (fool's mate, stalemate, repetition, insufficient material, promotion, timeouts, clock, forged-board tampering), LLM prompt/parse/retry logic with a mocked client, a stub UCI engine, Elo, tournaments, analysis, resume/openings, PGN round-trips and the web socket stream.

**What has *not* been verified here, so test it on your machine first:**
- **Real Stockfish** - not installed on the dev machine; the player and `analyze` were tested against a stub engine only.
- **Real Claude API calls** - tested against a mocked client only (no API key was available). Run one short game with `--max-plies 20` before a long one.
- **Docker image** - written but never built.
- **Web UI visuals** - the server/WebSocket flow is tested, the page itself was not opened in a browser.

**Still open (see section 16):** opening books, LLM commentator, "coached" LLM with Stockfish as a tool, Chess960, handicaps, fine-tuning data export.
