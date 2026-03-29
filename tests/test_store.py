import sqlite3
from datetime import datetime, timedelta, timezone

from red_crawler.models import AccountRecord, ContactLead, CrawlResult, RunReport
from red_crawler.store import CrawlerStore


def _build_crawl_result(
    *,
    raw_snippet: str = "邮箱：u2@example.com",
    confidence: float = 0.95,
    include_email: bool = True,
) -> CrawlResult:
    seed = AccountRecord(
        account_id="user-001",
        profile_url="https://www.xiaohongshu.com/user/profile/user-001",
        nickname="Seed",
        bio_text="美妆内容分享",
        visible_metadata={"tags": ["美妆博主"], "followers": "35.1万"},
        source_type="seed",
        source_from=None,
        crawl_status="success",
        crawl_error=None,
        creator_segment="creator",
        relevance_score=1.0,
        discovery_depth=0,
    )
    candidate = AccountRecord(
        account_id="user-002",
        profile_url="https://www.xiaohongshu.com/user/profile/user-002?xsec_source=pc_search",
        nickname="U2",
        bio_text="美妆博主 邮箱：u2@example.com",
        visible_metadata={"tags": ["美妆博主"], "followers": "2.3万"},
        source_type="search_result",
        source_from="user-001",
        crawl_status="success",
        crawl_error=None,
        creator_segment="creator",
        relevance_score=0.84,
        discovery_depth=1,
    )
    leads = []
    if include_email:
        leads.append(
            ContactLead(
                account_id="user-002",
                lead_type="email",
                normalized_value="u2@example.com",
                raw_snippet=raw_snippet,
                confidence=confidence,
                extractor_name="email_regex",
                source_field="bio",
                dedupe_key="email:u2@example.com",
            )
        )

    return CrawlResult(
        accounts=[seed, candidate],
        contact_leads=leads,
        run_report=RunReport(
            seed_url=seed.profile_url,
            attempted_accounts=2,
            succeeded_accounts=2,
            failed_accounts=0,
            lead_counts={"email": len(leads)} if leads else {},
            errors=[],
        ),
    )


def test_store_records_crawl_result_and_lists_contactable_creators(tmp_path):
    db_path = tmp_path / "red-crawler.db"
    store = CrawlerStore(db_path)

    run_id = store.record_crawl_result(
        _build_crawl_result(),
        run_type="crawl_seed",
        safe_mode=True,
        started_at=datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc),
    )

    assert run_id == 1

    creators = store.list_contactable_creators(limit=10)

    assert [creator.account_id for creator in creators] == ["user-002"]
    assert creators[0].email == "u2@example.com"
    assert creators[0].creator_segment == "creator"

    with sqlite3.connect(db_path) as conn:
        edge = conn.execute(
            """
            select from_account_id, to_account_id, edge_type, min_depth, seen_count
            from discovery_edges
            """
        ).fetchone()
        assert edge == ("user-001", "user-002", "search_result", 1, 1)


def test_store_merges_contact_leads_and_preserves_observations(tmp_path):
    db_path = tmp_path / "red-crawler.db"
    store = CrawlerStore(db_path)

    store.record_crawl_result(
        _build_crawl_result(raw_snippet="邮箱：u2@example.com", confidence=0.91),
        run_type="crawl_seed",
        safe_mode=True,
        started_at=datetime(2026, 3, 21, 1, 0, tzinfo=timezone.utc),
    )
    store.record_crawl_result(
        _build_crawl_result(raw_snippet="商务邮箱 u2@example.com", confidence=0.97),
        run_type="crawl_seed",
        safe_mode=True,
        started_at=datetime(2026, 3, 28, 1, 0, tzinfo=timezone.utc),
    )

    with sqlite3.connect(db_path) as conn:
        lead = conn.execute(
            """
            select best_confidence, latest_raw_snippet, first_seen_at, last_seen_at
            from contact_leads
            where account_id = 'user-002' and lead_type = 'email'
            """
        ).fetchone()
        observation_count = conn.execute(
            """
            select count(*)
            from contact_lead_observations
            where account_id = 'user-002' and lead_type = 'email'
            """
        ).fetchone()[0]

    assert lead[0] == 0.97
    assert lead[1] == "商务邮箱 u2@example.com"
    assert lead[2].startswith("2026-03-21")
    assert lead[3].startswith("2026-03-28")
    assert observation_count == 2


def test_store_weekly_growth_counts_first_email_hit_once_per_creator(tmp_path):
    db_path = tmp_path / "red-crawler.db"
    store = CrawlerStore(db_path)

    store.record_crawl_result(
        _build_crawl_result(include_email=False),
        run_type="crawl_seed",
        safe_mode=True,
        started_at=datetime(2026, 3, 20, 1, 0, tzinfo=timezone.utc),
    )
    store.record_crawl_result(
        _build_crawl_result(),
        run_type="crawl_seed",
        safe_mode=True,
        started_at=datetime(2026, 3, 27, 1, 0, tzinfo=timezone.utc),
    )

    report = store.build_weekly_growth_report(
        days=7,
        now=datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
    )

    assert report.new_contactable_creators == 1
    assert report.new_email_leads == 1


def test_store_search_terms_respect_cooldown(tmp_path):
    store = CrawlerStore(tmp_path / "red-crawler.db")
    now = datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc)

    store.seed_default_search_terms(now=now)

    selected = store.select_search_terms(limit=4, now=now)

    assert "美妆博主" in selected

    store.record_search_term_outcome(
        "美妆博主",
        candidate_count=0,
        new_contactable_count=0,
        now=now,
    )

    after_one_day = store.select_search_terms(limit=10, now=now + timedelta(days=1))
    after_four_days = store.select_search_terms(limit=10, now=now + timedelta(days=4))

    assert "美妆博主" not in after_one_day
    assert "美妆博主" in after_four_days


def test_store_dequeues_discovery_queue_by_priority(tmp_path):
    store = CrawlerStore(tmp_path / "red-crawler.db")
    now = datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc)

    store.enqueue_discovery_candidates(
        [
            {
                "profile_url": "https://www.xiaohongshu.com/user/profile/user-low",
                "account_id": "user-low",
                "nickname": "Low",
                "priority": 0.55,
            },
            {
                "profile_url": "https://www.xiaohongshu.com/user/profile/user-high",
                "account_id": "user-high",
                "nickname": "High",
                "priority": 0.91,
            },
        ],
        source_type="search_result",
        source_seed_account_id="",
        search_term="美妆博主",
        now=now,
    )

    items = store.dequeue_discovery_candidates(limit=2, now=now)

    assert [item.account_id for item in items] == ["user-high", "user-low"]
