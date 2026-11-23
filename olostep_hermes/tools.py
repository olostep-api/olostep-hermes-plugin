"""Olostep agent tools: answers, site maps, crawls, batches and their results."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from . import client
from .client import OlostepError, dumps

PAGE_CHARS = 10_000  # per-page content cap returned to the model
MAX_BATCH_URLS = 100_000  # one Olostep batch holds up to 100k URLs
MAP_OUTPUT_LIMIT = 500
POLL_SECONDS = 3.0

ANSWER_SCHEMA: dict[str, Any] = {
    "name": "olostep_answer",
    "description": (
        "Answer a question from the live web with Olostep. Olostep searches, reads the sources and returns "
        "an answer with source URLs. Pass json_format to get the answer as structured JSON in that shape. "
        "Use for current facts, comparisons and research questions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "The question or research task, in plain language."},
            "json_format": {
                "type": "object",
                "description": 'Optional shape for a structured answer, e.g. {"name": "", "price": ""}.',
            },
        },
        "required": ["task"],
    },
}

MAP_SCHEMA: dict[str, Any] = {
    "name": "olostep_map",
    "description": (
        "List the URLs of a website with Olostep. Pass search_query to rank URLs by relevance and top_n to keep "
        "only the best matches, or filter with glob patterns such as /docs/**. Use it to find the right page on "
        "a site before extracting it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Website to map, e.g. https://docs.example.com"},
            "search_query": {"type": "string", "description": "Rank URLs by relevance to this query."},
            "top_n": {"type": "integer", "minimum": 1, "description": "Keep only the N most relevant URLs."},
            "include_urls": {"type": "array", "items": {"type": "string"}, "description": "Glob patterns to keep."},
            "exclude_urls": {"type": "array", "items": {"type": "string"}, "description": "Glob patterns to drop."},
        },
        "required": ["url"],
    },
}

CRAWL_SCHEMA: dict[str, Any] = {
    "name": "olostep_crawl",
    "description": (
        "Crawl a website with Olostep, starting from one URL and following its links, and return each page as "
        "markdown. Waits up to wait_seconds for the crawl to finish; a larger crawl returns a crawl id to pass to "
        "olostep_get_results later."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "start_url": {"type": "string", "description": "URL to start crawling from."},
            "max_pages": {"type": "integer", "minimum": 1, "default": 10, "description": "Maximum pages to crawl."},
            "max_depth": {"type": "integer", "minimum": 1, "description": "Maximum link depth from start_url."},
            "include_urls": {"type": "array", "items": {"type": "string"}, "description": "Glob patterns to follow."},
            "exclude_urls": {"type": "array", "items": {"type": "string"}, "description": "Glob patterns to skip."},
            "search_query": {"type": "string", "description": "Prioritise pages relevant to this query."},
            "wait_seconds": {
                "type": "integer",
                "minimum": 0,
                "maximum": 300,
                "default": 60,
                "description": "How long to wait for the crawl before returning its id.",
            },
        },
        "required": ["start_url"],
    },
}

BATCH_SCHEMA: dict[str, Any] = {
    "name": "olostep_batch",
    "description": (
        "Scrape many URLs in one Olostep batch job (up to 100,000 URLs per batch). Returns a batch id at once; "
        "the job runs in the background (a large batch takes up to 20-25 minutes), so call olostep_get_results "
        "with the id to collect the pages. For a handful of URLs, web_extract is faster."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": MAX_BATCH_URLS,
                "description": "URLs to scrape.",
            },
        },
        "required": ["urls"],
    },
}

RESULTS_SCHEMA: dict[str, Any] = {
    "name": "olostep_get_results",
    "description": (
        "Get the status and pages of an Olostep crawl or batch started earlier, with each page's markdown. "
        "Pass the id returned by olostep_crawl or olostep_batch. Use cursor to page through large jobs."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "A crawl id (crawl_...) or batch id (batch_...)."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10, "description": "Pages to return."},
            "cursor": {
                "type": "integer",
                "minimum": 0,
                "description": "Cursor from a previous call, for the next page.",
            },
            "include_content": {"type": "boolean", "default": True, "description": "Include each page's markdown."},
        },
        "required": ["job_id"],
    },
}


def _fail(message: str) -> str:
    return dumps({"success": False, "error": message})


def _str_list(value: Any) -> list[str] | None:
    if not value:
        return None
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if item]


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, [], "")}


async def answer_handler(args: dict[str, Any], **_: Any) -> str:
    task = str(args.get("task") or "").strip()
    if not task:
        return _fail("task is required")
    try:
        data = await client.arequest(
            "POST",
            "/answers",
            json_body=_compact({"task": task, "json_format": args.get("json_format")}),
            timeout=180.0,
        )
    except OlostepError as exc:
        return _fail(str(exc))
    result = data.get("result") or {}
    answer: Any = result.get("json_content")
    if isinstance(answer, str):
        try:
            answer = json.loads(answer)
        except ValueError:
            pass
    return dumps({"success": True, "answer": answer, "sources": result.get("sources") or []})


async def map_handler(args: dict[str, Any], **_: Any) -> str:
    url = str(args.get("url") or "").strip()
    if not url:
        return _fail("url is required")
    body = _compact(
        {
            "url": url,
            "search_query": args.get("search_query"),
            "top_n": args.get("top_n"),
            "include_urls": _str_list(args.get("include_urls")),
            "exclude_urls": _str_list(args.get("exclude_urls")),
        }
    )
    try:
        data = await client.arequest("POST", "/maps", json_body=body, timeout=180.0)
    except OlostepError as exc:
        return _fail(str(exc))
    urls = data.get("urls") or []
    payload: dict[str, Any] = {
        "success": True,
        "urls_count": data.get("urls_count", len(urls)),
        "urls": urls[:MAP_OUTPUT_LIMIT],
    }
    if len(urls) > MAP_OUTPUT_LIMIT:
        payload["note"] = f"Showing the first {MAP_OUTPUT_LIMIT} URLs; pass search_query and top_n to narrow the list."
    return dumps(payload)


async def _page_markdown(retrieve_id: str) -> tuple[str, bool]:
    data = await client.arequest("GET", "/retrieve", params={"retrieve_id": retrieve_id, "formats": "markdown"})
    return client.truncate(data.get("markdown_content") or "", PAGE_CHARS)


async def _with_content(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    async def one(page: dict[str, Any]) -> dict[str, Any]:
        entry = {"url": page.get("url"), "custom_id": page.get("custom_id")}
        retrieve_id = page.get("retrieve_id")
        if not retrieve_id:
            return _compact({**entry, "error": "No content stored for this page"})
        try:
            markdown, truncated = await _page_markdown(retrieve_id)
        except OlostepError as exc:
            return _compact({**entry, "error": str(exc)})
        return _compact({**entry, "markdown": markdown, "truncated": truncated or None})

    return list(await asyncio.gather(*(one(page) for page in pages)))


async def _job_results(job_id: str, limit: int, cursor: int | None, include_content: bool) -> dict[str, Any]:
    if job_id.startswith("crawl_"):
        kind, info_path, list_path, list_key, params = (
            "crawl",
            f"/crawls/{job_id}",
            f"/crawls/{job_id}/pages",
            "pages",
            {},
        )
    elif job_id.startswith("batch_"):
        kind, info_path, list_path, list_key = "batch", f"/batches/{job_id}", f"/batches/{job_id}/items", "items"
        params = {"status": "completed"}
    else:
        raise OlostepError("job_id must be a crawl id (crawl_...) or a batch id (batch_...)")
    info = await client.arequest("GET", info_path)
    listing = await client.arequest("GET", list_path, params=_compact({**params, "limit": limit, "cursor": cursor}))
    pages = listing.get(list_key) or []
    entries = (
        await _with_content(pages)
        if include_content
        else [_compact({"url": p.get("url"), "custom_id": p.get("custom_id")}) for p in pages]
    )
    payload: dict[str, Any] = {
        "success": True,
        "id": job_id,
        "type": kind,
        "status": info.get("status"),
        "pages": entries,
    }
    if kind == "crawl":
        payload["pages_count"] = info.get("pages_count")
    else:
        payload["total_urls"] = info.get("total_urls")
        payload["completed_urls"] = info.get("completed_urls")
    next_cursor = listing.get("cursor")
    if next_cursor and len(pages) >= limit:
        payload["next_cursor"] = next_cursor
    return payload


def _limit(args: dict[str, Any]) -> int:
    try:
        return max(1, min(int(args.get("limit") or 10), 50))
    except (TypeError, ValueError):
        return 10


async def crawl_handler(args: dict[str, Any], **_: Any) -> str:
    start_url = str(args.get("start_url") or "").strip()
    if not start_url:
        return _fail("start_url is required")
    body = _compact(
        {
            "start_url": start_url,
            "max_pages": args.get("max_pages") or 10,
            "max_depth": args.get("max_depth"),
            "include_urls": _str_list(args.get("include_urls")),
            "exclude_urls": _str_list(args.get("exclude_urls")),
            "search_query": args.get("search_query"),
        }
    )
    try:
        wait = max(0.0, min(float(args.get("wait_seconds", 60)), 300.0))
    except (TypeError, ValueError):
        wait = 60.0
    try:
        started = await client.arequest("POST", "/crawls", json_body=body)
        crawl_id = started.get("id")
        if not crawl_id:
            return _fail("Olostep did not return a crawl id")
        deadline = time.monotonic() + wait
        status = started.get("status")
        while status not in ("completed", "failed") and time.monotonic() < deadline:
            await asyncio.sleep(POLL_SECONDS)
            status = (await client.arequest("GET", f"/crawls/{crawl_id}")).get("status")
        if status != "completed":
            return dumps(
                {
                    "success": status != "failed",
                    "id": crawl_id,
                    "status": status,
                    "note": "The crawl is still running. Call olostep_get_results with this id to collect the pages."
                    if status != "failed"
                    else "The crawl failed.",
                }
            )
        return dumps(await _job_results(crawl_id, _limit(args), None, True))
    except OlostepError as exc:
        return _fail(str(exc))


async def batch_handler(args: dict[str, Any], **_: Any) -> str:
    urls = _str_list(args.get("urls")) or []
    if not urls:
        return _fail("urls is required")
    if len(urls) > MAX_BATCH_URLS:
        return _fail(f"One batch holds up to {MAX_BATCH_URLS:,} URLs; split the list into several batches.")
    items = [{"custom_id": str(index), "url": url} for index, url in enumerate(urls)]
    try:
        data = await client.arequest("POST", "/batches", json_body={"items": items}, timeout=120.0)
    except OlostepError as exc:
        return _fail(str(exc))
    return dumps(
        {
            "success": True,
            "id": data.get("id"),
            "status": data.get("status"),
            "total_urls": data.get("total_urls", len(urls)),
            "note": "The batch runs in the background. Call olostep_get_results with this id to collect the pages.",
        }
    )


async def results_handler(args: dict[str, Any], **_: Any) -> str:
    job_id = str(args.get("job_id") or "").strip()
    if not job_id:
        return _fail("job_id is required")
    cursor = args.get("cursor")
    try:
        cursor_value = int(cursor) if cursor not in (None, "") else None
    except (TypeError, ValueError):
        return _fail("cursor must be a number from a previous call")
    include_content = args.get("include_content", True) is not False
    try:
        return dumps(await _job_results(job_id, _limit(args), cursor_value, include_content))
    except OlostepError as exc:
        return _fail(str(exc))


TOOLS = (
    ("olostep_answer", ANSWER_SCHEMA, answer_handler, "💡"),
    ("olostep_map", MAP_SCHEMA, map_handler, "🗺️"),
    ("olostep_crawl", CRAWL_SCHEMA, crawl_handler, "🕸️"),
    ("olostep_batch", BATCH_SCHEMA, batch_handler, "📦"),
    ("olostep_get_results", RESULTS_SCHEMA, results_handler, "📥"),
)
