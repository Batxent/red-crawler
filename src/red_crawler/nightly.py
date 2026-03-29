from __future__ import annotations

import csv
import json
import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from red_crawler.crawl.profile import parse_profile_html
from red_crawler.crawl.similar import (
    SEARCH_QUERY_GROUPS,
    TOPIC_QUERY_HINTS,
    build_search_queries,
    classify_creator_segment,
    extract_search_result_profiles,
    score_creator_relevance,
)
from red_crawler.extract.contacts import extract_contact_leads
from red_crawler.models import AccountRecord, ContactLead
from red_crawler.session import BrowserSession, PlaywrightCrawlerClient, RiskControlTriggered
from red_crawler.store import CrawlerStore, WeeklyGrowthReport


DEFAULT_BEAUTY_SEARCH_TERMS = tuple(
    list(SEARCH_QUERY_GROUPS["beauty"])
    + [query for _, query in TOPIC_QUERY_HINTS if query not in SEARCH_QUERY_GROUPS["beauty"]]
)


class NightlyClient(Protocol):
    def fetch_profile_html(self, profile_url: str) -> str: ...

    def fetch_search_result_htmls(self, query: str) -> list[str]: ...

    def fetch_note_recommendation_html(self, profile_url: str) -> list[str]: ...


def _ensure_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _beauty_seed_payload(query: str) -> dict[str, object]:
    return {
        "bio_text": query,
        "visible_metadata": {"tags": [query]},
    }


def _allowed_promoted_terms(account: AccountRecord) -> list[str]:
    allowed = set(DEFAULT_BEAUTY_SEARCH_TERMS)
    payload = {
        "nickname": account.nickname,
        "bio_text": account.bio_text,
        "visible_metadata": account.visible_metadata,
    }
    terms = []
    for term in build_search_queries(payload):
        if term in allowed and term not in terms:
            terms.append(term)
    return terms


def should_promote_seed(
    account: AccountRecord,
    leads: list[ContactLead],
    *,
    min_relevance_score: float,
) -> bool:
    return (
        account.creator_segment == "creator"
        and account.relevance_score >= min_relevance_score
        and any(lead.lead_type == "email" for lead in leads)
    )


@dataclass
class NightlyCollectConfig:
    storage_state: str
    db_path: str
    report_dir: str
    cache_dir: str
    crawl_budget: int = 30
    search_term_limit: int = 4
    safe_mode: bool = True
    cache_ttl_days: int = 7
    refresh_after_days: int = 14
    min_relevance_score: float = 0.7
    promotion_threshold: float = 0.75
    startup_jitter_minutes: int = 0
    slot_name: str = ""


@dataclass
class NightlyCollectResult:
    run_id: int
    generated_at: str
    crawl_budget: int
    queued_candidates: int
    processed_accounts: int
    new_contactable_creators: int
    new_email_leads: int
    promoted_seeds: int
    processed_search_terms: list[str]
    top_search_terms: list[dict[str, int | str]]
    aborted: bool
    abort_reason: str | None
    slot_name: str = ""
    startup_delay_seconds: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def write_daily_report(result: NightlyCollectResult, report_dir: str | Path) -> Path:
    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
    latest_path = output_dir / "daily-run-report.json"
    latest_path.write_text(payload, encoding="utf-8")

    generated = datetime.fromisoformat(result.generated_at)
    timestamp = generated.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slot_suffix = f"-{result.slot_name}" if result.slot_name else ""
    snapshot_path = output_dir / f"daily-run-report-{timestamp}{slot_suffix}.json"
    snapshot_path.write_text(payload, encoding="utf-8")
    return latest_path


def apply_startup_jitter(
    config: NightlyCollectConfig,
    *,
    sleep_fn: Callable[[float], None],
    rng: random.Random | object,
    log_fn: Callable[[str], None],
) -> float:
    if config.startup_jitter_minutes <= 0:
        return 0.0
    max_delay_seconds = max(config.startup_jitter_minutes, 0) * 60
    delay = float(rng.uniform(0, max_delay_seconds))
    log_fn(f"nightly: delaying start by {delay:.1f}s to randomize the run window")
    sleep_fn(delay)
    return delay


def write_weekly_reports(
    store: CrawlerStore,
    *,
    report_dir: str | Path,
    now: datetime | None = None,
    days: int = 7,
) -> WeeklyGrowthReport:
    output_dir = Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = store.build_weekly_growth_report(days=days, now=now)
    (output_dir / "weekly-growth-report.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    creators = store.list_contactable_creators(limit=500)
    with (output_dir / "contactable_creators.csv").open(
        "w", newline="", encoding="utf-8"
    ) as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "account_id",
                "profile_url",
                "nickname",
                "bio_text",
                "creator_segment",
                "relevance_score",
                "email",
                "email_confidence",
                "lead_count",
                "first_email_seen_at",
                "last_seen_at",
            ],
        )
        writer.writeheader()
        writer.writerows(creator.to_row() for creator in creators)

    return report


def collect_nightly_with_client(
    config: NightlyCollectConfig,
    client: NightlyClient,
    *,
    store: CrawlerStore | None = None,
    now_fn: Callable[[], datetime] | None = None,
    rng: random.Random | object | None = None,
) -> NightlyCollectResult:
    store = store or CrawlerStore(config.db_path)
    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    rng = rng or random.Random()
    started_at = _ensure_utc(now_fn())
    store.seed_default_search_terms(now=started_at)

    run_id = store.start_run(
        run_type="collect_nightly",
        safe_mode=config.safe_mode,
        crawl_budget=config.crawl_budget,
        started_at=started_at,
    )

    queued_candidates = 0
    processed_accounts = 0
    new_contactable_creators = 0
    new_email_leads = 0
    promoted_seeds = 0
    errors: list[dict[str, str]] = []
    aborted = False
    abort_reason: str | None = None
    processed_search_terms = store.select_search_terms(
        limit=config.search_term_limit,
        now=started_at,
    )
    if processed_search_terms:
        rng.shuffle(processed_search_terms)
    term_metrics = {
        term: {"candidate_count": 0, "new_contactable_count": 0}
        for term in processed_search_terms
    }

    for term in processed_search_terms:
        try:
            html_snapshots = client.fetch_search_result_htmls(term)
        except RiskControlTriggered as exc:
            aborted = True
            abort_reason = str(exc)
            errors.append({"source": term, "error": str(exc)})
            break

        candidates = []
        for html in html_snapshots:
            candidates.extend(extract_search_result_profiles(html=html, max_results=100))
        for index, candidate in enumerate(candidates):
            candidate["priority"] = round(max(0.2, 1.0 - index * 0.05), 2)
        term_metrics[term]["candidate_count"] = len(candidates)
        queued_candidates += store.enqueue_discovery_candidates(
            candidates,
            source_type="search_result",
            source_seed_account_id="",
            search_term=term,
            now=started_at,
        )

    if not aborted:
        queued_candidates += store.enqueue_refresh_candidates(
            limit=max(config.crawl_budget - queued_candidates, 0),
            now=started_at,
            refresh_after_days=config.refresh_after_days,
        )

    while not aborted and processed_accounts < config.crawl_budget:
        items = store.dequeue_discovery_candidates(limit=1, now=started_at)
        if not items:
            break
        item = items[0]
        store.mark_queue_item_processing(item.id)

        try:
            html = client.fetch_profile_html(item.profile_url)
        except RiskControlTriggered as exc:
            aborted = True
            abort_reason = str(exc)
            store.mark_queue_item_failed(
                item.id,
                error=str(exc),
                now=started_at,
                retry_after_hours=12,
            )
            errors.append({"source": item.profile_url, "error": str(exc)})
            break
        except Exception as exc:  # pragma: no cover - defensive
            store.mark_queue_item_failed(item.id, error=str(exc), now=started_at)
            errors.append({"source": item.profile_url, "error": str(exc)})
            continue

        try:
            account = parse_profile_html(
                html=html,
                profile_url=item.profile_url,
                source_type=item.source_type,
                source_from=item.source_seed_account_id or None,
            )
        except Exception as exc:
            store.mark_queue_item_failed(item.id, error=str(exc), now=started_at)
            errors.append({"source": item.profile_url, "error": str(exc)})
            continue

        processed_accounts += 1
        account.discovery_depth = 1 if item.source_type != "refresh" else 0
        payload = {
            "nickname": account.nickname,
            "bio_text": account.bio_text,
            "visible_metadata": account.visible_metadata,
        }
        account.creator_segment = classify_creator_segment(payload)
        query = item.search_term or DEFAULT_BEAUTY_SEARCH_TERMS[0]
        account.relevance_score = score_creator_relevance(
            _beauty_seed_payload(query),
            payload,
        )
        if account.relevance_score < config.min_relevance_score:
            store.mark_queue_item_filtered(
                item.id,
                error=f"low_relevance:{account.relevance_score:.2f}",
                now=started_at,
            )
            continue

        leads = extract_contact_leads(account.account_id, account.bio_text)
        outcome = store.persist_account_snapshot(
            run_id=run_id,
            account=account,
            leads=leads,
            observed_at=started_at,
        )
        store.mark_queue_item_done(item.id, account_id=account.account_id, now=started_at)

        new_contactable_creators += int(outcome.new_contactable_creator)
        new_email_leads += outcome.new_email_leads
        if item.search_term and outcome.new_contactable_creator:
            term_metrics.setdefault(
                item.search_term,
                {"candidate_count": 0, "new_contactable_count": 0},
            )
            term_metrics[item.search_term]["new_contactable_count"] += 1

        if should_promote_seed(
            account,
            leads,
            min_relevance_score=config.promotion_threshold,
        ):
            promoted = store.upsert_seed_account(
                account.account_id,
                seed_kind="promoted_seed",
                now=started_at,
                productive=True,
            )
            promoted_seeds += int(promoted)
            store.upsert_search_terms(
                _allowed_promoted_terms(account),
                source_type="creator",
                source_value=account.account_id,
                now=started_at,
            )

    for term, metrics in term_metrics.items():
        store.record_search_term_outcome(
            term,
            candidate_count=int(metrics["candidate_count"]),
            new_contactable_count=int(metrics["new_contactable_count"]),
            now=started_at,
            run_id=run_id,
        )

    lead_counts = {"email": new_email_leads} if new_email_leads else {}
    store.finalize_run(
        run_id,
        attempted_accounts=processed_accounts,
        succeeded_accounts=processed_accounts,
        failed_accounts=0,
        lead_counts=lead_counts,
        errors=errors,
        aborted=aborted,
        abort_reason=abort_reason,
        queued_candidates=queued_candidates,
        processed_search_terms=processed_search_terms,
        new_contactable_creators=new_contactable_creators,
        promoted_seeds=promoted_seeds,
        finished_at=started_at,
    )

    top_search_terms = sorted(
        (
            {
                "term": term,
                "candidate_count": int(metrics["candidate_count"]),
                "new_contactable_count": int(metrics["new_contactable_count"]),
            }
            for term, metrics in term_metrics.items()
        ),
        key=lambda item: (
            -int(item["new_contactable_count"]),
            -int(item["candidate_count"]),
            str(item["term"]),
        ),
    )[:5]

    result = NightlyCollectResult(
        run_id=run_id,
        generated_at=started_at.isoformat(),
        crawl_budget=config.crawl_budget,
        queued_candidates=queued_candidates,
        processed_accounts=processed_accounts,
        new_contactable_creators=new_contactable_creators,
        new_email_leads=new_email_leads,
        promoted_seeds=promoted_seeds,
        processed_search_terms=list(processed_search_terms),
        top_search_terms=top_search_terms,
        aborted=aborted,
        abort_reason=abort_reason,
        slot_name=config.slot_name,
    )
    write_daily_report(result, config.report_dir)
    return result


def run_nightly_collection(config: NightlyCollectConfig) -> NightlyCollectResult:
    jitter_rng = random.Random()
    startup_delay = apply_startup_jitter(
        config,
        sleep_fn=time.sleep,
        rng=jitter_rng,
        log_fn=print,
    )
    store = CrawlerStore(config.db_path)
    with BrowserSession(config.storage_state) as session:
        client = PlaywrightCrawlerClient(
            session,
            safe_mode=config.safe_mode,
            cache_dir=config.cache_dir,
            cache_ttl_days=config.cache_ttl_days,
        )
        result = collect_nightly_with_client(config, client, store=store)
        result.startup_delay_seconds = startup_delay
        write_daily_report(result, config.report_dir)
        return result
