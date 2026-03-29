# red-crawler-ops

Use this skill when you need to operate the `red-crawler` CLI from an OpenClaw workflow. It is the portable wrapper for the repo's existing crawler runtime, not a separate crawler implementation.

## When To Use

Use `red-crawler-ops` for:

- bootstrapping a fresh workspace into a ready-to-run state
- saving a login session into Playwright storage state
- crawling a seed Xiaohongshu profile
- running nightly collection against a workspace database
- exporting a weekly report
- listing contactable creators from the SQLite database

## Supported Actions

- `bootstrap`
- `login`
- `crawl_seed`
- `collect_nightly`
- `report_weekly`
- `list_contactable`

## Example Prompts

- "Bootstrap this workspace: run setup, install Chromium, and finish when `state.json` has been created."
- "Run `login` for this workspace and save the browser session to `state.json`."
- "Crawl this seed profile with a depth of 2 and write outputs into `output/`."
- "Run the nightly collector against the workspace database and report directory."
- "Export this week's report and return the generated artifacts."
- "List contactable creators from the database as CSV."

## Prerequisites

- The workspace must be the `red-crawler` repository root.
- `uv sync` must be run in the workspace before the first action.
- Chromium must be installed with `uv run playwright install chromium`.
- `login` creates the Playwright storage state explicitly.
- `crawl_seed` and `collect_nightly` require an authenticated Playwright storage state file.
- `report_weekly` and `list_contactable` run from the database and do not require storage state.
- The workspace must contain `pyproject.toml`.

## Safety Limits

- Do not run this skill outside a local `red-crawler` workspace.
- Do not install dependencies; `uv sync` and Playwright setup are required beforehand.
- Do not create login sessions silently; use the explicit `login` action so the user can complete authentication.
- Do not point it at production data or unknown databases.
- Do not assume a browser session exists; create `state.json` with `login` first.
- Do not hard-code machine-specific paths in prompts or config.
- Prefer relative, workspace-scoped paths for outputs and reports.

## Input Shape

Provide an object with `action` plus optional fields used by the selected action. Common fields include:

- `workspace_path`
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
