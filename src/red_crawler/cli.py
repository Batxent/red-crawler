from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from red_crawler import __version__
from red_crawler.export.csv_writer import export_run
from red_crawler.nightly import (
    NightlyCollectConfig,
    run_nightly_collection,
    write_weekly_reports,
)
from red_crawler.runner import CrawlConfig, run_crawl_seed
from red_crawler.session import (
    open_xiaohongshu,
    save_login_storage_state,
    start_qr_login_storage_state,
    wait_for_qr_login_storage_state,
)
from red_crawler.store import CrawlerStore


def _default_login_qr_path(save_state: str) -> Path:
    return Path(save_state).with_suffix(".login-qr.png")


def _default_login_session_path(save_state: str) -> Path:
    return Path(save_state).with_suffix(".login-session.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="red-crawler")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl_seed = subparsers.add_parser("crawl-seed")
    crawl_seed.add_argument("--seed-url", required=True)
    crawl_seed.add_argument("--storage-state", required=True)
    crawl_seed.add_argument("--max-accounts", type=int, default=20)
    crawl_seed.add_argument("--max-depth", type=int, default=2)
    crawl_seed.add_argument("--include-note-recommendations", action="store_true")
    crawl_seed.set_defaults(safe_mode=True)
    crawl_seed.add_argument("--safe-mode", dest="safe_mode", action="store_true")
    crawl_seed.add_argument("--no-safe-mode", dest="safe_mode", action="store_false")
    crawl_seed.add_argument("--cache-dir")
    crawl_seed.add_argument("--cache-ttl-days", type=int, default=7)
    crawl_seed.add_argument("--db-path", default="data/red_crawler.db")
    crawl_seed.add_argument("--output-dir", default="output")

    login = subparsers.add_parser("login")
    login.add_argument("--save-state", required=True)
    login.add_argument("--login-url", default="https://www.xiaohongshu.com")
    login_qr_start = subparsers.add_parser("login-qr-start")
    login_qr_start.add_argument("--save-state", required=True)
    login_qr_start.add_argument("--login-url", default="https://www.xiaohongshu.com")
    login_qr_start.add_argument("--qr-path")
    login_qr_start.add_argument("--session-path")
    login_qr_start.add_argument("--timeout", type=int, default=180)

    login_qr_finish = subparsers.add_parser("login-qr-finish")
    login_qr_finish.add_argument("--save-state", required=True)
    login_qr_finish.add_argument("--session-path")

    login_qr_worker = subparsers.add_parser("login-qr-worker")
    login_qr_worker.add_argument("--save-state", required=True)
    login_qr_worker.add_argument("--login-url", default="https://www.xiaohongshu.com")
    login_qr_worker.add_argument("--qr-path", required=True)
    login_qr_worker.add_argument("--session-path", required=True)
    login_qr_worker.add_argument("--timeout", type=int, default=180)

    open_page = subparsers.add_parser("open")
    open_page.add_argument("--storage-state", required=True)
    open_page.add_argument("--open-url", default="https://www.xiaohongshu.com")

    subparsers.add_parser("install-browsers")

    collect_nightly = subparsers.add_parser("collect-nightly")
    collect_nightly.add_argument("--storage-state", required=True)
    collect_nightly.add_argument("--db-path", default="data/red_crawler.db")
    collect_nightly.add_argument("--report-dir", default="reports")
    collect_nightly.add_argument("--cache-dir", default=".cache/red-crawler")
    collect_nightly.add_argument("--cache-ttl-days", type=int, default=7)
    collect_nightly.add_argument("--crawl-budget", type=int, default=30)
    collect_nightly.add_argument("--search-term-limit", type=int, default=4)
    collect_nightly.add_argument("--startup-jitter-minutes", type=int, default=0)
    collect_nightly.add_argument("--slot-name", default="")

    report_weekly = subparsers.add_parser("report-weekly")
    report_weekly.add_argument("--db-path", default="data/red_crawler.db")
    report_weekly.add_argument("--report-dir", default="reports")
    report_weekly.add_argument("--days", type=int, default=7)

    list_contactable = subparsers.add_parser("list-contactable")
    list_contactable.add_argument("--db-path", default="data/red_crawler.db")
    list_contactable.add_argument("--lead-type", default="email")
    list_contactable.add_argument("--creator-segment", default="creator")
    list_contactable.add_argument("--min-relevance-score", type=float, default=0.0)
    list_contactable.add_argument("--limit", type=int, default=20)
    list_contactable.add_argument("--format", choices=("table", "csv"), default="table")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "login":
        save_login_storage_state(
            output_path=Path(args.save_state),
            login_url=args.login_url,
        )
        return 0


    if args.command == "login-qr-start":
        qr_path = Path(args.qr_path) if args.qr_path else _default_login_qr_path(args.save_state)
        session_path = (
            Path(args.session_path)
            if args.session_path
            else _default_login_session_path(args.save_state)
        )
        pid = start_qr_login_storage_state(
            output_path=Path(args.save_state),
            login_url=args.login_url,
            qr_path=qr_path,
            session_path=session_path,
            timeout_seconds=args.timeout,
        )
        print(
            json.dumps(
                {
                    "pid": pid,
                    "qr_path": str(qr_path),
                    "session_path": str(session_path),
                    "storage_state": str(Path(args.save_state)),
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "login-qr-worker":
        wait_for_qr_login_storage_state(
            output_path=Path(args.save_state),
            login_url=args.login_url,
            qr_path=Path(args.qr_path),
            session_path=Path(args.session_path),
            timeout_seconds=args.timeout,
        )
        return 0

    if args.command == "login-qr-finish":
        state_path = Path(args.save_state)
        session_path = (
            Path(args.session_path)
            if args.session_path
            else _default_login_session_path(args.save_state)
        )
        if state_path.exists():
            print(json.dumps({"status": "authenticated", "storage_state": str(state_path)}))
            return 0
        if not session_path.exists():
            print(json.dumps({"status": "missing_session", "session_path": str(session_path)}))
            return 2
        status = json.loads(session_path.read_text(encoding="utf-8"))
        print(json.dumps(status, ensure_ascii=False))
        return 0
    if args.command == "open":
        open_xiaohongshu(
            storage_state=args.storage_state,
            open_url=args.open_url,
        )
        return 0

    if args.command == "install-browsers":
        return subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=False,
        ).returncode

    if args.command == "collect-nightly":
        config = NightlyCollectConfig(
            storage_state=args.storage_state,
            db_path=str(args.db_path),
            report_dir=str(args.report_dir),
            cache_dir=str(args.cache_dir),
            cache_ttl_days=args.cache_ttl_days,
            crawl_budget=args.crawl_budget,
            search_term_limit=args.search_term_limit,
            startup_jitter_minutes=args.startup_jitter_minutes,
            slot_name=args.slot_name,
        )
        run_nightly_collection(config)
        return 0

    if args.command == "report-weekly":
        store = CrawlerStore(Path(args.db_path))
        write_weekly_reports(
            store,
            report_dir=Path(args.report_dir),
            now=datetime.now(timezone.utc),
            days=args.days,
        )
        return 0

    if args.command == "list-contactable":
        store = CrawlerStore(Path(args.db_path))
        creators = store.list_contactable_creators(
            lead_type=args.lead_type,
            creator_segment=args.creator_segment,
            min_relevance_score=args.min_relevance_score,
            limit=args.limit,
        )
        if args.format == "csv":
            print(
                "account_id,profile_url,nickname,email,creator_segment,relevance_score,lead_count"
            )
            for creator in creators:
                print(
                    ",".join(
                        [
                            creator.account_id,
                            creator.profile_url,
                            creator.nickname,
                            creator.email,
                            creator.creator_segment,
                            f"{creator.relevance_score:.2f}",
                            str(creator.lead_count),
                        ]
                    )
                )
        else:
            print("account_id\tnickname\temail\trelevance_score\tlead_count")
            for creator in creators:
                print(
                    "\t".join(
                        [
                            creator.account_id,
                            creator.nickname,
                            creator.email,
                            f"{creator.relevance_score:.2f}",
                            str(creator.lead_count),
                        ]
                    )
                )
        return 0

    if args.command != "crawl-seed":
        parser.error(f"unsupported command: {args.command}")

    output_dir = Path(args.output_dir)
    config = CrawlConfig(
        seed_url=args.seed_url,
        storage_state=args.storage_state,
        output_dir=str(output_dir),
        max_accounts=args.max_accounts,
        max_depth=args.max_depth,
        include_note_recommendations=args.include_note_recommendations,
        safe_mode=args.safe_mode,
        cache_dir=args.cache_dir,
        cache_ttl_days=args.cache_ttl_days,
    )
    result = run_crawl_seed(config)
    export_run(result, output_dir)
    store = CrawlerStore(Path(args.db_path))
    store.record_crawl_result(
        result,
        run_type="crawl_seed",
        safe_mode=args.safe_mode,
        started_at=datetime.now(timezone.utc),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
