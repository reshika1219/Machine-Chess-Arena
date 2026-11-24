from types import SimpleNamespace

import chess
import pytest

from aichess.config import MatchConfig
from aichess.match import Match
from aichess.players.base import MoveContext
from aichess.players.llm import LLMPlayer, build_prompt, parse_move
from aichess.players.random_player import RandomPlayer


class FakeClient:
    """Mimics anthropic.Anthropic().messages.create with canned replies."""

    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.prompts.append(kw["messages"][0]["content"])
        text = self.replies.pop(0) if self.replies else "<move>e2e4</move>"
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def test_parse_uci_san_and_last_tag_wins():
    b = chess.Board()
    assert parse_move("<move>e2e4</move>", b).uci() == "e2e4"
    assert parse_move("<move>Nf3</move>", b).uci() == "g1f3"
    assert parse_move("maybe <move>d2d4</move> no, <move>c2c4</move>", b).uci() == "c2c4"


@pytest.mark.parametrize("text", ["I play e4", "<move>e2e5</move>", "<move></move>", ""])
def test_parse_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_move(text, chess.Board())


def test_prompt_contains_fen_history_legal_moves_and_feedback():
    b = chess.Board()
    b.push_san("e4")
    p = build_prompt(b, MoveContext(2, ["e4"], feedback="bad move"))
    assert b.fen() in p and "1. e4" in p and "e7e5" in p and "bad move" in p and "playing Black" in p
    assert "Legal moves" not in build_prompt(b, MoveContext(2, ["e4"]), show_legal_moves=False)


def test_player_returns_move_and_token_usage():
    p = LLMPlayer(client=FakeClient(["thinking... <move>g1f3</move>"]))
    res = p.choose_move(chess.Board(), MoveContext(1, []))
    assert res.move.uci() == "g1f3" and res.info["input_tokens"] == 10 and "thinking" in res.info["raw_reply"]


def test_referee_recovers_from_illegal_llm_reply_with_feedback():
    client = FakeClient(["<move>e2e5</move>", "no tag at all", "<move>e2e4</move>"])
    llm = LLMPlayer(client=client, name="fake-llm")
    events = []
    from aichess.events import EventBus, MoveEvent
    bus = EventBus(); bus.subscribe(events.append)
    Match(llm, RandomPlayer(1), MatchConfig(max_plies=2), bus).play()
    first = [e for e in events if isinstance(e, MoveEvent)][0]
    assert first.uci == "e2e4" and first.retries == 2
    assert "rejected" in client.prompts[1] and "e2e5" in client.prompts[1]


def test_temperature_only_sent_when_set():
    seen = {}
    client = FakeClient([])
    orig = client.messages.create
    client.messages.create = lambda **kw: (seen.update(kw), orig(**kw))[1]
    LLMPlayer(client=client).choose_move(chess.Board(), MoveContext(1, []))
    assert "temperature" not in seen
    LLMPlayer(client=client, temperature=0.3).choose_move(chess.Board(), MoveContext(1, []))
    assert seen["temperature"] == 0.3


def test_personality_added_to_system_prompt_and_unknown_rejected():
    p = LLMPlayer(client=FakeClient([]), personality="aggressive")
    assert "Your style" in p.system_prompt and "aggressively" in p.system_prompt
    assert "Your style" not in LLMPlayer(client=FakeClient([])).system_prompt
    with pytest.raises(ValueError):
        LLMPlayer(client=FakeClient([]), personality="sleepy")


def test_cost_tracking_and_budget_stop():
    from aichess.players.llm import BudgetExceeded
    p = LLMPlayer(client=FakeClient([]), price_in_per_mtok=1000, price_out_per_mtok=2000, budget_usd=0.025)
    r = p.choose_move(chess.Board(), MoveContext(1, []))
    assert r.info["cost_usd"] == pytest.approx((10 * 1000 + 5 * 2000) / 1e6)   # 0.02
    p.choose_move(chess.Board(), MoveContext(1, []))                           # 0.04 total now
    with pytest.raises(BudgetExceeded):
        p.choose_move(chess.Board(), MoveContext(1, []))
    assert p.total_tokens == {"input": 20, "output": 10}


def test_cost_absent_without_prices():
    r = LLMPlayer(client=FakeClient([])).choose_move(chess.Board(), MoveContext(1, []))
    assert "cost_usd" not in r.info


class ToolClient:
    """First reply asks for the engine tool, then answers with a move."""

    def __init__(self, tool_rounds=1, final="Engine says e4. <move>e2e4</move>"):
        self.rounds, self.final, self.calls = tool_rounds, final, []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        if self.rounds > 0:
            self.rounds -= 1
            blk = SimpleNamespace(type="tool_use", id=f"t{len(self.calls)}", name="engine_analysis", input={"lines": 2})
            return SimpleNamespace(content=[blk], stop_reason="tool_use", usage=usage)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.final)], stop_reason="end_turn", usage=usage)


class FakeCoach:
    def __init__(self): self.seen = []
    def analyse(self, board, lines=3): self.seen.append(lines); return "1. e2e4 (eval +0.30)"
    def close(self): self.closed = True


def test_coached_llm_uses_tool_then_answers():
    client, coach = ToolClient(), FakeCoach()
    p = LLMPlayer(client=client, coach=coach)
    res = p.choose_move(chess.Board(), MoveContext(1, []))
    assert res.move.uci() == "e2e4" and coach.seen == [2]
    assert res.info["tool_calls"] == 1 and res.info["input_tokens"] == 20
    assert "tools" in client.calls[0] and "engine_analysis" in p.system_prompt
    last = client.calls[1]["messages"][-1]["content"][0]
    assert last["type"] == "tool_result" and "e2e4" in last["content"]


def test_coach_tool_call_limit_and_engine_errors_do_not_break_the_move():
    class Boom(FakeCoach):
        def analyse(self, board, lines=3): raise RuntimeError("engine died")
    client = ToolClient(tool_rounds=3)
    p = LLMPlayer(client=client, coach=Boom(), max_tool_calls=2)
    res = p.choose_move(chess.Board(), MoveContext(1, []))
    assert res.move.uci() == "e2e4" and res.info["tool_calls"] == 3
    msgs = client.calls[-1]["messages"]   # the same list object is shared by every call
    results = [m["content"][0]["content"] for m in msgs if m["role"] == "user" and isinstance(m["content"], list)]
    assert "engine unavailable" in results[0] and "limit reached" in results[2]


def test_engine_coach_formats_lines_with_stub_engine():
    import chess.engine
    from aichess.players.coach import EngineCoach
    b = chess.Board()
    class Stub:
        def analyse(self, board, limit, multipv=1):
            return [{"pv": [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")], "score": chess.engine.PovScore(chess.engine.Cp(35), chess.WHITE)},
                    {"pv": [chess.Move.from_uci("d2d4")], "score": chess.engine.PovScore(chess.engine.Mate(3), chess.WHITE)}]
        def quit(self): pass
    out = EngineCoach(engine=Stub()).analyse(b, 2)
    assert "1. e2e4 (eval +0.35) line: e4 e5" in out and "mate in 3" in out
