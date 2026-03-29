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
