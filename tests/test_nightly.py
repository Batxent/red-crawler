import csv
import json
import sqlite3
from datetime import datetime, timezone

from red_crawler.models import AccountRecord, ContactLead, CrawlResult, RunReport
from red_crawler.nightly import (
    NightlyCollectConfig,
    apply_startup_jitter,
    collect_nightly_with_client,
    should_promote_seed,
    write_weekly_reports,
)
from red_crawler.session import RiskControlTriggered
from red_crawler.store import CrawlerStore


class FakeNightlyClient:
    def __init__(self, *, pages, search_pages, risky_profile_url=None):
        self.pages = pages
        self.search_pages = search_pages
        self.risky_profile_url = risky_profile_url
        self.search_queries = []

    def fetch_search_result_htmls(self, query):
        self.search_queries.append(query)
        payload = self.search_pages.get(query, [])
        if isinstance(payload, str):
            return [payload]
        return payload

    def fetch_profile_html(self, profile_url):
        if profile_url == self.risky_profile_url:
            raise RiskControlTriggered("risk control threshold reached")
        return self.pages[profile_url]

    def fetch_note_recommendation_html(self, profile_url):
        return []


class ReverseShuffle:
    def shuffle(self, values):
        values[:] = list(reversed(values))


def test_should_promote_seed_requires_creator_high_relevance_and_email():
    account = AccountRecord(
        account_id="user-101",
        profile_url="https://www.xiaohongshu.com/user/profile/user-101",
        nickname="Mia",
        bio_text="抗痘护肤博主",
        visible_metadata={"tags": ["美妆博主"]},
        source_type="search_result",
        source_from=None,
        crawl_status="success",
        crawl_error=None,
        creator_segment="creator",
        relevance_score=0.82,
    )
    email_lead = ContactLead(
        account_id="user-101",
        lead_type="email",
        normalized_value="mia@example.com",
        raw_snippet="mia@example.com",
        confidence=0.95,
        extractor_name="email_regex",
        source_field="bio",
        dedupe_key="email:mia@example.com",
    )

    assert should_promote_seed(account, [email_lead], min_relevance_score=0.75) is True

    account.creator_segment = "studio"
    assert should_promote_seed(account, [email_lead], min_relevance_score=0.75) is False

    account.creator_segment = "creator"
    account.relevance_score = 0.61
    assert should_promote_seed(account, [email_lead], min_relevance_score=0.75) is False
    assert should_promote_seed(account, [], min_relevance_score=0.75) is False


def test_apply_startup_jitter_sleeps_up_to_configured_minutes():
    sleeps = []
    logs = []

    class FixedRandom:
        def uniform(self, start, end):
            assert (start, end) == (0, 1800)
            return 742.0

    delay = apply_startup_jitter(
        NightlyCollectConfig(
            storage_state="state.json",
            db_path="db.sqlite3",
            report_dir="reports",
            cache_dir=".cache/red-crawler",
            startup_jitter_minutes=30,
        ),
        sleep_fn=sleeps.append,
        rng=FixedRandom(),
        log_fn=logs.append,
    )

    assert delay == 742.0
    assert sleeps == [742.0]
    assert logs == ["nightly: delaying start by 742.0s to randomize the run window"]


def test_collect_nightly_bootstraps_promotes_seed_and_writes_daily_report(tmp_path):
    db_path = tmp_path / "red-crawler.db"
    report_dir = tmp_path / "reports"
    store = CrawlerStore(db_path)
    client = FakeNightlyClient(
        search_pages={
            "美妆博主": [
                """
                <div class="note-item">
                  <div class="footer">
                    <div class="card-bottom-wrapper">
                      <a class="author" href="/user/profile/user-101?xsec_source=pc_search">Mia</a>
                    </div>
                  </div>
                </div>
                """
            ]
        },
        pages={
            "https://www.xiaohongshu.com/user/profile/user-101?xsec_source=pc_search": """
            <section class="profile">
              <div class="user-id">账号ID: user-101</div>
              <h1 class="user-name">Mia</h1>
              <div class="user-bio">抗痘护肤博主 商务邮箱：mia@example.com</div>
              <div class="user-tags"><span>美妆博主</span><span>护肤博主</span></div>
              <div class="user-followers">粉丝 2.6万</div>
            </section>
            """,
        },
    )
    config = NightlyCollectConfig(
        storage_state="state.json",
        db_path=str(db_path),
        report_dir=str(report_dir),
        cache_dir=str(tmp_path / "cache"),
        crawl_budget=3,
        search_term_limit=1,
    )

    result = collect_nightly_with_client(
        config,
        client,
        store=store,
        now_fn=lambda: datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc),
    )

    assert result.processed_accounts == 1
    assert result.new_contactable_creators == 1
    assert result.promoted_seeds == 1
    assert (report_dir / "daily-run-report.json").exists()

    with sqlite3.connect(db_path) as conn:
        seed_row = conn.execute(
            "select seed_kind from seed_pool where account_id = 'user-101'"
        ).fetchone()
        derived_terms = {
            row[0]
            for row in conn.execute(
                "select term from search_terms where source_value = 'user-101'"
            )
        }

    assert seed_row == ("promoted_seed",)
    assert "抗痘博主" in derived_terms
    assert len(list(report_dir.glob("daily-run-report-*.json"))) == 1


def test_collect_nightly_randomizes_search_term_order(tmp_path):
    db_path = tmp_path / "red-crawler.db"
    store = CrawlerStore(db_path)
    client = FakeNightlyClient(
        search_pages={
            "美妆博主": [""],
            "护肤博主": [""],
        },
        pages={},
    )
    config = NightlyCollectConfig(
        storage_state="state.json",
        db_path=str(db_path),
        report_dir=str(tmp_path / "reports"),
        cache_dir=str(tmp_path / "cache"),
        crawl_budget=1,
        search_term_limit=2,
    )

    collect_nightly_with_client(
        config,
        client,
        store=store,
        now_fn=lambda: datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc),
        rng=ReverseShuffle(),
    )

    assert client.search_queries[:2] == ["护肤博主", "美妆博主"]


def test_collect_nightly_stops_after_crawl_budget_and_leaves_pending_queue(tmp_path):
    db_path = tmp_path / "red-crawler.db"
    store = CrawlerStore(db_path)
    client = FakeNightlyClient(
        search_pages={
            "美妆博主": [
                """
                <div class="note-item"><div class="footer"><div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-101?xsec_source=pc_search">A</a>
                  <a class="author" href="/user/profile/user-102?xsec_source=pc_search">B</a>
                  <a class="author" href="/user/profile/user-103?xsec_source=pc_search">C</a>
                </div></div></div>
                """
            ]
        },
        pages={
            "https://www.xiaohongshu.com/user/profile/user-101?xsec_source=pc_search": """
            <section class="profile"><div class="user-id">账号ID: user-101</div><h1 class="user-name">A</h1>
            <div class="user-bio">美妆博主 a@example.com</div><div class="user-tags"><span>美妆博主</span></div>
            <div class="user-followers">粉丝 1.8万</div></section>
            """,
            "https://www.xiaohongshu.com/user/profile/user-102?xsec_source=pc_search": """
            <section class="profile"><div class="user-id">账号ID: user-102</div><h1 class="user-name">B</h1>
            <div class="user-bio">护肤博主 b@example.com</div><div class="user-tags"><span>护肤博主</span></div>
            <div class="user-followers">粉丝 2.1万</div></section>
            """,
            "https://www.xiaohongshu.com/user/profile/user-103?xsec_source=pc_search": """
            <section class="profile"><div class="user-id">账号ID: user-103</div><h1 class="user-name">C</h1>
            <div class="user-bio">彩妆博主 c@example.com</div><div class="user-tags"><span>彩妆博主</span></div>
            <div class="user-followers">粉丝 2.9万</div></section>
            """,
        },
    )
    config = NightlyCollectConfig(
        storage_state="state.json",
        db_path=str(db_path),
        report_dir=str(tmp_path / "reports"),
        cache_dir=str(tmp_path / "cache"),
        crawl_budget=2,
        search_term_limit=1,
    )

    result = collect_nightly_with_client(
        config,
        client,
        store=store,
        now_fn=lambda: datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc),
    )

    assert result.processed_accounts == 2

    with sqlite3.connect(db_path) as conn:
        pending_count = conn.execute(
            "select count(*) from discovery_queue where status = 'pending'"
        ).fetchone()[0]

    assert pending_count == 1


def test_collect_nightly_aborts_on_risk_and_preserves_pending_queue(tmp_path):
    db_path = tmp_path / "red-crawler.db"
    store = CrawlerStore(db_path)
    risky_url = "https://www.xiaohongshu.com/user/profile/user-102?xsec_source=pc_search"
    client = FakeNightlyClient(
        risky_profile_url=risky_url,
        search_pages={
            "美妆博主": [
                """
                <div class="note-item"><div class="footer"><div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-101?xsec_source=pc_search">A</a>
                  <a class="author" href="/user/profile/user-102?xsec_source=pc_search">B</a>
                </div></div></div>
                """
            ]
        },
        pages={
            "https://www.xiaohongshu.com/user/profile/user-101?xsec_source=pc_search": """
            <section class="profile"><div class="user-id">账号ID: user-101</div><h1 class="user-name">A</h1>
            <div class="user-bio">美妆博主 a@example.com</div><div class="user-tags"><span>美妆博主</span></div>
            <div class="user-followers">粉丝 1.8万</div></section>
            """,
        },
    )
    config = NightlyCollectConfig(
        storage_state="state.json",
        db_path=str(db_path),
        report_dir=str(tmp_path / "reports"),
        cache_dir=str(tmp_path / "cache"),
        crawl_budget=3,
        search_term_limit=1,
    )

    result = collect_nightly_with_client(
        config,
        client,
        store=store,
        now_fn=lambda: datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc),
    )

    assert result.aborted is True
    assert result.abort_reason == "risk control threshold reached"

    with sqlite3.connect(db_path) as conn:
        statuses = {
            row[0]: row[1]
            for row in conn.execute(
                "select account_id, status from discovery_queue order by account_id"
            )
        }

    assert statuses["user-101"] == "done"
    assert statuses["user-102"] == "pending"


def test_write_weekly_reports_exports_growth_json_and_contactable_csv(tmp_path):
    db_path = tmp_path / "red-crawler.db"
    report_dir = tmp_path / "reports"
    store = CrawlerStore(db_path)
    store.record_crawl_result(
        CrawlResult(
            accounts=[
                AccountRecord(
                    account_id="user-101",
                    profile_url="https://www.xiaohongshu.com/user/profile/user-101",
                    nickname="Mia",
                    bio_text="抗痘护肤博主 商务邮箱：mia@example.com",
                    visible_metadata={"tags": ["美妆博主"], "followers": "2.6万"},
                    source_type="seed",
                    source_from=None,
                    crawl_status="success",
                    crawl_error=None,
                    creator_segment="creator",
                    relevance_score=0.88,
                )
            ],
            contact_leads=[
                ContactLead(
                    account_id="user-101",
                    lead_type="email",
                    normalized_value="mia@example.com",
                    raw_snippet="商务邮箱：mia@example.com",
                    confidence=0.95,
                    extractor_name="email_regex",
                    source_field="bio",
                    dedupe_key="email:mia@example.com",
                )
            ],
            run_report=RunReport(
                seed_url="https://www.xiaohongshu.com/user/profile/user-101",
                attempted_accounts=1,
                succeeded_accounts=1,
                failed_accounts=0,
                lead_counts={"email": 1},
                errors=[],
            ),
        ),
        run_type="crawl_seed",
        safe_mode=True,
        started_at=datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc),
    )

    weekly = write_weekly_reports(
        store,
        report_dir=report_dir,
        now=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
    )

    assert weekly.new_contactable_creators == 1
    assert (report_dir / "weekly-growth-report.json").exists()
    assert (report_dir / "contactable_creators.csv").exists()

    report_payload = json.loads(
        (report_dir / "weekly-growth-report.json").read_text(encoding="utf-8")
    )
    with (report_dir / "contactable_creators.csv").open(
        newline="", encoding="utf-8"
    ) as fh:
        rows = list(csv.DictReader(fh))

    assert report_payload["new_contactable_creators"] == 1
    assert rows[0]["account_id"] == "user-101"


def test_write_daily_report_keeps_latest_and_timestamped_copy(tmp_path):
    from red_crawler.nightly import NightlyCollectResult, write_daily_report

    report_dir = tmp_path / "reports"
    result = NightlyCollectResult(
        run_id=7,
        generated_at="2026-03-29T09:40:00+00:00",
        crawl_budget=22,
        queued_candidates=40,
        processed_accounts=18,
        new_contactable_creators=5,
        new_email_leads=5,
        promoted_seeds=5,
        processed_search_terms=["美妆博主"],
        top_search_terms=[{"term": "美妆博主", "candidate_count": 10, "new_contactable_count": 5}],
        aborted=False,
        abort_reason=None,
        slot_name="morning",
        startup_delay_seconds=312.0,
    )

    latest = write_daily_report(result, report_dir)

    assert latest.name == "daily-run-report.json"
    assert (report_dir / "daily-run-report-20260329T094000Z-morning.json").exists()
