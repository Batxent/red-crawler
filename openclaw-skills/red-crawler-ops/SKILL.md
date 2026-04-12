# red-crawler-ops

Use this skill when you need to operate the `red-crawler` CLI from an OpenClaw workflow. It is the portable wrapper for the repo's existing crawler runtime, not a separate crawler implementation.

## When To Use

Use `red-crawler-ops` for:

- installing or cloning a fresh `red-crawler` workspace
- bootstrapping a fresh workspace into a ready-to-run state
- saving a login session into Playwright storage state
- crawling a seed Xiaohongshu profile
- running nightly collection against a workspace database
- exporting a weekly report
- listing contactable creators from the SQLite database

## red-crawler CLI Commands

All crawling tasks must use the native `red-crawler` CLI commands:

### 1. crawl-seed

Crawl a specific Xiaohongshu user profile and extract contact information.

```bash
uv run red-crawler crawl-seed \
  --seed-url "https://www.xiaohongshu.com/user/profile/USER_ID" \
  --storage-state "./state.json" \
  --max-accounts 5 \
  --max-depth 2 \
  --db-path "./data/red_crawler.db" \
  --output-dir "./output"
```

**Parameters:**

- `--seed-url` (required): Target user profile URL
- `--storage-state` (required): Path to Playwright storage state file
- `--max-accounts`: Maximum accounts to crawl (default: 20)
- `--max-depth`: Crawl depth for related accounts (default: 2)
- `--include-note-recommendations`: Include note recommendations
- `--safe-mode`: Enable safe mode
- `--cache-dir`: Cache directory path
- `--cache-ttl-days`: Cache TTL in days (default: 7)
- `--db-path`: SQLite database path (default: ./data/red_crawler.db)
- `--output-dir`: Output directory (default: ./output)

**Outputs:**

- `accounts.csv`: Crawled account information
- `contact_leads.csv`: Extracted contact information (emails, etc.)
- `run_report.json`: Execution report

### 2. login

Interactive login to save browser session.

```bash
uv run red-crawler login --save-state "./state.json"
```

**Parameters:**

- `--save-state` (required): Path to save storage state
- `--login-url`: Login page URL (default: https://www.xiaohongshu.com)

### 3. login-qr-start / login-qr-finish

QR code-based login for headless environments.

```bash
# Start QR login (generates QR code)
uv run red-crawler login-qr-start \
  --save-state "./state.json" \
  --qr-path "./login-qr.png" \
  --session-path "./login-session.json" \
  --timeout 180

# Finish QR login after user scans
uv run red-crawler login-qr-finish \
  --save-state "./state.json" \
  --session-path "./login-session.json"
```

### 4. collect-nightly

Run scheduled nightly data collection.

```bash
uv run red-crawler collect-nightly \
  --storage-state "./state.json" \
  --db-path "./data/red_crawler.db" \
  --report-dir "./reports" \
  --crawl-budget 30 \
  --search-term-limit 4
```

**Parameters:**

- `--storage-state` (required): Path to storage state file
- `--db-path`: Database path (default: ./data/red_crawler.db)
- `--report-dir`: Report directory (default: ./reports)
- `--cache-dir`: Cache directory
- `--cache-ttl-days`: Cache TTL (default: 7)
- `--crawl-budget`: Crawl budget (default: 30)
- `--search-term-limit`: Search term limit (default: 4)
- `--startup-jitter-minutes`: Startup jitter
- `--slot-name`: Slot name for scheduling

### 5. report-weekly

Export weekly reports from database.

```bash
uv run red-crawler report-weekly \
  --db-path "./data/red_crawler.db" \
  --report-dir "./reports" \
  --days 7
```

**Parameters:**

- `--db-path`: Database path (default: ./data/red_crawler.db)
- `--report-dir`: Report directory (default: ./reports)
- `--days`: Report period in days (default: 7)

**Outputs:**

- `weekly-growth-report.json`
- `contactable_creators.csv`

### 6. list-contactable

List contactable creators from database.

```bash
uv run red-crawler list-contactable \
  --db-path "./data/red_crawler.db" \
  --lead-type "email" \
  --creator-segment "creator" \
  --min-relevance-score 0.5 \
  --limit 20 \
  --format csv
```

**Parameters:**

- `--db-path`: Database path (default: ./data/red_crawler.db)
- `--lead-type`: Lead type filter (default: email)
- `--creator-segment`: Creator segment filter (default: creator)
- `--min-relevance-score`: Minimum relevance score (default: 0.0)
- `--limit`: Result limit (default: 20)
- `--format`: Output format - table or csv (default: table)

### 7. open

Open Xiaohongshu in browser with saved session.

```bash
uv run red-crawler open --storage-state "./state.json"
```

## Supported Actions

- `install_or_bootstrap`
- `bootstrap`
- `login`
- `crawl_seed`
- `collect_nightly`
- `report_weekly`
- `list_contactable`

## Example Prompts

- "帮我在当前目录初始化/安装一个小红书爬虫项目" (Automatically maps to `install_or_bootstrap` to setup the workspace)
- "我需要登录爬虫" / "我要登录小红书" (Automatically maps to `login` to fetch/refresh the Playwright session state)
- "开始执行每日夜间数据采集" / "运行自动收集任务" (Automatically maps to `collect_nightly` to continue crawling based on the database queue)
- "帮我生成一份本周的爬虫数据周报" (Automatically maps to `report_weekly` pointing to the workspace's DB)

**Crawling New Data vs Querying Database:**

- "帮我从这个博主去爬10个相关的美妆博主: https://www.xiaohongshu.com/..." (Crawls **NEW** data: Automatically maps to `crawl_seed` with `seed_url`, setting `max_accounts` to 10. _Note: crawling new data requires a seed URL._)
- "帮我从数据库/已爬取的数据中找出10个美妆/游戏/科技博主的联系方式" (Queries **EXISTING** DB: Automatically sets `action` to `list_contactable`, `limit` to 10, and `creator_segment` to "美妆" to filter the local SQLite database)

_(Also understands technical prompt variations:)_

- "Bootstrap this workspace: run setup, install Chromium, and finish when `state.json` has been created."
- "Crawl this seed profile with a depth of 2 and write outputs into `output/`."
- "Export this week's report and return the generated artifacts."

## Environment Setup

### Windows (WSL2)

On Windows, red-crawler runs inside WSL2. You need:

1. **WSL2 with Ubuntu** (20.04 or 22.04 recommended)
2. **WSLg** (built-in graphics support for WSL2) - for browser GUI
3. **Dependencies:**
   ```bash
   sudo apt-get update
   sudo apt-get install -y git python3 python3-pip
   ```
4. **uv** (Python package manager):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

**Known Issues & Fixes:**

1. **playwright-stealth version conflict**
   - Error: `ImportError: cannot import name 'stealth_sync'`
   - Fix: Lock to version `<2.0.0` in `pyproject.toml`:
     ```toml
     dependencies = [
       "playwright-stealth<2.0.0",
       ...
     ]
     ```

2. **setuptools/pkg_resources missing**
   - Error: `ModuleNotFoundError: No module named 'pkg_resources'`
   - Fix: Lock to version `<70` in `pyproject.toml`:
     ```toml
     dependencies = [
       "setuptools<70",
       ...
     ]
     ```

3. **DISPLAY not set (WSLg)**
   - Error: `Missing X server or $DISPLAY`
   - Fix: Export DISPLAY before running:
     ```bash
     export DISPLAY=:0
     ```

4. **Headless vs Headed browser**
   - `login` command requires headed browser (GUI)
   - `crawl-seed` and other commands also require headed browser on WSL
   - Always set `DISPLAY=:0` before running any command with browser

### Linux (Native)

1. **Dependencies:**
   ```bash
   sudo apt-get update
   sudo apt-get install -y git python3 python3-pip
   ```
2. **uv**:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. **X Server** (for headed browser):
   ```bash
   sudo apt-get install -y xvfb
   export DISPLAY=:99
   Xvfb :99 -screen 0 1024x768x16 &
   ```

### macOS

1. **Homebrew:**
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
2. **uv:**
   ```bash
   brew install uv
   ```
3. **Git:**
   ```bash
   brew install git
   ```

## Prerequisites

- `install_or_bootstrap` can clone the repository before setup when a workspace does not exist yet.
- `bootstrap` and every operational action require the workspace to be the `red-crawler` repository root.
- `git` must be available when `install_or_bootstrap` needs to clone the repository.
- `uv` must be available for `bootstrap`, `install_or_bootstrap`, and every CLI action.
- `login` creates the Playwright storage state explicitly.
- `crawl_seed` and `collect_nightly` require an authenticated Playwright storage state file.
- `report_weekly` and `list_contactable` run from the database and do not require storage state.
- The workspace must contain `pyproject.toml`.

## Safety Limits

- Do not overwrite an existing non-`red-crawler` directory during installation.
- Do not point this skill at a directory that lacks `pyproject.toml` unless you intend `install_or_bootstrap` to clone a fresh workspace there.
- Do not create login sessions silently; `bootstrap` or `install_or_bootstrap` still require the user to complete interactive authentication.
- Do not point it at production data or unknown databases.
- Do not assume a browser session exists; create `state.json` with `login` first.
- Do not hard-code machine-specific paths in prompts or config.
- Prefer relative, workspace-scoped paths for outputs and reports.

## Input Shape

Provide an object with `action` plus optional fields used by the selected action. Common fields include:

- `workspace_path`
- `repo_url`
- `workspace_parent`
- `workspace_name`
- `branch`
- `runner_command`
- `storage_state`
- `db_path`
- `report_dir`
- `output_dir`
- `cache_dir`

Action-specific fields include:

- `force_login`
- `sync_dependencies`
- `install_browser`
- `seed_url`
- `login_url`
- `max_accounts`
- `max_depth`
- `include_note_recommendations`
- `safe_mode`
- `cache_ttl_days`
- `crawl_budget`
- `search_term_limit`
- `startup_jitter_minutes`
- `slot_name`
- `days`
- `lead_type`
- `creator_segment`
- `min_relevance_score`
- `limit`
- `format`

## Output Shape

Successful runs return:

- `status`
- `action`
- `command`
- `summary`
- `artifacts`
- `metrics`
- `next_step`
- `stdout`
- `stderr`

Error runs return:

- `status`
- `action`
- `error_type`
- `message`
- `suggested_fix`
- `action`, `command`, `stdout`, and `stderr` for execution-time failures
- Early validation or configuration failures may omit `action`, `command`, `stdout`, and `stderr`
