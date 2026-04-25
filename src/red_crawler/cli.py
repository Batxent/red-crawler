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
from red_crawler.runner import (
    CrawlConfig,
    HomefeedCrawlConfig,
    SearchCrawlConfig,
    run_crawl_homefeed,
    run_crawl_search,
    run_crawl_seed,
)
from red_crawler.session import (
    DEFAULT_COSMETICS_HOMEFEED_URL,
    SUPPORTED_BROWSER_MODES,
    SUPPORTED_INTERACTION_MODES,
    SUPPORTED_ROTATION_MODES,
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


def _effective_homefeed_scroll_rounds(
    *,
    requested_scroll_rounds: int,
    max_accounts: int,
    existing_account_count: int,
) -> int:
    requested = max(int(requested_scroll_rounds), 0)
    if max_accounts <= 0 or existing_account_count <= 0:
        return requested
    backfill_multiplier = 1 + (existing_account_count // max_accounts)
    return requested * min(backfill_multiplier, 5)


def _add_browser_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--browser-mode",
        choices=SUPPORTED_BROWSER_MODES,
        default="local",
        help="Browser connection mode. Use bright-data to connect to Bright Data Browser API.",
    )
    parser.add_argument(
        "--browser-endpoint",
        help="Remote CDP WebSocket endpoint, for example wss://USER:PASS@brd.superproxy.io:9222.",
    )
    parser.add_argument(
        "--browser-auth",
        help="Bright Data Browser API credentials formatted as USER:PASS. Use {session} to inject a rotating session id.",
    )
    parser.add_argument(
        "--proxy",
        help="Proxy URL for local browser mode, for example http://user:pass@host:port or socks5://host:port.",
    )
    parser.add_argument(
        "--proxy-list",
        help="Path to a newline-delimited proxy list. With --rotation-mode session, each retry uses the next proxy.",
    )
    parser.add_argument(
        "--rotation-mode",
        choices=SUPPORTED_ROTATION_MODES,
        default="none",
        help="Proxy rotation mode. session retries the crawl with a new browser session on 403/429.",
    )
    parser.add_argument(
        "--rotation-retries",
        type=int,
        default=1,
        help="Number of new browser sessions to try after 403/429 when session rotation is enabled.",
    )
    parser.set_defaults(randomize_headers=True)
    parser.add_argument(
        "--randomize-headers",
        dest="randomize_headers",
        action="store_true",
        help="Generate a User-Agent, Accept-Language, and Sec-CH-UA header set per browser session.",
    )
    parser.add_argument(
        "--no-randomize-headers",
        dest="randomize_headers",
        action="store_false",
        help="Disable per-session request header randomization.",
    )


def _add_discovery_collect_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--storage-state", default="")
    parser.add_argument("--db-path", default="data/red_crawler.db")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--cache-dir", default=".cache/red-crawler")
    parser.add_argument("--cache-ttl-days", type=int, default=7)
    parser.add_argument("--crawl-budget", type=int, default=12)
    parser.add_argument("--search-term-limit", type=int, default=2)
    parser.add_argument("--daily-account-budget", type=int, default=12)
    parser.add_argument("--daily-search-term-budget", type=int, default=2)
    parser.add_argument("--startup-jitter-minutes", type=int, default=0)
    parser.add_argument("--slot-name", default="")
    parser.add_argument("--homefeed-url", default=DEFAULT_COSMETICS_HOMEFEED_URL)
    parser.add_argument(
        "--interaction-mode",
        choices=SUPPORTED_INTERACTION_MODES,
        default="playwright",
    )
    _add_browser_args(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="red-crawler")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl_seed = subparsers.add_parser("crawl-seed")
    crawl_seed.add_argument("--seed-url", required=True)
    crawl_seed.add_argument("--storage-state", default="")
    crawl_seed.add_argument("--max-accounts", type=int, default=20)
    crawl_seed.add_argument("--max-depth", type=int, default=2)
    crawl_seed.add_argument("--include-note-recommendations", action="store_true")
    crawl_seed.set_defaults(safe_mode=True)
    crawl_seed.add_argument("--safe-mode", dest="safe_mode", action="store_true")
    crawl_seed.add_argument("--no-safe-mode", dest="safe_mode", action="store_false")
    crawl_seed.add_argument("--cache-dir")
    crawl_seed.add_argument("--cache-ttl-days", type=int, default=7)
    crawl_seed.add_argument("--gender-filter")
    crawl_seed.add_argument(
        "--interaction-mode",
        choices=SUPPORTED_INTERACTION_MODES,
        default="playwright",
    )
    _add_browser_args(crawl_seed)
    crawl_seed.add_argument("--db-path", default="data/red_crawler.db")
    crawl_seed.add_argument("--output-dir", default="output")

    crawl_search = subparsers.add_parser("crawl-search")
    crawl_search.add_argument("--search-term", required=True)
    crawl_search.add_argument("--storage-state", default="")
    crawl_search.add_argument("--max-accounts", type=int, default=20)
    crawl_search.add_argument("--search-scroll-rounds", type=int, default=2)
    crawl_search.add_argument("--min-followers", type=int, default=0)
    crawl_search.add_argument("--min-relevance-score", type=float, default=0.0)
    crawl_search.add_argument("--creator-only", action="store_true")
    crawl_search.set_defaults(safe_mode=True)
    crawl_search.add_argument("--safe-mode", dest="safe_mode", action="store_true")
    crawl_search.add_argument("--no-safe-mode", dest="safe_mode", action="store_false")
    crawl_search.add_argument("--cache-dir")
    crawl_search.add_argument("--cache-ttl-days", type=int, default=7)
    crawl_search.add_argument("--gender-filter")
    crawl_search.add_argument(
        "--interaction-mode",
        choices=SUPPORTED_INTERACTION_MODES,
        default="playwright",
    )
    _add_browser_args(crawl_search)
    crawl_search.add_argument("--db-path", default="data/red_crawler.db")
    crawl_search.add_argument("--output-dir", default="output")

    crawl_homefeed = subparsers.add_parser("crawl-homefeed")
    crawl_homefeed.add_argument("--homefeed-url", default=DEFAULT_COSMETICS_HOMEFEED_URL)
    crawl_homefeed.add_argument("--storage-state", default="")
    crawl_homefeed.add_argument("--max-accounts", type=int, default=20)
    crawl_homefeed.add_argument("--search-scroll-rounds", type=int, default=2)
    crawl_homefeed.add_argument("--min-followers", type=int, default=0)
    crawl_homefeed.add_argument("--min-relevance-score", type=float, default=0.0)
    crawl_homefeed.add_argument("--creator-only", action="store_true")
    crawl_homefeed.set_defaults(safe_mode=True)
    crawl_homefeed.add_argument("--safe-mode", dest="safe_mode", action="store_true")
    crawl_homefeed.add_argument("--no-safe-mode", dest="safe_mode", action="store_false")
    crawl_homefeed.add_argument("--cache-dir")
    crawl_homefeed.add_argument("--cache-ttl-days", type=int, default=7)
    crawl_homefeed.add_argument("--gender-filter")
    crawl_homefeed.add_argument(
        "--interaction-mode",
        choices=SUPPORTED_INTERACTION_MODES,
        default="playwright",
    )
    _add_browser_args(crawl_homefeed)
    crawl_homefeed.add_argument("--db-path", default="data/red_crawler.db")
    crawl_homefeed.add_argument("--output-dir", default="output")

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
    _add_discovery_collect_args(collect_nightly)

    crawl_discover = subparsers.add_parser("crawl-discover")
    _add_discovery_collect_args(crawl_discover)

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

    if args.command in {"collect-nightly", "crawl-discover"}:
        config = NightlyCollectConfig(
            storage_state=args.storage_state,
            db_path=str(args.db_path),
            report_dir=str(args.report_dir),
            cache_dir=str(args.cache_dir),
            cache_ttl_days=args.cache_ttl_days,
            crawl_budget=args.crawl_budget,
            search_term_limit=args.search_term_limit,
            daily_account_budget=args.daily_account_budget,
            daily_search_term_budget=args.daily_search_term_budget,
            startup_jitter_minutes=args.startup_jitter_minutes,
            slot_name=args.slot_name,
            homefeed_url=args.homefeed_url,
            interaction_mode=args.interaction_mode,
            browser_mode=args.browser_mode,
            browser_endpoint=args.browser_endpoint,
            browser_auth=args.browser_auth,
            rotation_mode=args.rotation_mode,
            rotation_retries=args.rotation_retries,
            randomize_headers=args.randomize_headers,
            proxy=args.proxy,
            proxy_list=args.proxy_list,
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

    if args.command == "crawl-homefeed":
        output_dir = Path(args.output_dir)
        store = CrawlerStore(Path(args.db_path))
        existing_account_ids = tuple(sorted(store.list_creator_account_ids()))
        config = HomefeedCrawlConfig(
            homefeed_url=args.homefeed_url,
            storage_state=args.storage_state,
            output_dir=str(output_dir),
            max_accounts=args.max_accounts,
            search_scroll_rounds=_effective_homefeed_scroll_rounds(
                requested_scroll_rounds=args.search_scroll_rounds,
                max_accounts=args.max_accounts,
                existing_account_count=len(existing_account_ids),
            ),
            min_followers=args.min_followers,
            min_relevance_score=args.min_relevance_score,
            creator_only=args.creator_only,
            safe_mode=args.safe_mode,
            interaction_mode=args.interaction_mode,
            browser_mode=args.browser_mode,
            browser_endpoint=args.browser_endpoint,
            browser_auth=args.browser_auth,
            rotation_mode=args.rotation_mode,
            rotation_retries=args.rotation_retries,
            randomize_headers=args.randomize_headers,
            proxy=args.proxy,
            proxy_list=args.proxy_list,
            cache_dir=args.cache_dir,
            cache_ttl_days=args.cache_ttl_days,
            gender_filter=args.gender_filter,
            existing_account_ids=existing_account_ids,
        )
        result = run_crawl_homefeed(config)
        export_run(result, output_dir)
        store.record_crawl_result(
            result,
            run_type="crawl_homefeed",
            safe_mode=args.safe_mode,
            started_at=datetime.now(timezone.utc),
        )
        return 0

    if args.command == "crawl-search":
        output_dir = Path(args.output_dir)
        config = SearchCrawlConfig(
            search_term=args.search_term,
            storage_state=args.storage_state,
            output_dir=str(output_dir),
            max_accounts=args.max_accounts,
            search_scroll_rounds=args.search_scroll_rounds,
            min_followers=args.min_followers,
            min_relevance_score=args.min_relevance_score,
            creator_only=args.creator_only,
            safe_mode=args.safe_mode,
            interaction_mode=args.interaction_mode,
            browser_mode=args.browser_mode,
            browser_endpoint=args.browser_endpoint,
            browser_auth=args.browser_auth,
            rotation_mode=args.rotation_mode,
            rotation_retries=args.rotation_retries,
            randomize_headers=args.randomize_headers,
            proxy=args.proxy,
            proxy_list=args.proxy_list,
            cache_dir=args.cache_dir,
            cache_ttl_days=args.cache_ttl_days,
            gender_filter=args.gender_filter,
        )
        result = run_crawl_search(config)
        export_run(result, output_dir)
        store = CrawlerStore(Path(args.db_path))
        store.record_crawl_result(
            result,
            run_type="crawl_search",
            safe_mode=args.safe_mode,
            started_at=datetime.now(timezone.utc),
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
        interaction_mode=args.interaction_mode,
        browser_mode=args.browser_mode,
        browser_endpoint=args.browser_endpoint,
        browser_auth=args.browser_auth,
        rotation_mode=args.rotation_mode,
        rotation_retries=args.rotation_retries,
        randomize_headers=args.randomize_headers,
        proxy=args.proxy,
        proxy_list=args.proxy_list,
        cache_dir=args.cache_dir,
        cache_ttl_days=args.cache_ttl_days,
        gender_filter=args.gender_filter,
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
