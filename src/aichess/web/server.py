"""Live web UI: runs the game in a background thread and streams events over a WebSocket."""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import GameConfig
from ..events import GameOver, GameStart, MoveEvent
from ..runner import run_game

STATIC = Path(__file__).parent / "static"


class Pacer:
    """Observer that throttles the game: play/pause/step and a delay between moves."""

    def __init__(self) -> None:
        self.delay = 1.0
        self._play = threading.Event()   # set => running
        self._step = threading.Event()
        self._abort = False

    def __call__(self, ev: object) -> None:
        if not isinstance(ev, MoveEvent):
            return
        deadline = time.monotonic() + self.delay
        while not self._abort:
            if self._step.is_set():
                self._step.clear()
                return
            if self._play.is_set() and time.monotonic() >= deadline:
                return
            time.sleep(0.05)

    def wait_until_started(self) -> None:
        while not (self._play.is_set() or self._step.is_set()) and not self._abort:
            time.sleep(0.05)

    def command(self, cmd: str, value: Any = None) -> None:
        if cmd == "play":
            self._play.set()
        elif cmd == "pause":
            self._play.clear()
        elif cmd == "step":
            self._step.set()
        elif cmd == "speed":
            self.delay = max(0.0, float(value))

    def abort(self) -> None:
        self._abort = True


def _to_dict(ev: object) -> dict:
    d = asdict(ev)  # type: ignore[arg-type]
    d["type"] = type(ev).__name__
    d["info"] = {k: v for k, v in d.get("info", {}).items()}
    return d


def create_app(cfg: GameConfig, autostart: bool = True) -> FastAPI:
    app = FastAPI(title="Machine-Chess-Arena")
    events: list[dict] = []
    clients: set[WebSocket] = set()
    pacer = Pacer()
    state: dict[str, Any] = {"loop": None, "done": False, "error": None}

    async def broadcast(msg: dict) -> None:
        for ws in list(clients):
            try:
                await ws.send_json(msg)
            except Exception:
                clients.discard(ws)

    def observer(ev: object) -> None:
        msg = _to_dict(ev)
        events.append(msg)
        if state["loop"] is not None:
            asyncio.run_coroutine_threadsafe(broadcast(msg), state["loop"])

    def run() -> None:
        try:
            pacer.wait_until_started()
            if not pacer._abort:
                run_game(cfg, [observer, pacer])
        except Exception as exc:  # surface errors (missing API key, no stockfish...) in the UI
            state["error"] = str(exc)
            msg = {"type": "Error", "message": str(exc)}
            events.append(msg)
            if state["loop"] is not None:
                asyncio.run_coroutine_threadsafe(broadcast(msg), state["loop"])
        finally:
            state["done"] = True

    @app.on_event("startup")
    async def _startup() -> None:
        state["loop"] = asyncio.get_running_loop()
        if autostart:
            threading.Thread(target=run, daemon=True).start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        pacer.abort()

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/state")
    async def api_state() -> dict:
        return {"events": events, "done": state["done"], "error": state["error"]}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        for msg in list(events):          # replay history so late joiners catch up
            await ws.send_json(msg)
        clients.add(ws)
        try:
            while True:
                data = await ws.receive_json()
                pacer.command(data.get("cmd", ""), data.get("value"))
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(ws)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def serve_game(cfg: GameConfig, host: str = "127.0.0.1", port: int = 8000) -> int:
    import uvicorn

    print(f"Open http://{host}:{port} in your browser, then press Play.")
    uvicorn.run(create_app(cfg), host=host, port=port, log_level="warning")
    return 0
