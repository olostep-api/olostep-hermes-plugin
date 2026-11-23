"""The manifest must match what register() actually registers (catalog rule 6)."""

from __future__ import annotations

import re
from pathlib import Path

import olostep_hermes
from olostep_hermes.provider import OlostepWebSearchProvider

MANIFEST = (Path(__file__).resolve().parents[1] / "plugin.yaml").read_text()


def _manifest_list(key: str) -> list[str]:
    block = re.search(rf"^{key}:\n((?:  - .+\n)+)", MANIFEST, re.MULTILINE)
    return re.findall(r"  - (\S+)", block.group(1)) if block else []


class FakeCtx:
    def __init__(self) -> None:
        self.tools: list[dict] = []
        self.providers: list = []

    def register_tool(self, **kwargs) -> None:
        self.tools.append(kwargs)

    def register_web_search_provider(self, provider) -> None:
        self.providers.append(provider)


def test_register_matches_manifest():
    ctx = FakeCtx()
    olostep_hermes.register(ctx)
    assert [t["name"] for t in ctx.tools] == _manifest_list("provides_tools")
    assert [p.name for p in ctx.providers] == _manifest_list("provides_web_providers") == ["olostep"]
    assert isinstance(ctx.providers[0], OlostepWebSearchProvider)
    for tool in ctx.tools:
        assert tool["toolset"] == "olostep" and tool["is_async"] is True
        assert tool["schema"]["name"] == tool["name"]
        assert tool["requires_env"] == ["OLOSTEP_API_KEY"]


def test_versions_agree():
    from olostep_hermes.client import PLUGIN_VERSION

    assert f'version: "{PLUGIN_VERSION}"' in MANIFEST
