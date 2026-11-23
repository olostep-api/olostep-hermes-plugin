"""Olostep plugin for Hermes Agent: web search and extract backend plus web data tools."""

from __future__ import annotations

from typing import Any

from .client import KEY_ENV, has_api_key
from .provider import OlostepWebSearchProvider
from .tools import TOOLS


def register(ctx: Any) -> None:
    """Called once by the Hermes plugin loader."""
    for name, schema, handler, emoji in TOOLS:
        ctx.register_tool(
            name=name,
            toolset="olostep",
            schema=schema,
            handler=handler,
            check_fn=has_api_key,
            requires_env=[KEY_ENV],
            is_async=True,
            description=schema["description"].split(". ")[0] + ".",
            emoji=emoji,
        )
    ctx.register_web_search_provider(OlostepWebSearchProvider())
