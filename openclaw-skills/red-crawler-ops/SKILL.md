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

## Supported Actions

- `install_or_bootstrap`
- `bootstrap`
- `login`
- `crawl_seed`
- `collect_nightly`
- `report_weekly`
- `list_contactable`

## Example Prompts

- "Install `red-crawler` here if needed, then bootstrap it until `state.json` exists."
- "Bootstrap this workspace: run setup, install Chromium, and finish when `state.json` has been created."
- "Run `login` for this workspace and save the browser session to `state.json`."
- "Crawl this seed profile with a depth of 2 and write outputs into `output/`."
- "Run the nightly collector against the workspace database and report directory."
- "Export this week's report and return the generated artifacts."
- "List contactable creators from the database as CSV."

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
