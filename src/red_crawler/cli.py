from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from red_crawler.export.csv_writer import export_run
from red_crawler.runner import CrawlConfig, run_crawl_seed
from red_crawler.session import open_xiaohongshu, save_login_storage_state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="red-crawler")
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl_seed = subparsers.add_parser("crawl-seed")
    crawl_seed.add_argument("--seed-url", required=True)
    crawl_seed.add_argument("--storage-state", required=True)
    crawl_seed.add_argument("--max-accounts", type=int, default=20)
    crawl_seed.add_argument("--max-depth", type=int, default=2)
    crawl_seed.add_argument("--include-note-recommendations", action="store_true")
    crawl_seed.add_argument("--output-dir", default="output")

    login = subparsers.add_parser("login")
    login.add_argument("--save-state", required=True)
    login.add_argument("--login-url", default="https://www.xiaohongshu.com")

    open_page = subparsers.add_parser("open")
    open_page.add_argument("--storage-state", required=True)
    open_page.add_argument("--open-url", default="https://www.xiaohongshu.com")
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

    if args.command == "open":
        open_xiaohongshu(
            storage_state=args.storage_state,
            open_url=args.open_url,
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
    )
    result = run_crawl_seed(config)
    export_run(result, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
