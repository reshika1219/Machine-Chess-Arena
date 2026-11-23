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
