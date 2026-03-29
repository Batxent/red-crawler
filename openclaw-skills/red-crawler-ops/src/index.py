from __future__ import annotations

from pathlib import Path


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

    if action != "login" and not resolved.get("storage_state"):
        return structured_error(
            "configuration_error",
            "storage_state is required for non-login actions.",
            "Run login first or provide a storage_state path.",
        )

    workspace = Path(workspace_path)
    pyproject = workspace / "pyproject.toml"
    if not pyproject.exists():
        return structured_error(
            "configuration_error",
            f"workspace_path must contain pyproject.toml: {workspace}",
            "Point workspace_path at the red-crawler repository root.",
        )

    return {"status": "ok", "action": action, "resolved": resolved}


async def handler(input, context):
    resolved = merge_config(input or {}, context or {})
    validation = validate_request(resolved)
    if validation["status"] == "error":
        return validation

    return {
        "status": "success",
        "action": validation["action"],
        "error_type": None,
        "resolved": validation["resolved"],
    }
