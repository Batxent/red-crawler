import csv
import json

import pytest

from red_crawler.cli import main
from red_crawler.models import AccountRecord, ContactLead, CrawlResult, RunReport
from red_crawler.store import ContactableCreator


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert "red-crawler 0.1.2" in capsys.readouterr().out


def test_cli_install_browsers_runs_playwright_install(monkeypatch):
    captured = {}

    class Completed:
        returncode = 0

    def fake_run(argv, check):
        captured["argv"] = argv
        captured["check"] = check
        return Completed()

    monkeypatch.setattr("red_crawler.cli.subprocess.run", fake_run)
    monkeypatch.setattr("red_crawler.cli.sys.executable", "/tmp/python")

    assert main(["install-browsers"]) == 0
    assert captured == {
        "argv": ["/tmp/python", "-m", "playwright", "install", "chromium"],
        "check": False,
    }


def test_cli_crawl_seed_exports_expected_files(tmp_path, monkeypatch):
    def fake_run_crawl_seed(config):
        assert config.seed_url == "https://www.xiaohongshu.com/user/profile/user-001"
        assert config.max_depth == 2
        assert config.safe_mode is True
        assert config.interaction_mode == "os-mouse"
        assert config.cache_dir == str(tmp_path / "cache")
        assert config.cache_ttl_days == 7
        assert config.gender_filter == "女"
        return CrawlResult(
            accounts=[
                AccountRecord(
                    account_id="user-001",
                    profile_url=config.seed_url,
                    nickname="Miaç©¿æ­æ‰‹è®°",
                    bio_text="å•†åŠ¡åˆä½œ vxï¼šMia_Studio88",
                    visible_metadata={"location": "ä¸Šæµ·"},
                    source_type="seed",
                    source_from=None,
                    crawl_status="success",
                    crawl_error=None,
                )
            ],
            contact_leads=[
                ContactLead(
                    account_id="user-001",
                    lead_type="wechat",
                    normalized_value="mia_studio88",
                    raw_snippet="vxï¼šMia_Studio88",
                    confidence=0.98,
                    extractor_name="wechat_regex",
                    source_field="bio",
                    dedupe_key="wechat:mia_studio88",
                )
            ],
            run_report=RunReport(
                seed_url=config.seed_url,
                attempted_accounts=1,
                succeeded_accounts=1,
                failed_accounts=0,
                lead_counts={"wechat": 1},
                errors=[],
            ),
        )

    monkeypatch.setattr("red_crawler.cli.run_crawl_seed", fake_run_crawl_seed)

    exit_code = main(
        [
            "crawl-seed",
            "--seed-url",
            "https://www.xiaohongshu.com/user/profile/user-001",
            "--storage-state",
            "state.json",
            "--safe-mode",
            "--interaction-mode",
            "os-mouse",
            "--cache-dir",
            str(tmp_path / "cache"),
            "--gender-filter",
            "女",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "accounts.csv").exists()
    assert (tmp_path / "contact_leads.csv").exists()
    assert (tmp_path / "run_report.json").exists()

    with (tmp_path / "accounts.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))

    assert rows[0]["nickname"] == "Miaç©¿æ­æ‰‹è®°"
    assert report["succeeded_accounts"] == 1


def test_cli_login_saves_storage_state(tmp_path, monkeypatch):
    captured = {}

    def fake_save_login_storage_state(output_path, login_url):
        captured["output_path"] = output_path
        captured["login_url"] = login_url

    monkeypatch.setattr(
        "red_crawler.cli.save_login_storage_state", fake_save_login_storage_state
    )

    exit_code = main(
        [
            "login",
            "--save-state",
            str(tmp_path / "state.json"),
        ]
    )

    assert exit_code == 0
    assert captured == {
        "output_path": tmp_path / "state.json",
        "login_url": "https://www.xiaohongshu.com",
    }


def test_cli_open_uses_existing_storage_state(monkeypatch):
    captured = {}

    def fake_open_xiaohongshu(storage_state, open_url):
        captured["storage_state"] = storage_state
        captured["open_url"] = open_url

    monkeypatch.setattr("red_crawler.cli.open_xiaohongshu", fake_open_xiaohongshu)

    exit_code = main(
        [
            "open",
            "--storage-state",
            "./state.json",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "storage_state": "./state.json",
        "open_url": "https://www.xiaohongshu.com",
    }


def test_cli_crawl_seed_persists_result_to_database(tmp_path, monkeypatch):
    captured = {}

    def fake_run_crawl_seed(config):
        captured["interaction_mode"] = config.interaction_mode
        return CrawlResult(
            accounts=[],
            contact_leads=[],
            run_report=RunReport(
                seed_url="https://www.xiaohongshu.com/user/profile/user-001",
                attempted_accounts=0,
                succeeded_accounts=0,
                failed_accounts=0,
                lead_counts={},
                errors=[],
            ),
        )

    class FakeStore:
        def __init__(self, db_path):
            captured["db_path"] = db_path

        def record_crawl_result(self, result, run_type, safe_mode, started_at):
            captured["run_type"] = run_type
            captured["safe_mode"] = safe_mode
            captured["seed_url"] = result.run_report.seed_url
            captured["started_at"] = started_at
            return 1

    monkeypatch.setattr("red_crawler.cli.run_crawl_seed", fake_run_crawl_seed)
    monkeypatch.setattr("red_crawler.cli.CrawlerStore", FakeStore)

    exit_code = main(
        [
            "crawl-seed",
            "--seed-url",
            "https://www.xiaohongshu.com/user/profile/user-001",
            "--storage-state",
            "state.json",
            "--db-path",
            str(tmp_path / "red-crawler.db"),
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert captured["db_path"] == tmp_path / "red-crawler.db"
    assert captured["run_type"] == "crawl_seed"
    assert captured["safe_mode"] is True
    assert captured["interaction_mode"] == "playwright"
    assert captured["seed_url"] == "https://www.xiaohongshu.com/user/profile/user-001"


def test_cli_crawl_seed_can_disable_safe_mode(tmp_path, monkeypatch):
    captured = {}

    def fake_run_crawl_seed(config):
        captured["interaction_mode"] = config.interaction_mode
        return CrawlResult(
            accounts=[],
            contact_leads=[],
            run_report=RunReport(
                seed_url="https://www.xiaohongshu.com/user/profile/user-001",
                attempted_accounts=0,
                succeeded_accounts=0,
                failed_accounts=0,
                lead_counts={},
                errors=[],
            ),
        )

    class FakeStore:
        def __init__(self, db_path):
            captured["db_path"] = db_path

        def record_crawl_result(self, result, run_type, safe_mode, started_at):
            captured["run_type"] = run_type
            captured["safe_mode"] = safe_mode
            captured["seed_url"] = result.run_report.seed_url
            captured["started_at"] = started_at
            return 1

    monkeypatch.setattr("red_crawler.cli.run_crawl_seed", fake_run_crawl_seed)
    monkeypatch.setattr("red_crawler.cli.CrawlerStore", FakeStore)

    exit_code = main(
        [
            "crawl-seed",
            "--seed-url",
            "https://www.xiaohongshu.com/user/profile/user-001",
            "--storage-state",
            "state.json",
            "--no-safe-mode",
            "--interaction-mode",
            "os-mouse",
            "--db-path",
            str(tmp_path / "red-crawler.db"),
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert captured["safe_mode"] is False
    assert captured["interaction_mode"] == "os-mouse"
    assert captured["seed_url"] == "https://www.xiaohongshu.com/user/profile/user-001"


def test_cli_crawl_search_exports_and_persists_result(tmp_path, monkeypatch):
    captured = {}

    def fake_run_crawl_search(config):
        captured["search_term"] = config.search_term
        captured["max_accounts"] = config.max_accounts
        captured["search_scroll_rounds"] = config.search_scroll_rounds
        captured["min_followers"] = config.min_followers
        captured["min_relevance_score"] = config.min_relevance_score
        captured["creator_only"] = config.creator_only
        captured["safe_mode"] = config.safe_mode
        captured["interaction_mode"] = config.interaction_mode
        return CrawlResult(
            accounts=[
                AccountRecord(
                    account_id="user-201",
                    profile_url="https://www.xiaohongshu.com/user/profile/user-201",
                    nickname="A",
                    bio_text="抗痘护肤博主 邮箱：a@example.com",
                    visible_metadata={"tags": ["护肤博主"]},
                    source_type="search_result",
                    source_from=None,
                    crawl_status="success",
                    crawl_error=None,
                )
            ],
            contact_leads=[
                ContactLead(
                    account_id="user-201",
                    lead_type="email",
                    normalized_value="a@example.com",
                    raw_snippet="a@example.com",
                    confidence=0.98,
                    extractor_name="email_regex",
                    source_field="bio",
                    dedupe_key="email:a@example.com",
                )
            ],
            run_report=RunReport(
                seed_url="search:抗痘博主",
                attempted_accounts=1,
                succeeded_accounts=1,
                failed_accounts=0,
                lead_counts={"email": 1},
                errors=[],
            ),
        )

    class FakeStore:
        def __init__(self, db_path):
            captured["db_path"] = db_path

        def record_crawl_result(self, result, run_type, safe_mode, started_at):
            captured["run_type"] = run_type
            captured["persist_safe_mode"] = safe_mode
            captured["seed_url"] = result.run_report.seed_url
            captured["started_at"] = started_at
            return 1

    monkeypatch.setattr("red_crawler.cli.run_crawl_search", fake_run_crawl_search)
    monkeypatch.setattr("red_crawler.cli.CrawlerStore", FakeStore)

    exit_code = main(
        [
            "crawl-search",
            "--search-term",
            "抗痘博主",
            "--storage-state",
            "state.json",
            "--max-accounts",
            "8",
            "--search-scroll-rounds",
            "6",
            "--min-followers",
            "5000",
            "--min-relevance-score",
            "0.7",
            "--creator-only",
            "--interaction-mode",
            "os-mouse",
            "--db-path",
            str(tmp_path / "red-crawler.db"),
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert captured["search_term"] == "抗痘博主"
    assert captured["max_accounts"] == 8
    assert captured["search_scroll_rounds"] == 6
    assert captured["min_followers"] == 5000
    assert captured["min_relevance_score"] == 0.7
    assert captured["creator_only"] is True
    assert captured["safe_mode"] is True
    assert captured["interaction_mode"] == "os-mouse"
    assert captured["db_path"] == tmp_path / "red-crawler.db"
    assert captured["run_type"] == "crawl_search"
    assert captured["persist_safe_mode"] is True
    assert captured["seed_url"] == "search:抗痘博主"
    assert (tmp_path / "accounts.csv").exists()
    assert (tmp_path / "contact_leads.csv").exists()
    assert (tmp_path / "run_report.json").exists()


def test_cli_crawl_search_passes_bright_data_browser_config(tmp_path, monkeypatch):
    captured = {}

    def fake_run_crawl_search(config):
        captured["browser_mode"] = config.browser_mode
        captured["browser_endpoint"] = config.browser_endpoint
        captured["browser_auth"] = config.browser_auth
        return CrawlResult(
            accounts=[],
            contact_leads=[],
            run_report=RunReport(
                seed_url="search:抗痘博主",
                attempted_accounts=0,
                succeeded_accounts=0,
                failed_accounts=0,
                lead_counts={},
                errors=[],
            ),
        )

    class FakeStore:
        def __init__(self, _db_path):
            pass

        def record_crawl_result(self, result, run_type, safe_mode, started_at):
            return 1

    monkeypatch.setattr("red_crawler.cli.run_crawl_search", fake_run_crawl_search)
    monkeypatch.setattr("red_crawler.cli.CrawlerStore", FakeStore)

    exit_code = main(
        [
            "crawl-search",
            "--search-term",
            "抗痘博主",
            "--storage-state",
            "state.json",
            "--browser-mode",
            "bright-data",
            "--browser-auth",
            "user:pass",
            "--browser-endpoint",
            "wss://user:pass@brd.superproxy.io:9222",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert captured == {
        "browser_mode": "bright-data",
        "browser_endpoint": "wss://user:pass@brd.superproxy.io:9222",
        "browser_auth": "user:pass",
    }


def test_cli_crawl_homefeed_does_not_require_storage_state(tmp_path, monkeypatch):
    captured = {}

    def fake_run_crawl_homefeed(config):
        captured["homefeed_url"] = config.homefeed_url
        captured["storage_state"] = config.storage_state
        captured["max_accounts"] = config.max_accounts
        return CrawlResult(
            accounts=[],
            contact_leads=[],
            run_report=RunReport(
                seed_url=f"homefeed:{config.homefeed_url}",
                attempted_accounts=0,
                succeeded_accounts=0,
                failed_accounts=0,
                lead_counts={},
                errors=[],
            ),
        )

    class FakeStore:
        def __init__(self, db_path):
            captured["db_path"] = db_path

        def record_crawl_result(self, result, run_type, safe_mode, started_at):
            captured["run_type"] = run_type
            captured["safe_mode"] = safe_mode
            return 1

    monkeypatch.setattr("red_crawler.cli.run_crawl_homefeed", fake_run_crawl_homefeed)
    monkeypatch.setattr("red_crawler.cli.CrawlerStore", FakeStore)

    exit_code = main(
        [
            "crawl-homefeed",
            "--max-accounts",
            "8",
            "--db-path",
            str(tmp_path / "red-crawler.db"),
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert captured["homefeed_url"] == (
        "https://www.xiaohongshu.com/explore?channel_id=homefeed.cosmetics_v3"
    )
    assert captured["storage_state"] == ""
    assert captured["max_accounts"] == 8
    assert captured["db_path"] == tmp_path / "red-crawler.db"
    assert captured["run_type"] == "crawl_homefeed"
    assert captured["safe_mode"] is True


def test_cli_collect_nightly_runs_worker(tmp_path, monkeypatch):
    captured = {}

    def fake_run_nightly_collection(config):
        captured["storage_state"] = config.storage_state
        captured["db_path"] = config.db_path
        captured["report_dir"] = config.report_dir
        captured["crawl_budget"] = config.crawl_budget
        captured["daily_account_budget"] = config.daily_account_budget
        captured["daily_search_term_budget"] = config.daily_search_term_budget
        captured["startup_jitter_minutes"] = config.startup_jitter_minutes
        captured["slot_name"] = config.slot_name
        captured["homefeed_url"] = config.homefeed_url
        captured["interaction_mode"] = config.interaction_mode
        return object()

    monkeypatch.setattr("red_crawler.cli.run_nightly_collection", fake_run_nightly_collection)

    exit_code = main(
        [
            "collect-nightly",
            "--storage-state",
            "state.json",
            "--db-path",
            str(tmp_path / "red-crawler.db"),
            "--report-dir",
            str(tmp_path / "reports"),
            "--crawl-budget",
            "30",
            "--daily-account-budget",
            "14",
            "--daily-search-term-budget",
            "3",
            "--startup-jitter-minutes",
            "25",
            "--slot-name",
            "morning",
            "--interaction-mode",
            "os-mouse",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "storage_state": "state.json",
        "db_path": str(tmp_path / "red-crawler.db"),
        "report_dir": str(tmp_path / "reports"),
        "crawl_budget": 30,
        "daily_account_budget": 14,
        "daily_search_term_budget": 3,
        "startup_jitter_minutes": 25,
        "slot_name": "morning",
        "homefeed_url": "https://www.xiaohongshu.com/explore?channel_id=homefeed.cosmetics_v3",
        "interaction_mode": "os-mouse",
    }


def test_cli_crawl_discover_runs_worker_without_seed_url(tmp_path, monkeypatch):
    captured = {}

    def fake_run_nightly_collection(config):
        captured["storage_state"] = config.storage_state
        captured["db_path"] = config.db_path
        captured["report_dir"] = config.report_dir
        captured["crawl_budget"] = config.crawl_budget
        captured["search_term_limit"] = config.search_term_limit
        captured["homefeed_url"] = config.homefeed_url
        captured["interaction_mode"] = config.interaction_mode
        return object()

    monkeypatch.setattr("red_crawler.cli.run_nightly_collection", fake_run_nightly_collection)

    exit_code = main(
        [
            "crawl-discover",
            "--storage-state",
            "state.json",
            "--db-path",
            str(tmp_path / "red-crawler.db"),
            "--report-dir",
            str(tmp_path / "reports"),
            "--crawl-budget",
            "6",
            "--search-term-limit",
            "1",
            "--interaction-mode",
            "os-mouse",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "storage_state": "state.json",
        "db_path": str(tmp_path / "red-crawler.db"),
        "report_dir": str(tmp_path / "reports"),
        "crawl_budget": 6,
        "search_term_limit": 1,
        "homefeed_url": "https://www.xiaohongshu.com/explore?channel_id=homefeed.cosmetics_v3",
        "interaction_mode": "os-mouse",
    }


def test_cli_report_weekly_writes_growth_report(tmp_path, monkeypatch):
    captured = {}

    class FakeStore:
        def __init__(self, db_path):
            captured["db_path"] = db_path

    def fake_write_weekly_reports(store, report_dir, now, days):
        captured["store"] = store
        captured["report_dir"] = report_dir
        captured["days"] = days

    monkeypatch.setattr("red_crawler.cli.CrawlerStore", FakeStore)
    monkeypatch.setattr("red_crawler.cli.write_weekly_reports", fake_write_weekly_reports)

    exit_code = main(
        [
            "report-weekly",
            "--db-path",
            str(tmp_path / "red-crawler.db"),
            "--report-dir",
            str(tmp_path / "reports"),
            "--days",
            "14",
        ]
    )

    assert exit_code == 0
    assert captured["db_path"] == tmp_path / "red-crawler.db"
    assert captured["report_dir"] == tmp_path / "reports"
    assert captured["days"] == 14


def test_cli_list_contactable_prints_table(monkeypatch, capsys):
    class FakeStore:
        def __init__(self, db_path):
            self.db_path = db_path

        def list_contactable_creators(
            self,
            *,
            lead_type,
            creator_segment,
            min_relevance_score,
            limit,
        ):
            assert lead_type == "email"
            assert creator_segment == "creator"
            assert min_relevance_score == 0.7
            assert limit == 5
            return [
                ContactableCreator(
                    account_id="user-101",
                    profile_url="https://www.xiaohongshu.com/user/profile/user-101",
                    nickname="Mia",
                    bio_text="æŠ—ç—˜æŠ¤è‚¤åšä¸»",
                    creator_segment="creator",
                    relevance_score=0.88,
                    email="mia@example.com",
                    email_confidence=0.95,
                    lead_count=2,
                    first_email_seen_at="2026-03-29T01:00:00+00:00",
                    last_seen_at="2026-03-29T01:00:00+00:00",
                )
            ]

    monkeypatch.setattr("red_crawler.cli.CrawlerStore", FakeStore)

    exit_code = main(
        [
            "list-contactable",
            "--db-path",
            "./data/red-crawler.db",
            "--min-relevance-score",
            "0.7",
            "--limit",
            "5",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "user-101" in output
    assert "mia@example.com" in output
