from __future__ import annotations

import shlex
from pathlib import Path
from collections.abc import Sequence


KNOWN_ACTIONS = {
    "login",
    "crawl_seed",
    "collect_nightly",
    "report_weekly",
    "list_contactable",
}


def extract_config(context):
    if not isinstance(context, dict):
        return {}
    config = context.get("config", {})
    return config if isinstance(config, dict) else {}


def merge_config(input_data, context):
    if not isinstance(input_data, dict):
        return structured_error(
            "validation_error",
            "input must be a mapping.",
            "Pass a JSON object with action and parameters.",
        )
    config = extract_config(context)
    merged = dict(config)
    for key, value in input_data.items():
        if value is not None:
            merged[key] = value
    return merged


def structured_error(error_type, message, suggested_fix):
    return {
        "status": "error",
        "error_type": error_type,
        "message": message,
        "suggested_fix": suggested_fix,
    }


def _get_runner_command(resolved):
    runner_command = resolved.get("runner_command")
    if runner_command is None:
        return ["uv", "run", "red-crawler"]
    if isinstance(runner_command, str):
        parts = shlex.split(runner_command)
        return parts if parts else ["uv", "run", "red-crawler"]
    if isinstance(runner_command, Sequence):
        return [str(part) for part in runner_command]
    return ["uv", "run", "red-crawler"]


def _extend_flag(argv, flag, value):
    if value is not None:
        argv.extend([flag, str(value)])


def _extend_bool_flag(argv, flag, value):
    if value is True:
        argv.append(flag)


def build_login_command(resolved):
    argv = _get_runner_command(resolved) + ["login"]
    _extend_flag(argv, "--save-state", resolved.get("storage_state"))
    _extend_flag(argv, "--login-url", resolved.get("login_url"))
    return argv


def build_crawl_seed_command(resolved):
    argv = _get_runner_command(resolved) + ["crawl-seed"]
    _extend_flag(argv, "--seed-url", resolved.get("seed_url"))
    _extend_flag(argv, "--storage-state", resolved.get("storage_state"))
    _extend_flag(argv, "--max-accounts", resolved.get("max_accounts"))
    _extend_flag(argv, "--max-depth", resolved.get("max_depth"))
    _extend_bool_flag(
        argv,
        "--include-note-recommendations",
        resolved.get("include_note_recommendations"),
    )
    _extend_bool_flag(argv, "--safe-mode", resolved.get("safe_mode"))
    _extend_flag(argv, "--cache-dir", resolved.get("cache_dir"))
    _extend_flag(argv, "--cache-ttl-days", resolved.get("cache_ttl_days"))
    _extend_flag(argv, "--db-path", resolved.get("db_path"))
    _extend_flag(argv, "--output-dir", resolved.get("output_dir"))
    return argv


def build_collect_nightly_command(resolved):
    argv = _get_runner_command(resolved) + ["collect-nightly"]
    _extend_flag(argv, "--storage-state", resolved.get("storage_state"))
    _extend_flag(argv, "--db-path", resolved.get("db_path"))
    _extend_flag(argv, "--report-dir", resolved.get("report_dir"))
    _extend_flag(argv, "--cache-dir", resolved.get("cache_dir"))
    _extend_flag(argv, "--cache-ttl-days", resolved.get("cache_ttl_days"))
    _extend_flag(argv, "--crawl-budget", resolved.get("crawl_budget"))
    _extend_flag(argv, "--search-term-limit", resolved.get("search_term_limit"))
    _extend_flag(
        argv,
        "--startup-jitter-minutes",
        resolved.get("startup_jitter_minutes"),
    )
    _extend_flag(argv, "--slot-name", resolved.get("slot_name"))
    return argv


def build_report_weekly_command(resolved):
    argv = _get_runner_command(resolved) + ["report-weekly"]
    _extend_flag(argv, "--db-path", resolved.get("db_path"))
    _extend_flag(argv, "--report-dir", resolved.get("report_dir"))
    _extend_flag(argv, "--days", resolved.get("days"))
    return argv


def build_list_contactable_command(resolved):
    argv = _get_runner_command(resolved) + ["list-contactable"]
    _extend_flag(argv, "--db-path", resolved.get("db_path"))
    _extend_flag(argv, "--lead-type", resolved.get("lead_type"))
    _extend_flag(argv, "--creator-segment", resolved.get("creator_segment"))
    _extend_flag(
        argv,
        "--min-relevance-score",
        resolved.get("min_relevance_score"),
    )
    _extend_flag(argv, "--limit", resolved.get("limit"))
    _extend_flag(argv, "--format", resolved.get("format", "csv"))
    return argv


def build_command(resolved):
    action = str(resolved.get("action", "")).strip().lower()
    if action == "login":
        return build_login_command(resolved)
    if action == "crawl_seed":
        return build_crawl_seed_command(resolved)
    if action == "collect_nightly":
        return build_collect_nightly_command(resolved)
    if action == "report_weekly":
        return build_report_weekly_command(resolved)
    if action == "list_contactable":
        return build_list_contactable_command(resolved)
    raise ValueError(f"Unsupported action: {resolved.get('action')}")


def validate_request(resolved):
    action = str(resolved.get("action", "")).strip().lower()
    if action not in KNOWN_ACTIONS:
        return structured_error(
            "validation_error",
            f"Unsupported action: {resolved.get('action')}",
            "Use one of: login, crawl_seed, collect_nightly, report_weekly, list_contactable.",
        )

    if action == "crawl_seed" and not resolved.get("seed_url"):
        return structured_error(
            "validation_error",
            "seed_url is required for crawl_seed.",
            "Provide a valid Xiaohongshu seed profile URL.",
        )

    workspace_path = resolved.get("workspace_path")
    if not workspace_path:
        return structured_error(
            "configuration_error",
            "workspace_path is required.",
            "Provide workspace_path directly or set it in context.config.",
        )

    if action in {"login", "crawl_seed", "collect_nightly"} and not resolved.get(
        "storage_state"
    ):
        return structured_error(
            "configuration_error",
            f"storage_state is required for {action}.",
            "Run login first or provide a storage_state path.",
        )

    try:
        workspace = Path(workspace_path)
    except (TypeError, ValueError):
        return structured_error(
            "configuration_error",
            "workspace_path must be a path-like value.",
            "Provide workspace_path as a string or Path to the red-crawler repository root.",
        )
    pyproject = workspace / "pyproject.toml"
    if not pyproject.exists():
        return structured_error(
            "configuration_error",
            f"workspace_path must contain pyproject.toml: {workspace}",
            "Point workspace_path at the red-crawler repository root.",
        )

    return {"status": "ok", "action": action, "resolved": resolved}


async def handler(input, context):
    resolved = merge_config(input, context or {})
    if isinstance(resolved, dict) and resolved.get("status") == "error":
        return resolved
    validation = validate_request(resolved)
    if validation["status"] == "error":
        return validation

    normalized_action = validation["action"]
    resolved = dict(validation["resolved"])
    resolved["action"] = normalized_action

    return {
        "status": "success",
        "action": normalized_action,
        "error_type": None,
        "resolved": resolved,
    }
