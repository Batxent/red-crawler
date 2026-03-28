# red-crawler

CLI crawler for collecting Xiaohongshu creator contact leads from profile bios and recommendation chains.

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

Run a crawl with an existing Playwright storage state file:

```bash
uv run red-crawler crawl-seed \
  --seed-url "https://www.xiaohongshu.com/user/profile/USER_ID" \
  --storage-state "./state.json" \
  --max-accounts 20 \
  --max-depth 1 \
  --output-dir "./output"
```

Optional note-page expansion:

```bash
uv run red-crawler crawl-seed \
  --seed-url "https://www.xiaohongshu.com/user/profile/USER_ID" \
  --storage-state "./state.json" \
  --include-note-recommendations
```

Outputs:

- `accounts.csv`
- `contact_leads.csv`
- `run_report.json`
