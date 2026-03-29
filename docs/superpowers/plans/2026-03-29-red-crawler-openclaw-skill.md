# Red Crawler OpenClaw Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a portable OpenClaw skill that orchestrates the existing `red-crawler` CLI for login, seed crawling, nightly collection, weekly reports, and contactable-creator listing.

**Architecture:** Add a self-contained OpenClaw skill package under `openclaw-skills/red-crawler-ops/`, but keep `red-crawler` CLI as the single execution source. The skill runtime only merges config, validates inputs, builds argv, runs subprocesses, and maps results into structured outputs; it does not duplicate crawling logic.

**Tech Stack:** Python 3.9+, stdlib `subprocess`/`pathlib`/`json`, pytest, OpenClaw skill manifest + `SKILL.md`

---

## File Structure

### New Files

- `openclaw-skills/red-crawler-ops/SKILL.md`
  - Trigger guidance, examples, limits, and action descriptions for OpenClaw.
- `openclaw-skills/red-crawler-ops/manifest.yaml`
  - Runtime metadata, input/output schema, and config keys.
- `openclaw-skills/red-crawler-ops/config.example.yaml`
  - Portable defaults for `workspace_path`, `storage_state`, `db_path`, `report_dir`, and related paths.
- `openclaw-skills/red-crawler-ops/src/index.py`
  - Skill entrypoint: config merge, validation, command build, subprocess execution, structured result mapping.
- `openclaw-skills/red-crawler-ops/tests/test_index.py`
  - Unit and lightweight integration tests for the skill runtime.

### Modified Files

- `pyproject.toml`
  - Expand pytest discovery so the new skill test module runs with the repo’s default `pytest` invocation.
- `README.md`
  - Add a short OpenClaw section explaining where the skill lives, how to install it locally, and what environment prerequisites remain outside the skill.

## Task 1: Add Test Harness and First Failing Validation Tests

**Files:**
- Create: `openclaw-skills/red-crawler-ops/tests/test_index.py`
- Modify: `pyproject.toml`
- Test: `openclaw-skills/red-crawler-ops/tests/test_index.py`

- [ ] **Step 1: Update pytest discovery to include the skill tests**

```toml
[tool.pytest.ini_options]
testpaths = ["tests", "openclaw-skills"]
```

- [ ] **Step 2: Write the first failing tests for missing required inputs**

```python
def run_handler(input_data, context):
    return asyncio.run(handler(input_data, context))


def test_crawl_seed_requires_seed_url():
    result = run_handler({"action": "crawl_seed"}, {"config": {}})
    assert result["status"] == "error"
    assert result["error_type"] == "validation_error"
    assert "seed_url" in result["message"]


def test_collect_nightly_requires_storage_state():
    result = run_handler(
        {"action": "collect_nightly", "workspace_path": "/tmp/project"},
        {"config": {}},
    )
    assert result["status"] == "error"
    assert result["error_type"] == "configuration_error"
    assert "storage_state" in result["suggested_fix"]
```

- [ ] **Step 3: Run the focused test file to verify it fails**

Run: `uv run pytest openclaw-skills/red-crawler-ops/tests/test_index.py -q`

Expected: FAIL with import error or missing `handler`

- [ ] **Step 4: Create a minimal entry module skeleton just enough for import**

```python
async def handler(input, context):
    return {"status": "error", "error_type": "not_implemented"}
```

- [ ] **Step 5: Run the focused test file again**

Run: `uv run pytest openclaw-skills/red-crawler-ops/tests/test_index.py -q`

Expected: FAIL on assertion mismatch instead of import failure

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml openclaw-skills/red-crawler-ops/src/index.py openclaw-skills/red-crawler-ops/tests/test_index.py
git commit -m "test: add OpenClaw skill harness and validation tests"
```

## Task 2: Implement Config Merge and Validation Helpers

**Files:**
- Modify: `openclaw-skills/red-crawler-ops/src/index.py`
- Modify: `openclaw-skills/red-crawler-ops/tests/test_index.py`
- Test: `openclaw-skills/red-crawler-ops/tests/test_index.py`

- [ ] **Step 1: Extend tests to cover config fallback and path checks**

```python
def test_workspace_path_can_come_from_context_config(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    result = run_handler(
        {"action": "login", "storage_state": str(tmp_path / "state.json")},
        {"config": {"workspace_path": str(tmp_path)}},
    )
    assert result["error_type"] != "configuration_error"


def test_workspace_path_must_contain_pyproject(tmp_path):
    result = run_handler(
        {
            "action": "login",
            "workspace_path": str(tmp_path),
            "storage_state": str(tmp_path / "state.json"),
        },
        {"config": {}},
    )
    assert result["status"] == "error"
    assert result["error_type"] == "configuration_error"
    assert "pyproject.toml" in result["message"]
```

- [ ] **Step 2: Run the focused tests to capture the failing cases**

Run: `uv run pytest openclaw-skills/red-crawler-ops/tests/test_index.py -q`

Expected: FAIL on missing config merge / validation helpers

- [ ] **Step 3: Implement minimal helpers**

```python
def merge_config(input_data, context):
    config = extract_config(context)
    return {**config, **{k: v for k, v in input_data.items() if v is not None}}


def validate_request(resolved):
    ...
```

Implementation details:
- Normalize `action`
- Read config from a single helper so runtime-shape assumptions stay isolated
- Require `workspace_path` for all actions
- Require `storage_state` for all actions except `login`
- Require `seed_url` for `crawl_seed`
- Verify `workspace_path / "pyproject.toml"` exists before executing subprocesses

- [ ] **Step 4: Run the focused tests and make them pass**

Run: `uv run pytest openclaw-skills/red-crawler-ops/tests/test_index.py -q`

Expected: PASS for validation-related tests

- [ ] **Step 5: Commit**

```bash
git add openclaw-skills/red-crawler-ops/src/index.py openclaw-skills/red-crawler-ops/tests/test_index.py
git commit -m "feat: add OpenClaw skill config merge and validation"
```

## Task 3: Add Action-Specific Command Builders

**Files:**
- Modify: `openclaw-skills/red-crawler-ops/src/index.py`
- Modify: `openclaw-skills/red-crawler-ops/tests/test_index.py`
- Test: `openclaw-skills/red-crawler-ops/tests/test_index.py`

- [ ] **Step 1: Write failing tests for argv generation**

```python
def test_build_crawl_seed_command_uses_overrides(tmp_path):
    command = build_command(
        {
            "action": "crawl_seed",
            "workspace_path": str(tmp_path),
            "storage_state": "state.json",
            "seed_url": "https://www.xiaohongshu.com/user/profile/user-001",
            "output_dir": "output",
            "db_path": "data/red_crawler.db",
            "max_accounts": 15,
            "max_depth": 3,
            "include_note_recommendations": True,
        }
    )
    assert command == [
        "uv",
        "run",
        "red-crawler",
        "crawl-seed",
        "--seed-url",
        "https://www.xiaohongshu.com/user/profile/user-001",
        "--storage-state",
        "state.json",
        "--max-accounts",
        "15",
        "--max-depth",
        "3",
        "--include-note-recommendations",
        "--db-path",
        "data/red_crawler.db",
        "--output-dir",
        "output",
    ]
```

- [ ] **Step 2: Add similar tests for the remaining actions**

Cover:
- `login`
- `collect_nightly`
- `report_weekly`
- `list_contactable`

- [ ] **Step 3: Run the focused tests to verify the builders fail**

Run: `uv run pytest openclaw-skills/red-crawler-ops/tests/test_index.py -q`

Expected: FAIL on missing builder functions or mismatched argv

- [ ] **Step 4: Implement pure command-builder helpers**

```python
def build_login_command(resolved): ...
def build_crawl_seed_command(resolved): ...
def build_collect_nightly_command(resolved): ...
def build_report_weekly_command(resolved): ...
def build_list_contactable_command(resolved): ...
```

Implementation details:
- Build argv as lists, never shell strings
- Keep `runner_command` configurable, but default to `["uv", "run", "red-crawler"]`
- Only emit optional flags when values are explicitly present
- Default `list-contactable` to `--format csv` so the skill can summarize predictable output

- [ ] **Step 5: Run the focused tests and make them pass**

Run: `uv run pytest openclaw-skills/red-crawler-ops/tests/test_index.py -q`

Expected: PASS for all builder tests

- [ ] **Step 6: Commit**

```bash
git add openclaw-skills/red-crawler-ops/src/index.py openclaw-skills/red-crawler-ops/tests/test_index.py
git commit -m "feat: add OpenClaw skill command builders"
```

## Task 4: Execute Commands and Map Structured Results

**Files:**
- Modify: `openclaw-skills/red-crawler-ops/src/index.py`
- Modify: `openclaw-skills/red-crawler-ops/tests/test_index.py`
- Test: `openclaw-skills/red-crawler-ops/tests/test_index.py`

- [ ] **Step 1: Write failing tests for subprocess success and failure mapping**

```python
def test_handler_returns_structured_success_for_report_weekly(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_completed_process(stdout=""))
    result = run_handler(
        {
            "action": "report_weekly",
            "workspace_path": str(tmp_path),
            "db_path": str(tmp_path / "data.db"),
            "report_dir": str(tmp_path / "reports"),
            "days": 7,
        },
        {"config": {}},
    )
    assert result["status"] == "success"
    assert result["action"] == "report_weekly"
    assert "weekly" in result["summary"]


def test_handler_returns_execution_error_when_cli_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_failed_process(stderr="boom"))
    result = run_handler(
        {
            "action": "login",
            "workspace_path": str(tmp_path),
            "storage_state": str(tmp_path / "state.json"),
        },
        {"config": {}},
    )
    assert result["status"] == "error"
    assert result["error_type"] == "execution_error"
    assert "boom" in result["message"]
```

- [ ] **Step 2: Write one failing artifact test for `crawl_seed`**

```python
def test_crawl_seed_reports_expected_artifacts(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    for name in ("accounts.csv", "contact_leads.csv", "run_report.json"):
        (output_dir / name).parent.mkdir(parents=True, exist_ok=True)
        (output_dir / name).write_text("", encoding="utf-8")
    ...
    assert result["artifacts"] == [
        str(output_dir / "accounts.csv"),
        str(output_dir / "contact_leads.csv"),
        str(output_dir / "run_report.json"),
    ]
```

- [ ] **Step 3: Run the focused tests to verify the execution layer fails**

Run: `uv run pytest openclaw-skills/red-crawler-ops/tests/test_index.py -q`

Expected: FAIL on missing subprocess orchestration and result mapping

- [ ] **Step 4: Implement subprocess execution and output mapping**

```python
def run_command(argv, cwd):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


async def handler(input_data, context):
    resolved = merge_config(input_data, context)
    error = validate_request(resolved)
    if error:
        return error
    argv = build_command(resolved)
    completed = run_command(argv, cwd=resolved["workspace_path"])
    return build_result(resolved, argv, completed)
```

Implementation details:
- Return `command` as a single display string for auditability
- Return `suggested_fix` on all error paths
- Recognize expected artifacts per action:
  - `crawl_seed`: `accounts.csv`, `contact_leads.csv`, `run_report.json`
  - `collect_nightly`: `daily-run-report.json`, `weekly-growth-report.json`, `contactable_creators.csv`
  - `report_weekly`: `weekly-growth-report.json`, `contactable_creators.csv`
- Treat non-zero exit as `execution_error`
- Treat zero exit with missing required artifacts as `artifact_error`

- [ ] **Step 5: Run the focused tests and make them pass**

Run: `uv run pytest openclaw-skills/red-crawler-ops/tests/test_index.py -q`

Expected: PASS for success, failure, and artifact tests

- [ ] **Step 6: Run the full repo test suite**

Run: `uv run pytest`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add openclaw-skills/red-crawler-ops/src/index.py openclaw-skills/red-crawler-ops/tests/test_index.py
git commit -m "feat: add OpenClaw skill execution and result mapping"
```

## Task 5: Author Skill Metadata and Installation Docs

**Files:**
- Create: `openclaw-skills/red-crawler-ops/SKILL.md`
- Create: `openclaw-skills/red-crawler-ops/manifest.yaml`
- Create: `openclaw-skills/red-crawler-ops/config.example.yaml`
- Modify: `README.md`
- Test: `openclaw-skills/red-crawler-ops/tests/test_index.py`

- [ ] **Step 1: Write a small failing smoke test that reads the metadata files**

```python
def test_manifest_and_skill_files_exist():
    skill_root = Path("openclaw-skills/red-crawler-ops")
    assert (skill_root / "manifest.yaml").exists()
    assert (skill_root / "SKILL.md").exists()
    assert (skill_root / "config.example.yaml").exists()
```

- [ ] **Step 2: Run the focused test file to confirm the metadata files are missing**

Run: `uv run pytest openclaw-skills/red-crawler-ops/tests/test_index.py -q`

Expected: FAIL on missing files

- [ ] **Step 3: Author `manifest.yaml`**

Include:
- `name: red-crawler-ops`
- semantic `version`
- `runtime: python`
- `entry: src/index.py`
- `description`
- `config` entries for path defaults and `runner_command`
- input schema with `action` enum and shared optional properties
- output schema with `status`, `summary`, `artifacts`, `metrics`, `next_step`, and error fields

- [ ] **Step 4: Author `config.example.yaml`**

Include portable placeholders only:

```yaml
workspace_path: /absolute/path/to/red-crawler
runner_command:
  - uv
  - run
  - red-crawler
storage_state: /absolute/path/to/state.json
db_path: /absolute/path/to/data/red_crawler.db
report_dir: /absolute/path/to/reports
output_dir: /absolute/path/to/output
cache_dir: /absolute/path/to/.cache/red-crawler
default_crawl_budget: 30
default_report_days: 7
default_list_limit: 20
```

- [ ] **Step 5: Author `SKILL.md`**

Document:
- when to use the skill
- the 5 supported actions
- example prompts
- prerequisites the user must satisfy outside the skill
- safety limits: the skill does not install dependencies or create login sessions silently

- [ ] **Step 6: Update `README.md` with a short OpenClaw section**

Add:
- where the skill lives in the repo
- how to install it with a local path
- reminder that users still need `uv sync` and `playwright install chromium`
- reminder to create `state.json` before non-login actions

- [ ] **Step 7: Run focused tests, then full suite**

Run: `uv run pytest openclaw-skills/red-crawler-ops/tests/test_index.py -q`

Expected: PASS

Run: `uv run pytest`

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add README.md pyproject.toml openclaw-skills/red-crawler-ops docs/superpowers/plans/2026-03-29-red-crawler-openclaw-skill.md
git commit -m "feat: add portable OpenClaw skill for red-crawler"
```

## Final Verification

- [ ] **Step 1: Run one local dry invocation against the handler with mocked subprocesses**

Run:

```bash
uv run pytest openclaw-skills/red-crawler-ops/tests/test_index.py -q
```

Expected: PASS with coverage of config merge, validation, command generation, and result mapping

- [ ] **Step 2: Run the full repo suite one last time**

Run: `uv run pytest`

Expected: PASS

- [ ] **Step 3: Record final manual verification notes**

Check:
- `manifest.yaml` points to `src/index.py`
- `config.example.yaml` contains no author-specific paths
- `README.md` installation instructions refer to the skill’s repo-local path
- `SKILL.md` examples align with the supported `action` enum
