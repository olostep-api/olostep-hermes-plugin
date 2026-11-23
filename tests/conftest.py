"""Test setup: stand in for Hermes' provider base class when Hermes isn't installed,
and route every Olostep API call through a mock transport."""

from __future__ import annotations

import abc
import json
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:  # pragma: no cover - real Hermes available
    import agent.web_search_provider  # noqa: F401
except ImportError:  # minimal stand-in mirroring agent/web_search_provider.py
    import os

    class WebSearchProvider(abc.ABC):
        @property
        @abc.abstractmethod
        def name(self) -> str: ...

        @abc.abstractmethod
        def is_available(self) -> bool: ...

    def get_provider_env(name: str) -> str:
        return os.getenv(name, "").strip()

    agent_pkg = types.ModuleType("agent")
    module = types.ModuleType("agent.web_search_provider")
    module.WebSearchProvider = WebSearchProvider  # type: ignore[attr-defined]
    module.get_provider_env = get_provider_env  # type: ignore[attr-defined]
    agent_pkg.web_search_provider = module  # type: ignore[attr-defined]
    sys.modules.setdefault("agent", agent_pkg)
    sys.modules.setdefault("agent.web_search_provider", module)

from olostep_hermes import client  # noqa: E402

Handler = Callable[[httpx.Request], httpx.Response]


class FakeApi:
    """Maps (method, path) to a JSON response or a callable, and records every request."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Any] = {}
        self.calls: list[httpx.Request] = []

    def on(self, method: str, path: str, response: Any, status: int = 200) -> None:
        self.routes[(method, path)] = (response, status)

    def body(self, index: int = -1) -> Any:
        return json.loads(self.calls[index].content or b"null")

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path.removeprefix("/v1")
        route = self.routes.get((request.method, path))
        if route is None:
            return httpx.Response(404, json={"detail": f"no fake for {request.method} {path}"})
        response, status = route
        if callable(response):
            return response(request)
        return httpx.Response(status, json=response)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> FakeApi:
    fake = FakeApi()
    monkeypatch.setenv("OLOSTEP_API_KEY", "test-key")
    monkeypatch.setattr(client, "_transport", httpx.MockTransport(fake))
    return fake
