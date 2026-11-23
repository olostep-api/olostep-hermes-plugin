# Olostep plugin for Hermes Agent

Live web search, scraping and crawling for [Hermes Agent](https://hermes-agent.nousresearch.com), powered by [Olostep](https://www.olostep.com).

The plugin does two things:

1. **Backs Hermes' built-in `web_search` and `web_extract` tools** with Olostep, so every agent, skill and subagent that searches or reads the web uses it.
2. **Adds five tools** for work the built-in tools don't cover: answers with sources, site maps, crawls and batch scraping.

## Why Olostep

Olostep is web data infrastructure for AI agents and enterprise AI workflows. Its APIs provide live web search, scraping and crawling to extract, clean and structure data from the web.

From a handful of URLs to hundreds of millions of pages, Olostep gives developers, AI companies and enterprises reliable, cost-effective access to clean, structured web data at scale. It is built for performance and high concurrency: up to 100k URLs in a single batch, and 1M with 10 parallel batches. Pages are rendered with JavaScript, so single-page apps and dynamic sites come back complete.

New accounts get **500 free credits**, no credit card required.

## Install

```bash
hermes plugins install olostep
```

Hermes asks for your `OLOSTEP_API_KEY` during install. Get one at [olostep.com/dashboard](https://www.olostep.com/dashboard).

To install from this repository instead:

```bash
hermes plugins install https://github.com/olostep-api/olostep-hermes-plugin
```

## Use Olostep for web_search and web_extract

Pick Olostep in `hermes tools`, or set it in `config.yaml`:

```yaml
web:
  search_backend: olostep
  extract_backend: olostep
```

| Built-in tool | Olostep endpoint | What you get |
|---|---|---|
| `web_search` | `/v1/searches` | Title, URL and description for up to 25 results |
| `web_extract` | `/v1/scrapes` | Each page as clean markdown (or HTML), JavaScript rendered, with its title |

## Tools

| Tool | What it does |
|---|---|
| `olostep_answer` | Answers a question from the live web, with source URLs. Pass `json_format` to get the answer as JSON in your shape. |
| `olostep_map` | Lists a site's URLs, ranked by `search_query`, filtered by glob patterns such as `/docs/**`. |
| `olostep_crawl` | Crawls a site from one URL and returns each page as markdown. Waits up to `wait_seconds` (default 60), then hands back a crawl id for larger crawls. |
| `olostep_batch` | Starts a batch scrape of up to 100,000 URLs. Returns a batch id immediately. |
| `olostep_get_results` | Status and pages of a crawl or batch, with each page's markdown, paged with `cursor`. |

Examples you can give the agent:

- "What do the top three vector databases charge for their entry plan? Answer as a table with sources."
- "Find the rate-limit page in the Stripe docs and summarise it."
- "Crawl docs.example.com/guides and list every page that mentions webhooks."
- "Scrape these 2,000 product URLs and tell me when the batch is done."

### What a single call returns

These keep tool output to a size the model can read. They are not Olostep limits:

- `olostep_map` returns the first 500 URLs and the total count; use `search_query` and `top_n` to narrow it.
- `olostep_crawl` and `olostep_get_results` return up to 50 pages per call (default 10), each capped at 10,000 characters of markdown. Page through the rest with `cursor`.

## Disclosure

- Search queries, URLs, answer tasks and crawl or batch settings are sent to the Olostep API (`api.olostep.com`) with your `OLOSTEP_API_KEY`.
- Every call uses Olostep credits from your account.
- The key is read through Hermes' profile-scoped credential lookup. The plugin reads no other files, runs no shell commands, starts no background processes, sends no telemetry and does not update itself.
- Before a URL is sent for extraction, Hermes' URL safety check and website policy are applied, so private and internal addresses are refused.

## Development

```bash
uv venv && uv pip install "httpx>=0.27,<1" pytest==9.0.2 pytest-asyncio==1.3.0 "ruff>=0.15,<0.17"
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
hermes plugins validate . --install-deps
```

The tests mock the Olostep API and don't need Hermes installed.

## Links

- [Olostep](https://www.olostep.com)
- [Olostep docs](https://docs.olostep.com)
- [Hermes Agent plugin catalog](https://hermes-agent.nousresearch.com/marketplace)

## License

MIT
