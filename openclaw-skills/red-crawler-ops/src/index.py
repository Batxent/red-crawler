from __future__ import annotations

import shlex
import subprocess
import tomllib
from pathlib import Path
from collections.abc import Sequence


KNOWN_ACTIONS = {
    "bootstrap",
    "install_or_bootstrap",
    "login",
    "crawl_seed",
    "collect_nightly",
    "report_weekly",
    "list_contactable",
}

EXPECTED_ARTIFACTS = {
    "crawl_seed": ("accounts.csv", "contact_leads.csv", "run_report.json"),
    "collect_nightly": (
        "daily-run-report.json",
        "weekly-growth-report.json",
        "contactable_creators.csv",
    ),
    "report_weekly": (
        "weekly-growth-report.json",
        "contactable_creators.csv",
    ),
}

CONFIG_DEFAULTS = (
    ("default_crawl_budget", "crawl_budget"),
    ("default_report_days", "days"),
    ("default_list_limit", "limit"),
)

CLI_ARTIFACT_DEFAULTS = {
    "crawl_seed": "output",
    "collect_nightly": "reports",
    "report_weekly": "reports",
}

WORKSPACE_DEFAULT_PATH = "."
WORKSPACE_DEFAULT_NAME = "red-crawler"
EXPECTED_PROJECT_NAME = "red-crawler"


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
    for default_key, target_key in CONFIG_DEFAULTS:
        if target_key not in merged and merged.get(default_key) is not None:
            merged[target_key] = merged[default_key]
    return merged


def structured_error(error_type, message, suggested_fix):
    return {
        "status": "error",
        "error_type": error_type,
        "message": message,
        "suggested_fix": suggested_fix,
    }


def _display_command(argv):
    return shlex.join(str(part) for part in argv)


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
    if action == "bootstrap":
        raise ValueError("bootstrap uses multi-step execution")
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


def run_command(argv, cwd):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


def _workspace_root(resolved):
    return Path(resolved["workspace_path"])


def _is_red_crawler_workspace(workspace):
    pyproject = workspace / "pyproject.toml"
    if not pyproject.exists():
        return False

    try:
        with pyproject.open("rb") as handle:
            project_name = tomllib.load(handle).get("project", {}).get("name")
    except (OSError, tomllib.TOMLDecodeError):
        return False

    return project_name == EXPECTED_PROJECT_NAME


def _resolve_workspace_path_value(path_value, resolved):
    base = _workspace_root(resolved)
    path = Path(path_value)
    if path.is_absolute():
        return path
    return base / path


def _resolve_artifact_dir(path_value, resolved):
    base = _workspace_root(resolved)
    if path_value is None:
        default_dir = CLI_ARTIFACT_DEFAULTS.get(str(resolved.get("action", "")).strip().lower())
        if default_dir is None:
            return base
        return base / default_dir

    return _resolve_workspace_path_value(path_value, resolved)


def _artifact_root(action, resolved):
    if action == "crawl_seed":
        return _resolve_artifact_dir(resolved.get("output_dir"), resolved)
    if action in {"collect_nightly", "report_weekly"}:
        return _resolve_artifact_dir(resolved.get("report_dir"), resolved)
    return None


def _collect_artifacts(action, resolved):
    expected = EXPECTED_ARTIFACTS.get(action, ())
    if not expected:
        return {}, []

    root = _artifact_root(action, resolved)
    artifacts = {}
    missing = []

    for name in expected:
        artifact_path = root / name
        if artifact_path.exists():
            artifacts[name] = str(artifact_path)
        else:
            missing.append(name)

    return artifacts, missing


def validate_request(resolved):
    action = str(resolved.get("action", "")).strip().lower()
    if action not in KNOWN_ACTIONS:
        return structured_error(
            "validation_error",
            f"Unsupported action: {resolved.get('action')}",
            (
                "Use one of: install_or_bootstrap, bootstrap, login, crawl_seed, "
                "collect_nightly, report_weekly, list_contactable."
            ),
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

    if action in {"bootstrap", "login", "crawl_seed", "collect_nightly"} and not resolved.get(
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
    if not _is_red_crawler_workspace(workspace):
        return structured_error(
            "configuration_error",
            (
                "workspace_path must be a red-crawler repository root with "
                f"pyproject.toml name = '{EXPECTED_PROJECT_NAME}': {workspace}"
            ),
            "Point workspace_path at the red-crawler repository root with pyproject.toml name = 'red-crawler'.",
        )

    return {"status": "ok", "action": action, "resolved": resolved}


def _resolve_install_workspace(resolved):
    workspace_path = resolved.get("workspace_path")
    if workspace_path:
        workspace = Path(workspace_path).expanduser().resolve()
        if workspace.exists() and _is_red_crawler_workspace(workspace):
            return workspace
        if str(workspace_path).strip() not in {WORKSPACE_DEFAULT_PATH, "./"}:
            return workspace

    workspace_parent = resolved.get("workspace_parent", WORKSPACE_DEFAULT_PATH)
    workspace_name = resolved.get("workspace_name", WORKSPACE_DEFAULT_NAME)
    return (Path(workspace_parent) / str(workspace_name)).expanduser().resolve()


def _install_or_bootstrap_result(resolved):
    try:
        workspace = _resolve_install_workspace(resolved)
    except (TypeError, ValueError):
        return structured_error(
            "configuration_error",
            "workspace_path must be a path-like value.",
            (
                "Provide workspace_path directly or set workspace_parent and "
                "workspace_name to path-like values."
            ),
        )

    repo_url = resolved.get("repo_url")
    if not repo_url:
        return structured_error(
            "configuration_error",
            "repo_url is required for install_or_bootstrap.",
            "Provide a git clone URL for the red-crawler repository.",
        )

    command_displays = []
    repo_cloned = False

    if workspace.exists():
        if not workspace.is_dir():
            return structured_error(
                "configuration_error",
                f"workspace_path already exists and is not a directory: {workspace}",
                "Point workspace_path at a directory or choose a different target path.",
            )
        if not _is_red_crawler_workspace(workspace):
            return structured_error(
                "configuration_error",
                (
                    "workspace_path must be a red-crawler repository root with "
                    f"pyproject.toml name = '{EXPECTED_PROJECT_NAME}': {workspace}"
                ),
                (
                    "Point workspace_path at a red-crawler repository root or "
                    "remove the conflicting directory before rerunning "
                    "install_or_bootstrap."
                ),
            )
    else:
        clone_command = ["git", "clone"]
        if resolved.get("branch"):
            clone_command.extend(["--branch", str(resolved["branch"])])
        clone_command.extend([str(repo_url), str(workspace)])
        command_displays.append(_display_command(clone_command))

        workspace.parent.mkdir(parents=True, exist_ok=True)
        try:
            completed = run_command(clone_command, cwd=workspace.parent)
        except OSError as exc:
            return {
                "status": "error",
                "action": "install_or_bootstrap",
                "error_type": "execution_error",
                "message": f"install_or_bootstrap failed to start: {exc}.",
                "command": command_displays[-1],
                "stdout": "",
                "stderr": "",
                "suggested_fix": (
                    "Verify git is installed and available from the current "
                    "environment, then rerun install_or_bootstrap."
                ),
            }

        if completed.returncode != 0:
            return {
                "status": "error",
                "action": "install_or_bootstrap",
                "error_type": "execution_error",
                "message": (
                    "install_or_bootstrap failed while cloning the repository "
                    f"with exit code {completed.returncode}."
                ),
                "command": command_displays[-1],
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "suggested_fix": (
                    "Inspect stderr, verify repo_url and network access, and rerun "
                    "install_or_bootstrap."
                ),
            }

        if not _is_red_crawler_workspace(workspace):
            return {
                "status": "error",
                "action": "install_or_bootstrap",
                "error_type": "artifact_error",
                "message": (
                    "install_or_bootstrap cloned the repository but the target "
                    "workspace is not a valid red-crawler repository."
                ),
                "command": command_displays[-1],
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "suggested_fix": (
                    "Verify repo_url points at the red-crawler repository with "
                    "project.name = 'red-crawler', then rerun install_or_bootstrap."
                ),
            }
        repo_cloned = True

    bootstrap_resolved = dict(resolved)
    bootstrap_resolved["action"] = "bootstrap"
    bootstrap_resolved["workspace_path"] = str(workspace)

    validation = validate_request(bootstrap_resolved)
    if validation["status"] == "error":
        return validation

    bootstrap_result = _bootstrap_result(validation["resolved"])
    if bootstrap_result["status"] == "error":
        result = dict(bootstrap_result)
        result["action"] = "install_or_bootstrap"
        if command_displays:
            bootstrap_command = result.get("command", "")
            result["command"] = " && ".join(
                part for part in [*command_displays, bootstrap_command] if part
            )
        return result

    artifacts = dict(bootstrap_result.get("artifacts", {}))
    artifacts["workspace_path"] = str(workspace)

    metrics = dict(bootstrap_result.get("metrics", {}))
    metrics["repo_cloned"] = repo_cloned
    ordered_metrics = {
        "repo_cloned": metrics.get("repo_cloned", False),
        "uv_sync_ran": metrics.get("uv_sync_ran", False),
        "playwright_install_ran": metrics.get("playwright_install_ran", False),
        "login_ran": metrics.get("login_ran", False),
        "state_file_created": metrics.get("state_file_created", False),
    }

    command_parts = [*command_displays, bootstrap_result.get("command", "")]
    return {
        "status": "success",
        "action": "install_or_bootstrap",
        "command": " && ".join(part for part in command_parts if part),
        "artifacts": artifacts,
        "metrics": ordered_metrics,
        "next_step": "You can now run crawl_seed or collect_nightly.",
        "summary": "install_or_bootstrap completed successfully.",
        "stdout": "",
        "stderr": "",
    }


def _bootstrap_commands(resolved):
    commands = []
    if resolved.get("sync_dependencies", True):
        commands.append(["uv", "sync"])
    if resolved.get("install_browser", True):
        commands.append(["uv", "run", "playwright", "install", "chromium"])

    state_path = _resolve_workspace_path_value(resolved["storage_state"], resolved)
    if resolved.get("force_login", False) or not state_path.exists():
        commands.append(build_login_command(resolved))

    return commands, state_path


def _bootstrap_result(resolved):
    commands, state_path = _bootstrap_commands(resolved)
    command_displays = []

    for command in commands:
        command_display = _display_command(command)
        command_displays.append(command_display)
        try:
            completed = run_command(command, cwd=_workspace_root(resolved))
        except OSError as exc:
            return {
                "status": "error",
                "action": "bootstrap",
                "error_type": "execution_error",
                "message": f"bootstrap failed to start: {exc}.",
                "command": command_display,
                "stdout": "",
                "stderr": "",
                "suggested_fix": (
                    "Verify the required bootstrap command is installed and "
                    "available in the current environment, then rerun bootstrap."
                ),
            }

        if completed.returncode != 0:
            return {
                "status": "error",
                "action": "bootstrap",
                "error_type": "execution_error",
                "message": (
                    f"bootstrap step failed with exit code {completed.returncode}."
                ),
                "command": command_display,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "suggested_fix": (
                    "Inspect stderr, fix the failing bootstrap step, and rerun "
                    "bootstrap."
                ),
            }

    if not state_path.exists():
        return {
            "status": "error",
            "action": "bootstrap",
            "error_type": "artifact_error",
            "message": (
                f"bootstrap completed but missing required artifact: {state_path.name}."
            ),
            "command": " && ".join(command_displays),
            "stdout": "",
            "stderr": "",
            "suggested_fix": (
                "Complete the interactive login flow and ensure the storage_state "
                "file is written before rerunning bootstrap."
            ),
        }

    login_command = build_login_command(resolved)
    metrics = {
        "uv_sync_ran": resolved.get("sync_dependencies", True),
        "playwright_install_ran": resolved.get("install_browser", True),
        "login_ran": login_command in commands,
        "state_file_created": state_path.exists(),
    }
    return {
        "status": "success",
        "action": "bootstrap",
        "command": " && ".join(command_displays),
        "artifacts": {state_path.name: str(state_path)},
        "metrics": metrics,
        "next_step": "You can now run crawl_seed or collect_nightly.",
        "summary": "bootstrap completed successfully.",
        "stdout": "",
        "stderr": "",
    }


async def handler(input, context):
    resolved = merge_config(input, context or {})
    if isinstance(resolved, dict) and resolved.get("status") == "error":
        return resolved
    normalized_action = str(resolved.get("action", "")).strip().lower()
    if normalized_action == "install_or_bootstrap":
        resolved["action"] = normalized_action
        return _install_or_bootstrap_result(resolved)
    validation = validate_request(resolved)
    if validation["status"] == "error":
        return validation

    normalized_action = validation["action"]
    resolved = dict(validation["resolved"])
    resolved["action"] = normalized_action
    if normalized_action == "bootstrap":
        return _bootstrap_result(resolved)
    command = build_command(resolved)
    command_display = _display_command(command)
    try:
        completed = run_command(command, cwd=_workspace_root(resolved))
    except OSError as exc:
        return {
            "status": "error",
            "action": normalized_action,
            "error_type": "execution_error",
            "message": f"{normalized_action} failed to start: {exc}.",
            "command": command_display,
            "stdout": "",
            "stderr": "",
            "suggested_fix": (
                "Verify the runner command is installed and available from the "
                "current environment, then rerun the action."
            ),
        }

    if completed.returncode != 0:
        return {
            "status": "error",
            "action": normalized_action,
            "error_type": "execution_error",
            "message": (
                f"{normalized_action} failed with exit code {completed.returncode}."
            ),
            "command": command_display,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "suggested_fix": (
                "Inspect stderr, verify the red-crawler CLI arguments, and rerun "
                "after fixing the underlying issue."
            ),
        }

    artifacts, missing_artifacts = _collect_artifacts(normalized_action, resolved)
    if missing_artifacts:
        return {
            "status": "error",
            "action": normalized_action,
            "error_type": "artifact_error",
            "message": (
                f"{normalized_action} completed but missing required artifacts: "
                f"{', '.join(missing_artifacts)}."
            ),
            "command": command_display,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "suggested_fix": (
                "Verify the CLI completed in the expected output directory and "
                "check whether the underlying command wrote all required files."
            ),
        }

    return {
        "status": "success",
        "action": normalized_action,
        "command": command_display,
        "artifacts": artifacts,
        "summary": f"{normalized_action} completed successfully.",
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
