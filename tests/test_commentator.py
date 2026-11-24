from types import SimpleNamespace

from aichess.config import MatchConfig
from aichess.events import Commentary, EventBus
from aichess.match import Match
from aichess.observers.commentator import Commentator
from aichess.players.random_player import RandomPlayer


class Client:
    def __init__(self, fail=False):
        self.fail, self.prompts = fail, []
        self.messages = SimpleNamespace(create=self._c)

    def _c(self, **kw):
        self.prompts.append(kw["messages"][0]["content"])
        if self.fail:
            raise RuntimeError("api down")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=f"remark {len(self.prompts)}")])


def play(client, plies=6, every=2):
    bus, got = EventBus(), []
    bus.subscribe(got.append)
    bus.subscribe(Commentator(bus.emit, client, every=every))
    res = Match(RandomPlayer(1), RandomPlayer(2), MatchConfig(max_plies=plies), bus).play()
    return res, [e for e in got if isinstance(e, Commentary)]


def test_commentary_emitted_every_n_plies_plus_summary():
    client = Client()
    _, comments = play(client, plies=6, every=2)
    assert [c.ply for c in comments if c.kind == "move"] == [2, 4, 6]
    assert comments[-1].kind == "summary" and len(comments) == 4
    assert "FEN:" in client.prompts[0]


def test_api_failure_never_breaks_the_game():
    res, comments = play(Client(fail=True))
    assert res.plies == 6 and comments == []
