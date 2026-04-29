# red-crawler

CLI crawler for collecting Xiaohongshu creator contact leads from profile bios and recommendation chains, with SQLite persistence and nightly automation.

## Usage

Install the published CLI:

```bash
uv tool install red-crawler==0.1.3
```

Install the Playwright browser runtime:

```bash
red-crawler install-browsers
```

For local development from a checkout:

```bash
uv sync
uv run playwright install chromium
```

Run without logging in. If Xiaohongshu shows a login popup, the crawler tries to close it and continue.

Collect creators from the Xiaohongshu fashion homefeed:

```bash
red-crawler crawl-homefeed \
  --max-accounts 20 \
  --db-path "./data/red_crawler.db" \
  --output-dir "./output"
```

The default homefeed URL is `https://www.xiaohongshu.com/explore?channel_id=homefeed.fashion_v3`. The crawler reads each card's author link and opens the user profile, not the note page.

Run a manual crawl from a known user profile:

```bash
red-crawler crawl-seed \
  --seed-url "https://www.xiaohongshu.com/user/profile/USER_ID" \
  --max-accounts 20 \
  --max-depth 2 \
  --gender-filter "女" \
  --db-path "./data/red_crawler.db" \
  --output-dir "./output"
```

`crawl-seed` defaults to safe mode, adding slower request pacing and dwell/scroll delays that look more like a normal browsing session. Use `--no-safe-mode` only if you explicitly want a faster run.

Use `--gender-filter "男"` or `--gender-filter "女"` to keep only inferred male or female accounts in the exported and persisted crawl results.

Use Bright Data Browser API instead of launching local Chromium:

```bash
export BRIGHT_DATA_BROWSER_API_AUTH="SBR_ZONE_FULL_USERNAME:SBR_ZONE_PASSWORD"

red-crawler crawl-search \
  --search-term "抗痘博主" \
  --browser-mode bright-data \
  --output-dir "./output"
```

You can also pass the full CDP endpoint directly:

```bash
red-crawler crawl-seed \
  --seed-url "https://www.xiaohongshu.com/user/profile/USER_ID" \
  --browser-mode bright-data \
  --browser-endpoint "wss://SBR_ZONE_FULL_USERNAME:SBR_ZONE_PASSWORD@brd.superproxy.io:9222"
```

`crawl-seed` now does both:

- exports `accounts.csv`, `contact_leads.csv`, `run_report.json`
- upserts the same result into SQLite

### Browser IP rotation

Bright Data Browser API mode rotates by opening a fresh browser session on retry. If your Bright Data username, password, or endpoint contains `{session}`, red-crawler replaces it with a random session id for each browser session:

```bash
red-crawler crawl-homefeed \
  --browser-mode bright-data \
  --browser-auth "brd-customer-xxx-zone-xxx-session-{session}:PASSWORD" \
  --rotation-mode session \
  --rotation-retries 2
```

In local browser mode, red-crawler cannot rotate the machine's real IP by itself. Provide one proxy with `--proxy` or a newline-delimited proxy pool with `--proxy-list`; session rotation will launch a new Chromium session with the next proxy after `403` or `429`.

```bash
red-crawler crawl-homefeed \
  --proxy-list "./proxies.txt" \
  --rotation-mode session \
  --rotation-retries 3 \
  --output-dir "./output"
```

Proxy entries can be `host:port`, `http://user:pass@host:port`, or `socks5://host:port`. By default, each proxy maps deterministically to one `User-Agent`, `Accept-Language`, and `Sec-CH-UA` header set, so the same outbound IP does not appear with a different browser fingerprint on a later retry. Direct local mode uses one stable local fingerprint. Use `--no-randomize-headers` only for debugging.

Run a manual crawl for one explicit search term without a `seed_url`:

```bash
red-crawler crawl-search \
  --search-term "抗痘博主" \
  --max-accounts 20 \
  --search-scroll-rounds 8 \
  --creator-only \
  --min-followers 5000 \
  --min-relevance-score 0.7 \
  --db-path "./data/red_crawler.db" \
  --output-dir "./output"
```

想尽量覆盖某个搜索词下的博主时，可以把 `--search-scroll-rounds` 和 `--max-accounts` 调大，同时配合 `--creator-only`、`--min-followers`、`--min-relevance-score` 做收口。这里的“全量”只能是尽量覆盖，平台搜索结果本身不是稳定全量接口，而且滚动过深会明显增加风控概率。

Optional note-page expansion:

```bash
red-crawler crawl-seed \
  --seed-url "https://www.xiaohongshu.com/user/profile/USER_ID" \
  --include-note-recommendations
```

List high-quality contactable creators from the SQLite database:

```bash
red-crawler list-contactable \
  --db-path "./data/red_crawler.db" \
  --min-relevance-score 0.7 \
  --limit 20
```

Run nightly auto-collection with queue, search bootstrap, seed promotion, and daily report output:

```bash
red-crawler collect-nightly \
  --db-path "./data/red_crawler.db" \
  --report-dir "./reports" \
  --cache-dir "./.cache/red-crawler" \
  --crawl-budget 12 \
  --daily-account-budget 12 \
  --daily-search-term-budget 2
```

`collect-nightly` now enforces a daily budget across all runs started on the same UTC day. If you schedule multiple slots, later runs automatically shrink or skip once the daily profile/search-term budget is used up.

Run the same discovery flow manually without a `seed_url`:

```bash
red-crawler crawl-discover \
  --db-path "./data/red_crawler.db" \
  --report-dir "./reports" \
  --cache-dir "./.cache/red-crawler" \
  --crawl-budget 6
```

Export weekly growth report and a contactable creator CSV:

```bash
red-crawler report-weekly \
  --db-path "./data/red_crawler.db" \
  --report-dir "./reports" \
  --days 7
```

Key outputs:

- manual crawl:
  - `accounts.csv`
  - `contact_leads.csv`
  - `run_report.json`
- nightly automation:
  - `reports/daily-run-report.json`
  - `reports/weekly-growth-report.json`
  - `reports/contactable_creators.csv`
- SQLite database:
  - `data/red_crawler.db`

## OpenClaw

The OpenClaw skill for this project lives at `openclaw-skills/red-crawler-ops/`.

To install it from a local path, point OpenClaw at that folder, or copy the skill directory into your OpenClaw skills location and register the same path.

Use the OpenClaw skill actions in this order:

- `bootstrap` validates a local working directory and can run Chromium installation when explicitly requested.
- `crawl_homefeed` collects from the default fashion homefeed without requiring login.
- `login` creates an optional Playwright storage state explicitly.
- `crawl_seed` and `collect_nightly` can run without `--storage-state`; pass one only when you want to reuse an authenticated session.
- `report_weekly` and `list_contactable` run from the SQLite database and do not require `--storage-state`.

For long crawls, pass `run_mode: background`. The skill returns a `job_id` immediately, writes job state under `./.openclaw/red-crawler`, and maintains `HEARTBEAT.md` for OpenClaw heartbeat polling. Use `job_status`, `job_logs`, or `job_stop` with the returned `job_id` for manual follow-up. After OpenClaw reports a pending heartbeat event to the user, call `ack_event` with its `event_id` to avoid duplicate notifications.

The skill does not clone repositories or create login sessions implicitly. Install the `red-crawler` CLI package first, point `workspace_path` at a local working directory, and run `bootstrap` only for reviewed local setup steps.

## Publishing

The package builds as a standard Python wheel and source distribution:

```bash
uv build
```

See [docs/publishing.md](/docs/publishing.md) for the release checklist and PyPI/TestPyPI commands.

## launchd

For macOS local scheduling, use the template at [docs/launchd/red-crawler.collect-nightly.plist](/docs/launchd/red-crawler.collect-nightly.plist).

Replace the placeholder paths:

- `__WORKDIR__`
- `__UV_BIN__`
- `__STORAGE_STATE__`
- `__DB_PATH__`
- `__REPORT_DIR__`
- `__CACHE_DIR__`
- `__LOG_DIR__`

Then load it with:

```bash
launchctl unload ~/Library/LaunchAgents/com.red-crawler.collect-nightly.plist 2>/dev/null || true
cp docs/launchd/red-crawler.collect-nightly.plist ~/Library/LaunchAgents/com.red-crawler.collect-nightly.plist
launchctl load ~/Library/LaunchAgents/com.red-crawler.collect-nightly.plist
```
