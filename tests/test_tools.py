from __future__ import annotations

import json

import pytest

from olostep_hermes import tools


def run(result: str) -> dict:
    return json.loads(result)


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch):
    monkeypatch.setattr(tools, "POLL_SECONDS", 0)


async def test_answer_decodes_json_content(api):
    api.on("POST", "/answers", {"result": {"json_content": '{"year": "1889"}', "sources": ["https://s.example"]}})
    out = run(await tools.answer_handler({"task": "When was the Eiffel Tower completed?", "json_format": {"year": ""}}))
    assert out == {"success": True, "answer": {"year": "1889"}, "sources": ["https://s.example"]}
    assert api.body() == {"task": "When was the Eiffel Tower completed?", "json_format": {"year": ""}}


async def test_answer_requires_task(api):
    assert run(await tools.answer_handler({}))["success"] is False
    assert api.calls == []


async def test_map_sends_filters_and_caps_output(api):
    urls = [f"https://x.example/{i}" for i in range(600)]
    api.on("POST", "/maps", {"urls": urls, "urls_count": 600})
    out = run(await tools.map_handler({"url": "https://x.example", "search_query": "docs", "include_urls": "/docs/**"}))
    assert out["urls_count"] == 600 and len(out["urls"]) == 500 and "note" in out
    assert api.body() == {"url": "https://x.example", "search_query": "docs", "include_urls": ["/docs/**"]}


async def test_batch_starts_job(api):
    api.on("POST", "/batches", {"id": "batch_1", "status": "in_progress", "total_urls": 2})
    out = run(await tools.batch_handler({"urls": ["https://a.example", "https://b.example"]}))
    assert out["id"] == "batch_1" and out["total_urls"] == 2
    assert api.body()["items"] == [
        {"custom_id": "0", "url": "https://a.example"},
        {"custom_id": "1", "url": "https://b.example"},
    ]


async def test_batch_rejects_more_than_100k(api):
    out = run(await tools.batch_handler({"urls": ["https://a.example"] * 100_001}))
    assert out["success"] is False and "100,000" in out["error"]
    assert api.calls == []


async def test_crawl_waits_then_returns_pages(api):
    api.on("POST", "/crawls", {"id": "crawl_1", "status": "in_progress"})
    api.on("GET", "/crawls/crawl_1", {"status": "completed", "pages_count": 1})
    api.on(
        "GET", "/crawls/crawl_1/pages", {"pages": [{"url": "https://e.example/", "retrieve_id": "r1"}], "cursor": None}
    )
    api.on("GET", "/retrieve", {"markdown_content": "# Page"})
    out = run(await tools.crawl_handler({"start_url": "https://e.example", "max_pages": 2}))
    assert out["status"] == "completed" and out["pages_count"] == 1
    assert out["pages"] == [{"url": "https://e.example/", "markdown": "# Page"}]
    assert api.body(0) == {"start_url": "https://e.example", "max_pages": 2}


async def test_crawl_returns_id_when_still_running(api):
    api.on("POST", "/crawls", {"id": "crawl_2", "status": "in_progress"})
    out = run(await tools.crawl_handler({"start_url": "https://e.example", "wait_seconds": 0}))
    assert out["id"] == "crawl_2" and out["status"] == "in_progress" and "olostep_get_results" in out["note"]


async def test_results_for_batch_truncates_content_and_pages(api, monkeypatch):
    monkeypatch.setattr(tools, "PAGE_CHARS", 5)
    api.on("GET", "/batches/batch_1", {"status": "in_progress", "total_urls": 3, "completed_urls": 2})
    api.on(
        "GET",
        "/batches/batch_1/items",
        {
            "items": [
                {"url": "https://a.example", "custom_id": "0", "retrieve_id": "r1"},
                {"url": "https://b.example", "custom_id": "1"},
            ],
            "cursor": 2,
        },
    )
    api.on("GET", "/retrieve", {"markdown_content": "0123456789"})
    out = run(await tools.results_handler({"job_id": "batch_1", "limit": 2}))
    assert out["completed_urls"] == 2 and out["next_cursor"] == 2
    assert out["pages"][0] == {"url": "https://a.example", "custom_id": "0", "markdown": "01234", "truncated": True}
    assert "error" in out["pages"][1]
    items_call = next(c for c in api.calls if c.url.path.endswith("/items"))
    assert items_call.url.params["status"] == "completed" and items_call.url.params["limit"] == "2"


async def test_results_without_content_skips_retrieve(api):
    api.on("GET", "/crawls/crawl_1", {"status": "completed", "pages_count": 1})
    api.on("GET", "/crawls/crawl_1/pages", {"pages": [{"url": "https://e.example/", "retrieve_id": "r1"}]})
    out = run(await tools.results_handler({"job_id": "crawl_1", "include_content": False}))
    assert out["pages"] == [{"url": "https://e.example/"}]
    assert not any(c.url.path.endswith("/retrieve") for c in api.calls)


async def test_results_rejects_unknown_id(api):
    out = run(await tools.results_handler({"job_id": "abc"}))
    assert out["success"] is False and "crawl id" in out["error"]
