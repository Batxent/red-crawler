# red-crawler

CLI crawler for collecting Xiaohongshu beauty creator contact leads from profile bios and recommendation chains, with SQLite persistence and nightly automation.

## Usage

Install the published CLI:

```bash
uv tool install red-crawler==0.1.2
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

Save a reusable login session first:

```bash
red-crawler login --save-state "./state.json"
```

It will open a visible browser. Log in to Xiaohongshu there, then come back to the terminal and press Enter to save the session file.

Run a manual crawl with an existing Playwright storage state file:

```bash
red-crawler crawl-seed \
  --seed-url "https://www.xiaohongshu.com/user/profile/USER_ID" \
  --storage-state "./state.json" \
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
  --storage-state "./state.json" \
  --browser-mode bright-data \
  --output-dir "./output"
```

You can also pass the full CDP endpoint directly:

```bash
red-crawler crawl-seed \
  --seed-url "https://www.xiaohongshu.com/user/profile/USER_ID" \
  --storage-state "./state.json" \
  --browser-mode bright-data \
  --browser-endpoint "wss://SBR_ZONE_FULL_USERNAME:SBR_ZONE_PASSWORD@brd.superproxy.io:9222"
```

`crawl-seed` now does both:

- exports `accounts.csv`, `contact_leads.csv`, `run_report.json`
- upserts the same result into SQLite

Run a manual crawl for one explicit search term without a `seed_url`:

```bash
red-crawler crawl-search \
  --search-term "抗痘博主" \
  --storage-state "./state.json" \
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
  --storage-state "./state.json" \
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
  --storage-state "./state.json" \
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
  --storage-state "./state.json" \
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
- `login` creates the Playwright storage state explicitly.
- `crawl_seed` and `collect_nightly` require an authenticated Playwright storage state file.
- `report_weekly` and `list_contactable` run from the SQLite database and do not require `--storage-state`.

The skill does not clone repositories or create login sessions implicitly. Install the `red-crawler` CLI package first, point `workspace_path` at a local working directory, run `bootstrap` only for reviewed local setup steps, then run `login` when you are ready to create `state.json`.

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
