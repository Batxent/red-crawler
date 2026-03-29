from __future__ import annotations

import asyncio
import importlib.util
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


def test_workspace_path_can_come_from_context_config(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    result = run_handler(
        {"action": "LOGIN", "storage_state": str(tmp_path / "state.json")},
        {"config": {"workspace_path": str(tmp_path)}},
    )
    assert result["status"] == "success"
    assert result["action"] == "login"
    assert result["resolved"]["action"] == "login"


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
