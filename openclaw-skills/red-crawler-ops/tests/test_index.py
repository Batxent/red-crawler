from __future__ import annotations

import asyncio
import importlib.util
import subprocess
from pathlib import Path

INDEX_PATH = Path(__file__).resolve().parents[1] / "src" / "index.py"
INDEX_SPEC = importlib.util.spec_from_file_location("red_crawler_ops_index", INDEX_PATH)
assert INDEX_SPEC is not None
assert INDEX_SPEC.loader is not None
INDEX_MODULE = importlib.util.module_from_spec(INDEX_SPEC)
INDEX_SPEC.loader.exec_module(INDEX_MODULE)
handler = INDEX_MODULE.handler
build_command = INDEX_MODULE.build_command
SKILL_DIR = Path(__file__).resolve().parents[1]
MANIFEST_TEXT = (SKILL_DIR / "manifest.yaml").read_text(encoding="utf-8")
SKILL_TEXT = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
CONFIG_EXAMPLE_TEXT = (SKILL_DIR / "config.example.yaml").read_text(
    encoding="utf-8"
)
README_TEXT = (SKILL_DIR.parents[1] / "README.md").read_text(encoding="utf-8")
RED_CRAWLER_PYPROJECT = '[project]\nname = "red-crawler"\n'
OTHER_PYPROJECT = '[project]\nname = "other-project"\n'


def run_handler(input_data, context):
    return asyncio.run(handler(input_data, context))


def test_skill_metadata_contract_matches_runtime():
    output_schema = MANIFEST_TEXT.split("output_schema:", 1)[1]
    assert "runtime: python" in MANIFEST_TEXT
    assert "entry: src/index.py" in MANIFEST_TEXT
    assert "- bootstrap" in MANIFEST_TEXT
    assert "- install_or_bootstrap" in MANIFEST_TEXT
    assert "default_crawl_budget:" in MANIFEST_TEXT
    assert "default_report_days:" in MANIFEST_TEXT
    assert "default_list_limit:" in MANIFEST_TEXT
    assert "command:" in output_schema
    assert "summary:" in output_schema
    assert "artifacts:" in output_schema
    assert "stdout:" in output_schema
    assert "stderr:" in output_schema
    assert "error_type:" in output_schema
    assert "message:" in output_schema
    assert "suggested_fix:" in output_schema
    assert "metrics:" in output_schema
    assert "next_step:" in output_schema
    assert "error:" in output_schema
    assert "stdout:" in output_schema
    assert "stderr:" in output_schema
    assert "command:" in output_schema
    assert "runner_command:" in CONFIG_EXAMPLE_TEXT
    assert "workspace_path: ." in CONFIG_EXAMPLE_TEXT
    assert "repo_url: https://github.com/Batxent/red-crawler.git" in CONFIG_EXAMPLE_TEXT
    assert "workspace_parent: ." in CONFIG_EXAMPLE_TEXT
    assert "workspace_name: red-crawler" in CONFIG_EXAMPLE_TEXT
    assert "storage_state: ./state.json" in CONFIG_EXAMPLE_TEXT
    assert "db_path: ./data/red_crawler.db" in CONFIG_EXAMPLE_TEXT
    assert "report_dir: ./reports" in CONFIG_EXAMPLE_TEXT
    assert "output_dir: ./output" in CONFIG_EXAMPLE_TEXT
    assert "cache_dir: ./.cache/red-crawler" in CONFIG_EXAMPLE_TEXT
    assert "- uv" in CONFIG_EXAMPLE_TEXT
    assert "- run" in CONFIG_EXAMPLE_TEXT
    assert "- red-crawler" in CONFIG_EXAMPLE_TEXT
    assert "default_crawl_budget: 30" in CONFIG_EXAMPLE_TEXT
    assert "default_report_days: 7" in CONFIG_EXAMPLE_TEXT
    assert "default_list_limit: 20" in CONFIG_EXAMPLE_TEXT


def test_skill_docs_match_storage_state_behavior():
    assert "bootstrap" in SKILL_TEXT
    assert "install_or_bootstrap" in SKILL_TEXT
    assert "login` creates the Playwright storage state explicitly" in SKILL_TEXT
    assert "crawl_seed" in SKILL_TEXT
    assert "collect_nightly" in SKILL_TEXT
    assert "report_weekly" in SKILL_TEXT
    assert "list_contactable" in SKILL_TEXT
    assert "execution-time failures" in SKILL_TEXT
    assert (
        "Early validation or configuration failures may omit `action`, `command`, "
        "`stdout`, and `stderr`"
    ) in SKILL_TEXT
    assert "Save a reusable login session first" in README_TEXT
    assert "Run a manual crawl with an existing Playwright storage state file" in README_TEXT
    assert "List high-quality contactable creators from the SQLite database" in README_TEXT
    assert "Use the OpenClaw skill actions in this order" in README_TEXT
    assert "install_or_bootstrap" in README_TEXT
    assert "bootstrap" in README_TEXT
    assert "login` creates the Playwright storage state explicitly" in README_TEXT
    assert "crawl_seed` and `collect_nightly` require an authenticated Playwright storage state file" in README_TEXT
    assert "report_weekly` and `list_contactable` run from the SQLite database and do not require `--storage-state`" in README_TEXT


def test_install_or_bootstrap_clones_missing_repo_then_bootstraps(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "red-crawler"
    commands = []

    def fake_run(argv, cwd, capture_output, text):
        commands.append((argv, Path(cwd)))
        if argv[:2] == ["git", "clone"]:
            workspace.mkdir()
            (workspace / "pyproject.toml").write_text(
                RED_CRAWLER_PYPROJECT, encoding="utf-8"
            )
        if argv == ["uv", "run", "red-crawler", "login", "--save-state", "./state.json"]:
            (workspace / "state.json").write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(INDEX_MODULE.subprocess, "run", fake_run)

    result = run_handler(
        {
            "action": "install_or_bootstrap",
            "workspace_parent": str(tmp_path),
            "workspace_name": "red-crawler",
            "storage_state": "./state.json",
            "repo_url": "https://github.com/Batxent/red-crawler.git",
        },
        {"config": {}},
    )

    assert result["status"] == "success"
    assert result["action"] == "install_or_bootstrap"
    assert result["artifacts"] == {
        "workspace_path": str(workspace),
        "state.json": str(workspace / "state.json"),
    }
    assert result["metrics"] == {
        "repo_cloned": True,
        "uv_sync_ran": True,
        "playwright_install_ran": True,
        "login_ran": True,
        "state_file_created": True,
    }
    assert commands == [
        (
            [
                "git",
                "clone",
                "https://github.com/Batxent/red-crawler.git",
                str(workspace),
            ],
            tmp_path,
        ),
        (["uv", "sync"], workspace),
        (["uv", "run", "playwright", "install", "chromium"], workspace),
        (
            ["uv", "run", "red-crawler", "login", "--save-state", "./state.json"],
            workspace,
        ),
    ]


def test_install_or_bootstrap_reuses_existing_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "red-crawler"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text(
        RED_CRAWLER_PYPROJECT, encoding="utf-8"
    )
    (workspace / "state.json").write_text("{}", encoding="utf-8")
    commands = []

    def fake_run(argv, cwd, capture_output, text):
        commands.append((argv, Path(cwd)))
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(INDEX_MODULE.subprocess, "run", fake_run)

    result = run_handler(
        {
            "action": "install_or_bootstrap",
            "workspace_parent": str(tmp_path),
            "workspace_name": "red-crawler",
            "storage_state": "./state.json",
            "repo_url": "https://github.com/Batxent/red-crawler.git",
        },
        {"config": {}},
    )

    assert result["status"] == "success"
    assert result["metrics"] == {
        "repo_cloned": False,
        "uv_sync_ran": True,
        "playwright_install_ran": True,
        "login_ran": False,
        "state_file_created": True,
    }
    assert commands == [
        (["uv", "sync"], workspace),
        (["uv", "run", "playwright", "install", "chromium"], workspace),
    ]


def test_install_or_bootstrap_rejects_existing_non_workspace_directory(tmp_path):
    workspace = tmp_path / "red-crawler"
    workspace.mkdir()

    result = run_handler(
        {
            "action": "install_or_bootstrap",
            "workspace_parent": str(tmp_path),
            "workspace_name": "red-crawler",
            "storage_state": "./state.json",
            "repo_url": "https://github.com/Batxent/red-crawler.git",
        },
        {"config": {}},
    )

    assert result["status"] == "error"
    assert result["error_type"] == "configuration_error"
    assert "pyproject.toml" in result["message"]


def test_install_or_bootstrap_uses_default_relative_target_for_fresh_install(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "red-crawler"
    commands = []
    monkeypatch.chdir(tmp_path)

    def fake_run(argv, cwd, capture_output, text):
        commands.append((argv, Path(cwd)))
        if argv[:2] == ["git", "clone"]:
            workspace.mkdir()
            (workspace / "pyproject.toml").write_text(
                RED_CRAWLER_PYPROJECT, encoding="utf-8"
            )
        if argv == ["uv", "run", "red-crawler", "login", "--save-state", "./state.json"]:
            (workspace / "state.json").write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(INDEX_MODULE.subprocess, "run", fake_run)

    result = run_handler(
        {"action": "install_or_bootstrap"},
        {
            "config": {
                "workspace_path": ".",
                "workspace_parent": ".",
                "workspace_name": "red-crawler",
                "storage_state": "./state.json",
                "repo_url": "https://github.com/Batxent/red-crawler.git",
            }
        },
    )

    assert result["status"] == "success"
    assert result["artifacts"]["workspace_path"] == str(workspace)
    assert commands[0] == (
        [
            "git",
            "clone",
            "https://github.com/Batxent/red-crawler.git",
            str(workspace),
        ],
        tmp_path,
    )


def test_install_or_bootstrap_rejects_other_python_workspace(tmp_path):
    workspace = tmp_path / "red-crawler"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text(OTHER_PYPROJECT, encoding="utf-8")

    result = run_handler(
        {
            "action": "install_or_bootstrap",
            "workspace_parent": str(tmp_path),
            "workspace_name": "red-crawler",
            "storage_state": "./state.json",
            "repo_url": "https://github.com/Batxent/red-crawler.git",
        },
        {"config": {}},
    )

    assert result["status"] == "error"
    assert result["error_type"] == "configuration_error"
    assert "red-crawler" in result["message"]


def test_bootstrap_runs_sync_install_and_login_until_state_exists(
    tmp_path, monkeypatch
):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    state_path = tmp_path / "state.json"
    commands = []

    def fake_run(argv, cwd, capture_output, text):
        commands.append(argv)
        if argv == ["uv", "run", "red-crawler", "login", "--save-state", str(state_path)]:
            state_path.write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(INDEX_MODULE.subprocess, "run", fake_run)

    result = run_handler(
        {
            "action": "bootstrap",
            "workspace_path": str(tmp_path),
            "storage_state": str(state_path),
        },
        {"config": {}},
    )

    assert result["status"] == "success"
    assert result["action"] == "bootstrap"
    assert result["artifacts"] == {"state.json": str(state_path)}
    assert result["metrics"] == {
        "uv_sync_ran": True,
        "playwright_install_ran": True,
        "login_ran": True,
        "state_file_created": True,
    }
    assert result["next_step"] == "You can now run crawl_seed or collect_nightly."
    assert commands == [
        ["uv", "sync"],
        ["uv", "run", "playwright", "install", "chromium"],
        ["uv", "run", "red-crawler", "login", "--save-state", str(state_path)],
    ]


def test_bootstrap_skips_login_when_state_already_exists(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    commands = []

    def fake_run(argv, cwd, capture_output, text):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(INDEX_MODULE.subprocess, "run", fake_run)

    result = run_handler(
        {
            "action": "bootstrap",
            "workspace_path": str(tmp_path),
            "storage_state": str(state_path),
        },
        {"config": {}},
    )

    assert result["status"] == "success"
    assert result["metrics"] == {
        "uv_sync_ran": True,
        "playwright_install_ran": True,
        "login_ran": False,
        "state_file_created": True,
    }
    assert commands == [
        ["uv", "sync"],
        ["uv", "run", "playwright", "install", "chromium"],
    ]


def test_bootstrap_force_login_even_if_state_exists(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    commands = []

    def fake_run(argv, cwd, capture_output, text):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(INDEX_MODULE.subprocess, "run", fake_run)

    result = run_handler(
        {
            "action": "bootstrap",
            "workspace_path": str(tmp_path),
            "storage_state": str(state_path),
            "force_login": True,
        },
        {"config": {}},
    )

    assert result["status"] == "success"
    assert result["metrics"]["login_ran"] is True
    assert commands[-1] == [
        "uv",
        "run",
        "red-crawler",
        "login",
        "--save-state",
        str(state_path),
    ]


def test_bootstrap_returns_artifact_error_when_login_does_not_create_state(
    tmp_path, monkeypatch
):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    state_path = tmp_path / "state.json"

    monkeypatch.setattr(
        INDEX_MODULE.subprocess,
        "run",
        lambda argv, cwd, capture_output, text: subprocess.CompletedProcess(
            argv, 0, stdout="ok", stderr=""
        ),
    )

    result = run_handler(
        {
            "action": "bootstrap",
            "workspace_path": str(tmp_path),
            "storage_state": str(state_path),
        },
        {"config": {}},
    )

    assert result["status"] == "error"
    assert result["error_type"] == "artifact_error"
    assert "state.json" in result["message"]


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


def test_crawl_seed_requires_storage_state(tmp_path):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    result = run_handler(
        {
            "action": "crawl_seed",
            "workspace_path": str(tmp_path),
            "seed_url": "https://www.xiaohongshu.com/user/profile/user-001",
        },
        {"config": {}},
    )
    assert result["status"] == "error"
    assert result["error_type"] == "configuration_error"
    assert "storage_state" in result["suggested_fix"]


def test_login_requires_storage_state(tmp_path):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    result = run_handler(
        {"action": "login", "workspace_path": str(tmp_path)},
        {"config": {}},
    )
    assert result["status"] == "error"
    assert result["error_type"] == "configuration_error"
    assert "storage_state" in result["message"]


def test_report_weekly_does_not_require_storage_state(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "weekly-growth-report.json").write_text("{}", encoding="utf-8")
    (report_dir / "contactable_creators.csv").write_text("id\n1\n", encoding="utf-8")
    monkeypatch.setattr(
        INDEX_MODULE.subprocess,
        "run",
        lambda argv, cwd, capture_output, text: subprocess.CompletedProcess(
            argv, 0, stdout="", stderr=""
        ),
    )
    result = run_handler(
        {
            "action": "report_weekly",
            "workspace_path": str(tmp_path),
            "db_path": str(tmp_path / "data.db"),
            "report_dir": str(report_dir),
        },
        {"config": {}},
    )
    assert result["status"] == "success"
    assert result["action"] == "report_weekly"


def test_collect_nightly_uses_default_crawl_budget_from_context_config(
    tmp_path, monkeypatch
):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "daily-run-report.json").write_text("{}", encoding="utf-8")
    (report_dir / "weekly-growth-report.json").write_text("{}", encoding="utf-8")
    (report_dir / "contactable_creators.csv").write_text("id\n1\n", encoding="utf-8")

    def fake_run(argv, cwd, capture_output, text):
        assert argv == [
            "uv",
            "run",
            "red-crawler",
            "collect-nightly",
            "--storage-state",
            str(tmp_path / "state.json"),
            "--db-path",
            str(tmp_path / "data.db"),
            "--report-dir",
            str(report_dir),
            "--crawl-budget",
            "30",
        ]
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(INDEX_MODULE.subprocess, "run", fake_run)

    result = run_handler(
        {
            "action": "collect_nightly",
            "workspace_path": str(tmp_path),
            "storage_state": str(tmp_path / "state.json"),
            "db_path": str(tmp_path / "data.db"),
            "report_dir": str(report_dir),
        },
        {"config": {"default_crawl_budget": 30}},
    )

    assert result["status"] == "success"
    assert result["action"] == "collect_nightly"


def test_report_weekly_uses_default_report_days_from_context_config(
    tmp_path, monkeypatch
):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "weekly-growth-report.json").write_text("{}", encoding="utf-8")
    (report_dir / "contactable_creators.csv").write_text("id\n1\n", encoding="utf-8")

    def fake_run(argv, cwd, capture_output, text):
        assert argv == [
            "uv",
            "run",
            "red-crawler",
            "report-weekly",
            "--db-path",
            str(tmp_path / "data.db"),
            "--report-dir",
            str(report_dir),
            "--days",
            "7",
        ]
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(INDEX_MODULE.subprocess, "run", fake_run)

    result = run_handler(
        {
            "action": "report_weekly",
            "workspace_path": str(tmp_path),
            "db_path": str(tmp_path / "data.db"),
            "report_dir": str(report_dir),
        },
        {"config": {"default_report_days": 7}},
    )

    assert result["status"] == "success"
    assert result["action"] == "report_weekly"


def test_list_contactable_uses_default_list_limit_from_context_config(
    tmp_path, monkeypatch
):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")

    def fake_run(argv, cwd, capture_output, text):
        assert argv == [
            "uv",
            "run",
            "red-crawler",
            "list-contactable",
            "--db-path",
            str(tmp_path / "data.db"),
            "--limit",
            "20",
            "--format",
            "csv",
        ]
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(INDEX_MODULE.subprocess, "run", fake_run)

    result = run_handler(
        {
            "action": "list_contactable",
            "workspace_path": str(tmp_path),
            "db_path": str(tmp_path / "data.db"),
        },
        {"config": {"default_list_limit": 20}},
    )

    assert result["status"] == "success"
    assert result["action"] == "list_contactable"


def test_list_contactable_does_not_require_storage_state(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    monkeypatch.setattr(
        INDEX_MODULE.subprocess,
        "run",
        lambda argv, cwd, capture_output, text: subprocess.CompletedProcess(
            argv, 0, stdout="", stderr=""
        ),
    )
    result = run_handler(
        {
            "action": "list_contactable",
            "workspace_path": str(tmp_path),
            "db_path": str(tmp_path / "data.db"),
        },
        {"config": {}},
    )
    assert result["status"] == "success"
    assert result["action"] == "list_contactable"


def test_workspace_path_can_come_from_context_config(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    monkeypatch.setattr(
        INDEX_MODULE.subprocess,
        "run",
        lambda argv, cwd, capture_output, text: subprocess.CompletedProcess(
            argv, 0, stdout="", stderr=""
        ),
    )
    result = run_handler(
        {"action": "LOGIN", "storage_state": str(tmp_path / "state.json")},
        {"config": {"workspace_path": str(tmp_path)}},
    )
    assert result["status"] == "success"
    assert result["action"] == "login"
    assert result["command"] == f"uv run red-crawler login --save-state {tmp_path / 'state.json'}"


def test_handler_rejects_non_mapping_input(tmp_path):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    result = run_handler(
        "bad-input",
        {"config": {"workspace_path": str(tmp_path)}},
    )
    assert result["status"] == "error"
    assert result["error_type"] == "validation_error"
    assert "mapping" in result["message"]


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


def test_workspace_path_rejects_non_path_like_value():
    result = run_handler(
        {"action": "login", "workspace_path": 123, "storage_state": "/tmp/state.json"},
        {"config": {}},
    )
    assert result["status"] == "error"
    assert result["error_type"] == "configuration_error"
    assert "path-like" in result["message"]


def test_build_login_command_uses_overrides(tmp_path):
    command = build_command(
        {
            "action": "login",
            "workspace_path": str(tmp_path),
            "storage_state": "state.json",
            "login_url": "https://www.xiaohongshu.com/explore",
        }
    )
    assert command == [
        "uv",
        "run",
        "red-crawler",
        "login",
        "--save-state",
        "state.json",
        "--login-url",
        "https://www.xiaohongshu.com/explore",
    ]


def test_build_command_splits_string_runner_command(tmp_path):
    command = build_command(
        {
            "action": "login",
            "workspace_path": str(tmp_path),
            "storage_state": "state.json",
            "runner_command": "uv run red-crawler",
        }
    )
    assert command[:3] == ["uv", "run", "red-crawler"]
    assert command[3:] == ["login", "--save-state", "state.json"]


def test_build_command_preserves_list_runner_command(tmp_path):
    command = build_command(
        {
            "action": "report_weekly",
            "workspace_path": str(tmp_path),
            "runner_command": ["python", "-m", "red_crawler.cli"],
            "db_path": "data/red_crawler.db",
            "report_dir": "reports",
            "days": 7,
        }
    )
    assert command == [
        "python",
        "-m",
        "red_crawler.cli",
        "report-weekly",
        "--db-path",
        "data/red_crawler.db",
        "--report-dir",
        "reports",
        "--days",
        "7",
    ]


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


def test_build_collect_nightly_command_uses_overrides(tmp_path):
    command = build_command(
        {
            "action": "collect_nightly",
            "workspace_path": str(tmp_path),
            "storage_state": "state.json",
            "db_path": "data/red_crawler.db",
            "report_dir": "reports",
            "cache_dir": ".cache/red-crawler",
            "crawl_budget": 42,
            "search_term_limit": 5,
            "startup_jitter_minutes": 10,
            "slot_name": "nightly",
        }
    )
    assert command == [
        "uv",
        "run",
        "red-crawler",
        "collect-nightly",
        "--storage-state",
        "state.json",
        "--db-path",
        "data/red_crawler.db",
        "--report-dir",
        "reports",
        "--cache-dir",
        ".cache/red-crawler",
        "--crawl-budget",
        "42",
        "--search-term-limit",
        "5",
        "--startup-jitter-minutes",
        "10",
        "--slot-name",
        "nightly",
    ]


def test_build_report_weekly_command_uses_overrides(tmp_path):
    command = build_command(
        {
            "action": "report_weekly",
            "workspace_path": str(tmp_path),
            "db_path": "data/red_crawler.db",
            "report_dir": "reports",
            "days": 14,
        }
    )
    assert command == [
        "uv",
        "run",
        "red-crawler",
        "report-weekly",
        "--db-path",
        "data/red_crawler.db",
        "--report-dir",
        "reports",
        "--days",
        "14",
    ]


def test_build_list_contactable_command_uses_defaults_and_overrides(tmp_path):
    command = build_command(
        {
            "action": "list_contactable",
            "workspace_path": str(tmp_path),
            "db_path": "data/red_crawler.db",
            "min_relevance_score": 0.7,
            "limit": 25,
        }
    )
    assert command == [
        "uv",
        "run",
        "red-crawler",
        "list-contactable",
        "--db-path",
        "data/red_crawler.db",
        "--min-relevance-score",
        "0.7",
        "--limit",
        "25",
        "--format",
        "csv",
    ]


def test_handler_returns_structured_success_for_report_weekly(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    weekly_report = report_dir / "weekly-growth-report.json"
    weekly_report.write_text("{}", encoding="utf-8")
    creators_csv = report_dir / "contactable_creators.csv"
    creators_csv.write_text("id\n1\n", encoding="utf-8")

    def fake_run(argv, cwd, capture_output, text):
        assert argv == [
            "uv",
            "run",
            "red-crawler",
            "report-weekly",
            "--db-path",
            str(tmp_path / "data.db"),
            "--report-dir",
            str(report_dir),
            "--days",
            "7",
        ]
        assert cwd == tmp_path
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(argv, 0, stdout="weekly report ready", stderr="")

    monkeypatch.setattr(INDEX_MODULE.subprocess, "run", fake_run)

    result = run_handler(
        {
            "action": "report_weekly",
            "workspace_path": str(tmp_path),
            "db_path": str(tmp_path / "data.db"),
            "report_dir": str(report_dir),
            "days": 7,
        },
        {"config": {}},
    )

    assert result["status"] == "success"
    assert result["action"] == "report_weekly"
    assert result["command"] == (
        f"uv run red-crawler report-weekly --db-path {tmp_path / 'data.db'} "
        f"--report-dir {report_dir} --days 7"
    )
    assert result["summary"] == "report_weekly completed successfully."
    assert result["artifacts"] == {
        "weekly-growth-report.json": str(weekly_report),
        "contactable_creators.csv": str(creators_csv),
    }
    assert result["stdout"] == "weekly report ready"
    assert result["stderr"] == ""


def test_handler_finds_relative_report_artifacts_under_workspace(
    tmp_path, monkeypatch
):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    weekly_report = report_dir / "weekly-growth-report.json"
    weekly_report.write_text("{}", encoding="utf-8")
    creators_csv = report_dir / "contactable_creators.csv"
    creators_csv.write_text("id\n1\n", encoding="utf-8")

    monkeypatch.setattr(
        INDEX_MODULE.subprocess,
        "run",
        lambda argv, cwd, capture_output, text: subprocess.CompletedProcess(
            argv, 0, stdout="ok", stderr=""
        ),
    )

    result = run_handler(
        {
            "action": "report_weekly",
            "workspace_path": str(tmp_path),
            "db_path": "data/red_crawler.db",
            "report_dir": "reports",
        },
        {"config": {}},
    )

    assert result["status"] == "success"
    assert result["artifacts"] == {
        "weekly-growth-report.json": str(weekly_report),
        "contactable_creators.csv": str(creators_csv),
    }


def test_handler_uses_default_output_dir_for_crawl_seed_artifacts(
    tmp_path, monkeypatch
):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    accounts_csv = output_dir / "accounts.csv"
    accounts_csv.write_text("id\n1\n", encoding="utf-8")
    contact_leads_csv = output_dir / "contact_leads.csv"
    contact_leads_csv.write_text("id\n1\n", encoding="utf-8")
    run_report_json = output_dir / "run_report.json"
    run_report_json.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        INDEX_MODULE.subprocess,
        "run",
        lambda argv, cwd, capture_output, text: subprocess.CompletedProcess(
            argv, 0, stdout="ok", stderr=""
        ),
    )

    result = run_handler(
        {
            "action": "crawl_seed",
            "workspace_path": str(tmp_path),
            "storage_state": str(tmp_path / "state.json"),
            "seed_url": "https://www.xiaohongshu.com/user/profile/user-001",
        },
        {"config": {}},
    )

    assert result["status"] == "success"
    assert result["artifacts"] == {
        "accounts.csv": str(accounts_csv),
        "contact_leads.csv": str(contact_leads_csv),
        "run_report.json": str(run_report_json),
    }


def test_handler_uses_default_report_dir_for_weekly_artifacts(
    tmp_path, monkeypatch
):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    weekly_report = report_dir / "weekly-growth-report.json"
    weekly_report.write_text("{}", encoding="utf-8")
    creators_csv = report_dir / "contactable_creators.csv"
    creators_csv.write_text("id\n1\n", encoding="utf-8")

    monkeypatch.setattr(
        INDEX_MODULE.subprocess,
        "run",
        lambda argv, cwd, capture_output, text: subprocess.CompletedProcess(
            argv, 0, stdout="ok", stderr=""
        ),
    )

    result = run_handler(
        {
            "action": "report_weekly",
            "workspace_path": str(tmp_path),
            "db_path": str(tmp_path / "data.db"),
        },
        {"config": {}},
    )

    assert result["status"] == "success"
    assert result["artifacts"] == {
        "weekly-growth-report.json": str(weekly_report),
        "contactable_creators.csv": str(creators_csv),
    }


def test_handler_maps_non_zero_exit_to_execution_error(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")

    def fake_run(argv, cwd, capture_output, text):
        return subprocess.CompletedProcess(argv, 2, stdout="", stderr="boom")

    monkeypatch.setattr(INDEX_MODULE.subprocess, "run", fake_run)

    result = run_handler(
        {
            "action": "report_weekly",
            "workspace_path": str(tmp_path),
            "db_path": str(tmp_path / "data.db"),
            "report_dir": str(tmp_path / "reports"),
        },
        {"config": {}},
    )

    assert result["status"] == "error"
    assert result["error_type"] == "execution_error"
    assert result["command"] == (
        f"uv run red-crawler report-weekly --db-path {tmp_path / 'data.db'} "
        f"--report-dir {tmp_path / 'reports'}"
    )
    assert "exit code 2" in result["message"]
    assert result["stderr"] == "boom"
    assert "Inspect stderr" in result["suggested_fix"]


def test_handler_maps_subprocess_start_failure_to_execution_error(
    tmp_path, monkeypatch
):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")

    def fake_run(argv, cwd, capture_output, text):
        raise FileNotFoundError("uv not found")

    monkeypatch.setattr(INDEX_MODULE.subprocess, "run", fake_run)

    result = run_handler(
        {
            "action": "report_weekly",
            "workspace_path": str(tmp_path),
            "db_path": str(tmp_path / "data.db"),
            "report_dir": str(tmp_path / "reports"),
        },
        {"config": {}},
    )

    assert result["status"] == "error"
    assert result["error_type"] == "execution_error"
    assert "failed to start" in result["message"]
    assert "uv not found" in result["message"]
    assert result["command"] == (
        f"uv run red-crawler report-weekly --db-path {tmp_path / 'data.db'} "
        f"--report-dir {tmp_path / 'reports'}"
    )
    assert "runner command is installed" in result["suggested_fix"]


def test_handler_returns_artifact_error_for_missing_crawl_seed_outputs(
    tmp_path, monkeypatch
):
    (tmp_path / "pyproject.toml").write_text(RED_CRAWLER_PYPROJECT, encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "accounts.csv").write_text("id\n1\n", encoding="utf-8")

    def fake_run(argv, cwd, capture_output, text):
        return subprocess.CompletedProcess(argv, 0, stdout="done", stderr="")

    monkeypatch.setattr(INDEX_MODULE.subprocess, "run", fake_run)

    result = run_handler(
        {
            "action": "crawl_seed",
            "workspace_path": str(tmp_path),
            "storage_state": str(tmp_path / "state.json"),
            "seed_url": "https://www.xiaohongshu.com/user/profile/user-001",
            "output_dir": str(output_dir),
        },
        {"config": {}},
    )

    assert result["status"] == "error"
    assert result["error_type"] == "artifact_error"
    assert "contact_leads.csv" in result["message"]
    assert "run_report.json" in result["message"]
    assert result["command"] == (
        "uv run red-crawler crawl-seed --seed-url "
        "https://www.xiaohongshu.com/user/profile/user-001 "
        f"--storage-state {tmp_path / 'state.json'} --output-dir {output_dir}"
    )
    assert "Verify the CLI completed" in result["suggested_fix"]
