# red-crawler

CLI crawler for collecting Xiaohongshu beauty creator contact leads from profile bios and recommendation chains, with SQLite persistence and nightly automation.

## Usage

Install dependencies and Playwright browser runtime:

```bash
uv sync
uv run playwright install chromium
```

Save a reusable login session first:

```bash
uv run red-crawler login --save-state "./state.json"
```

It will open a visible browser. Log in to Xiaohongshu there, then come back to the terminal and press Enter to save the session file.

Run a manual crawl with an existing Playwright storage state file:

```bash
uv run red-crawler crawl-seed \
  --seed-url "https://www.xiaohongshu.com/user/profile/USER_ID" \
  --storage-state "./state.json" \
  --max-accounts 20 \
  --max-depth 2 \
  --db-path "./data/red_crawler.db" \
  --output-dir "./output"
```

`crawl-seed` now does both:

- exports `accounts.csv`, `contact_leads.csv`, `run_report.json`
- upserts the same result into SQLite

Optional note-page expansion:

```bash
uv run red-crawler crawl-seed \
  --seed-url "https://www.xiaohongshu.com/user/profile/USER_ID" \
  --storage-state "./state.json" \
  --include-note-recommendations
```

List high-quality contactable creators from the SQLite database:

```bash
uv run red-crawler list-contactable \
  --db-path "./data/red_crawler.db" \
  --min-relevance-score 0.7 \
  --limit 20
```

Run nightly auto-collection with queue, search bootstrap, seed promotion, and daily report output:

```bash
uv run red-crawler collect-nightly \
  --storage-state "./state.json" \
  --db-path "./data/red_crawler.db" \
  --report-dir "./reports" \
  --cache-dir "./.cache/red-crawler" \
  --crawl-budget 30
```

Export weekly growth report and a contactable creator CSV:

```bash
uv run red-crawler report-weekly \
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

- `install_or_bootstrap` can clone the repository into a target directory, run `uv sync`, install Chromium, and keep going until `state.json` exists.
- `bootstrap` can initialize the workspace, install Chromium, and keep going until `state.json` exists.
- `login` creates the Playwright storage state explicitly.
- `crawl_seed` and `collect_nightly` require an authenticated Playwright storage state file.
- `report_weekly` and `list_contactable` run from the SQLite database and do not require `--storage-state`.

`install_or_bootstrap` is the lowest-dependency entrypoint. A new user only needs `git`, `uv`, and a machine that can run Playwright Chromium; the skill can handle cloning the repo, syncing Python dependencies, installing Chromium, and starting the interactive login flow.

## launchd

For macOS local scheduling, use the template at [docs/launchd/red-crawler.collect-nightly.plist](/Users/tommy/Documents/GitHubOpenSources/red-crawler/docs/launchd/red-crawler.collect-nightly.plist).

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
