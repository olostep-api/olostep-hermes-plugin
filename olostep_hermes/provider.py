"""Olostep backend for Hermes' built-in web_search and web_extract tools.

Select it with::

    web:
      search_backend: olostep
      extract_backend: olostep
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent.web_search_provider import WebSearchProvider

from . import client
from .client import OlostepError

logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 25  # /v1/searches accepts 1-25
SEARCH_TIMEOUT = 60.0
SCRAPE_TIMEOUT = 120.0  # JavaScript-heavy pages can take a while to render
MAX_PARALLEL_SCRAPES = 5


def _error_item(url: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"url": url, "title": "", "content": "", "raw_content": "", "error": message, **extra}


def _refusal(url: str) -> dict[str, Any] | None:
    """Apply Hermes' URL safety and website policy before sending a URL to Olostep."""
    try:
        from tools.url_safety import is_safe_url

        if not is_safe_url(url):
            return _error_item(url, "Blocked by policy: private or internal network address")
    except ImportError:
        pass
    try:
        from tools.website_policy import check_website_access
    except ImportError:
        return None
    blocked = check_website_access(url)
    if blocked:
        return _error_item(url, blocked.get("message") or "Blocked by the website policy")
    return None


class OlostepWebSearchProvider(WebSearchProvider):
    """Web search via /v1/searches and page extraction via /v1/scrapes."""

    @property
    def name(self) -> str:
        return "olostep"

    @property
    def display_name(self) -> str:
        return "Olostep"

    def is_available(self) -> bool:
        return client.has_api_key()

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        try:
            count = max(1, min(int(limit), MAX_SEARCH_RESULTS))
        except (TypeError, ValueError):
            count = 5
        try:
            data = client.request(
                "POST", "/searches", json_body={"query": query, "limit": count}, timeout=SEARCH_TIMEOUT
            )
        except OlostepError as exc:
            return {"success": False, "error": str(exc)}
        links = (data.get("result") or {}).get("links") or []
        web = [
            {
                "title": link.get("title") or "",
                "url": link.get("url") or "",
                "description": link.get("description") or "",
                "position": position,
            }
            for position, link in enumerate((link for link in links if link.get("url")), start=1)
        ][:count]
        return {"success": True, "data": {"web": web}}

    async def extract(self, urls: list[str], **kwargs: Any) -> list[dict[str, Any]]:
        fmt = "html" if kwargs.get("format") == "html" else "markdown"
        semaphore = asyncio.Semaphore(MAX_PARALLEL_SCRAPES)

        async def one(url: str) -> dict[str, Any]:
            refused = _refusal(url)
            if refused:
                return refused
            async with semaphore:
                return await self._scrape(url, fmt)

        results = await asyncio.gather(*(one(url) for url in urls), return_exceptions=True)
        return [
            _error_item(url, str(result)) if isinstance(result, BaseException) else result
            for url, result in zip(urls, results, strict=True)
        ]

    async def _scrape(self, url: str, fmt: str) -> dict[str, Any]:
        # HTML is always requested too (same credit cost) because it carries the page <title>.
        try:
            data = await client.arequest(
                "POST",
                "/scrapes",
                json_body={"url_to_scrape": url, "formats": ["markdown", "html"]},
                timeout=SCRAPE_TIMEOUT,
            )
        except OlostepError as exc:
            return _error_item(url, str(exc))
        result = data.get("result") or {}
        markdown = result.get("markdown_content") or ""
        html = result.get("html_content") or ""
        content = markdown if fmt == "markdown" else html
        status = (result.get("page_metadata") or {}).get("status_code")
        if not content:
            message = f"Olostep returned no content (page status {status})" if status else "Olostep returned no content"
            return _error_item(url, message)
        return {
            "url": url,
            "title": client.page_title(html, markdown),
            "content": content,
            "raw_content": content,
            "metadata": {"source": "olostep", "status_code": status, "retrieve_id": data.get("retrieve_id")},
        }

    def get_setup_schema(self) -> dict[str, Any]:
        return {
            "name": "Olostep",
            "badge": "paid",
            "tag": "Web search and JavaScript-rendered page extraction. New accounts get 500 free credits.",
            "env_vars": [{"key": client.KEY_ENV, "prompt": "Olostep API key", "url": client.KEY_URL}],
        }
