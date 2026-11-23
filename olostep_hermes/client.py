"""Small HTTP client for the Olostep API (https://docs.olostep.com)."""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.olostep.com/v1"
KEY_ENV = "OLOSTEP_API_KEY"
KEY_URL = "https://www.olostep.com/dashboard"
PLUGIN_VERSION = "0.1.0"

# Replaced in tests with an httpx.MockTransport.
_transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None


class OlostepError(Exception):
    """An Olostep API call failed; the message is safe to show to the model."""


def get_api_key() -> str:
    """Return OLOSTEP_API_KEY through Hermes' profile-aware lookup, or "" when unset."""
    try:
        from agent.web_search_provider import get_provider_env

        return get_provider_env(KEY_ENV)
    except ImportError:
        pass
    try:
        from agent.secret_scope import get_secret

        return (get_secret(KEY_ENV) or "").strip()
    except ImportError:
        return ""


def has_api_key() -> bool:
    return bool(get_api_key())


def _user_agent() -> str:
    try:
        from hermes_cli.version_info import hermes_user_agent

        return f"olostep-hermes-plugin/{PLUGIN_VERSION} {hermes_user_agent('Hermes-Agent')}"
    except Exception:  # noqa: BLE001 - optional on older Hermes releases
        return f"olostep-hermes-plugin/{PLUGIN_VERSION}"


def _headers() -> dict[str, str]:
    key = get_api_key()
    if not key:
        raise OlostepError(f"Olostep is not configured. Set {KEY_ENV} (get a key at {KEY_URL}).")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": _user_agent(),
    }


def _error_message(response: httpx.Response) -> str:
    status = response.status_code
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = str(body.get("detail") or body.get("message") or body.get("title") or "")
    except ValueError:
        detail = response.text[:200]
    if status == 401:
        return f"Olostep rejected the API key (HTTP 401). Check {KEY_ENV}."
    if status == 402:
        return f"The Olostep account is out of credits (HTTP 402). Top up at {KEY_URL}."
    if status == 429:
        return "Olostep rate limit reached (HTTP 429). Retry in a moment."
    return f"Olostep returned HTTP {status}" + (f": {detail}" if detail else "")


def _parse(response: httpx.Response) -> dict[str, Any]:
    if response.status_code >= 400:
        raise OlostepError(_error_message(response))
    try:
        data = response.json()
    except ValueError as exc:
        raise OlostepError("Olostep returned a response that is not JSON") from exc
    if not isinstance(data, dict):
        raise OlostepError("Olostep returned an unexpected response")
    return data


def request(
    method: str, path: str, *, json_body: Any = None, params: Any = None, timeout: float = 60.0
) -> dict[str, Any]:
    """Synchronous API call; raises OlostepError on any failure."""
    headers = _headers()
    try:
        with httpx.Client(timeout=timeout, transport=_transport) as client:  # type: ignore[arg-type]
            response = client.request(method, f"{API_BASE}{path}", json=json_body, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise OlostepError(f"Olostep did not answer within {timeout:.0f}s") from exc
    except httpx.RequestError as exc:
        raise OlostepError(f"Could not reach Olostep: {exc}") from exc
    return _parse(response)


async def arequest(
    method: str, path: str, *, json_body: Any = None, params: Any = None, timeout: float = 60.0
) -> dict[str, Any]:
    """Asynchronous API call; raises OlostepError on any failure."""
    headers = _headers()
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=_transport) as client:  # type: ignore[arg-type]
            response = await client.request(method, f"{API_BASE}{path}", json=json_body, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise OlostepError(f"Olostep did not answer within {timeout:.0f}s") from exc
    except httpx.RequestError as exc:
        raise OlostepError(f"Could not reach Olostep: {exc}") from exc
    return _parse(response)


_HTML_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def page_title(html: str, markdown: str) -> str:
    """The page's <title>, else its first markdown heading (scrapes return no title field)."""
    match = _HTML_TITLE.search(html or "")
    if match:
        title = html_lib.unescape(" ".join(match.group(1).split()))
        if title:
            return title
    match = _HEADING.search(markdown or "")
    return " ".join(_LINK.sub(r"\1", match.group(1)).split()) if match else ""


def truncate(text: str, limit: int) -> tuple[str, bool]:
    if text and len(text) > limit:
        return text[:limit], True
    return text or "", False


def dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)
