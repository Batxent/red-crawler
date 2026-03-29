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


def test_crawl_seed_requires_storage_state(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
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
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    result = run_handler(
        {"action": "login", "workspace_path": str(tmp_path)},
        {"config": {}},
    )
    assert result["status"] == "error"
    assert result["error_type"] == "configuration_error"
    assert "storage_state" in result["message"]


def test_report_weekly_does_not_require_storage_state(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
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


def test_list_contactable_does_not_require_storage_state(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
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
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
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
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
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
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
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


def test_handler_maps_non_zero_exit_to_execution_error(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")

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


def test_handler_returns_artifact_error_for_missing_crawl_seed_outputs(
    tmp_path, monkeypatch
):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
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
