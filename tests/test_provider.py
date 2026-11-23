from __future__ import annotations

import pytest

from olostep_hermes import provider as provider_module
from olostep_hermes.provider import OlostepWebSearchProvider

LINKS = [
    {"url": "https://a.example", "title": "A", "description": "first"},
    {"url": "", "title": "no url", "description": "dropped"},
    {"url": "https://b.example", "title": "B", "description": None},
]


def test_identity_and_capabilities(api):
    p = OlostepWebSearchProvider()
    assert (p.name, p.display_name) == ("olostep", "Olostep")
    assert p.is_available() and p.supports_search() and p.supports_extract()


def test_not_available_without_key(monkeypatch):
    monkeypatch.delenv("OLOSTEP_API_KEY", raising=False)
    assert OlostepWebSearchProvider().is_available() is False


def test_search_returns_hermes_envelope(api):
    api.on("POST", "/searches", {"result": {"links": LINKS}})
    result = OlostepWebSearchProvider().search("hermes agent", limit=5)
    assert result == {
        "success": True,
        "data": {
            "web": [
                {"title": "A", "url": "https://a.example", "description": "first", "position": 1},
                {"title": "B", "url": "https://b.example", "description": "", "position": 2},
            ]
        },
    }
    assert api.body() == {"query": "hermes agent", "limit": 5}
    assert api.calls[-1].headers["Authorization"] == "Bearer test-key"


@pytest.mark.parametrize(("asked", "sent"), [(100, 25), (0, 1), ("x", 5)])
def test_search_clamps_limit(api, asked, sent):
    api.on("POST", "/searches", {"result": {"links": []}})
    OlostepWebSearchProvider().search("q", limit=asked)
    assert api.body()["limit"] == sent


@pytest.mark.parametrize(
    ("status", "fragment"),
    [(401, "rejected the API key"), (402, "out of credits"), (429, "rate limit"), (500, "HTTP 500: boom")],
)
def test_search_errors_are_reported_not_raised(api, status, fragment):
    api.on("POST", "/searches", {"detail": "boom"}, status=status)
    result = OlostepWebSearchProvider().search("q")
    assert result["success"] is False and fragment in result["error"]


def test_search_without_key_explains_setup(monkeypatch):
    monkeypatch.delenv("OLOSTEP_API_KEY", raising=False)
    result = OlostepWebSearchProvider().search("q")
    assert result["success"] is False and "OLOSTEP_API_KEY" in result["error"]


async def test_extract_markdown_with_title(api):
    api.on(
        "POST",
        "/scrapes",
        {
            "retrieve_id": "r1",
            "result": {"markdown_content": "# Example Domain\n\nBody", "page_metadata": {"status_code": 200}},
        },
    )
    [item] = await OlostepWebSearchProvider().extract(["https://example.com"])
    assert item["title"] == "Example Domain"
    assert item["content"] == item["raw_content"] == "# Example Domain\n\nBody"
    assert item["metadata"] == {"source": "olostep", "status_code": 200, "retrieve_id": "r1"}
    assert api.body() == {"url_to_scrape": "https://example.com", "formats": ["markdown", "html"]}


async def test_extract_html_format(api):
    api.on("POST", "/scrapes", {"result": {"html_content": "<h1>Hi</h1>", "markdown_content": None}})
    [item] = await OlostepWebSearchProvider().extract(["https://example.com"], format="html")
    assert item["content"] == "<h1>Hi</h1>"


async def test_extract_keeps_order_and_reports_per_url_errors(api):
    def scrape(request):
        import json

        import httpx

        url = json.loads(request.content)["url_to_scrape"]
        if "bad" in url:
            return httpx.Response(500, json={"detail": "upstream"})
        if "empty" in url:
            return httpx.Response(200, json={"result": {"markdown_content": "", "page_metadata": {"status_code": 404}}})
        return httpx.Response(200, json={"result": {"markdown_content": f"# {url}"}})

    api.on("POST", "/scrapes", scrape)
    urls = ["https://ok.example", "https://bad.example", "https://empty.example"]
    items = await OlostepWebSearchProvider().extract(urls)
    assert [i["url"] for i in items] == urls
    assert "error" not in items[0]
    assert "HTTP 500" in items[1]["error"]
    assert "page status 404" in items[2]["error"]


async def test_extract_skips_refused_urls(api, monkeypatch):
    monkeypatch.setattr(
        provider_module,
        "_refusal",
        lambda url: provider_module._error_item(url, "Blocked by policy") if "internal" in url else None,
    )
    api.on("POST", "/scrapes", {"result": {"markdown_content": "ok"}})
    items = await OlostepWebSearchProvider().extract(["http://internal.local", "https://ok.example"])
    assert items[0]["error"] == "Blocked by policy"
    assert len(api.calls) == 1


def test_setup_schema_names_key(api):
    schema = OlostepWebSearchProvider().get_setup_schema()
    assert schema["env_vars"][0]["key"] == "OLOSTEP_API_KEY"
    assert "500 free credits" in schema["tag"]


async def test_extract_title_prefers_html_title(api):
    api.on(
        "POST",
        "/scrapes",
        {"result": {"markdown_content": "Body only", "html_content": "<title>\n Example &amp; Co </title>"}},
    )
    [item] = await OlostepWebSearchProvider().extract(["https://example.com"])
    assert item["title"] == "Example & Co"
    assert item["content"] == "Body only"


async def test_extract_title_from_heading_strips_links(api):
    api.on("POST", "/scrapes", {"result": {"markdown_content": "## [](#why)Why [Olostep](https://o.example)?"}})
    [item] = await OlostepWebSearchProvider().extract(["https://example.com"])
    assert item["title"] == "Why Olostep?"
