from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

from red_crawler.crawl.similar import SEARCH_QUERY_GROUPS, TOPIC_QUERY_HINTS
from red_crawler.models import AccountRecord, ContactLead, CrawlResult
from red_crawler.profile_url import canonicalize_profile_url


def _ensure_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _isoformat(value: datetime | None) -> str:
    return _ensure_utc(value).isoformat()


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@dataclass
class ContactableCreator:
    account_id: str
    profile_url: str
    nickname: str
    bio_text: str
    creator_segment: str
    relevance_score: float
    email: str
    email_confidence: float
    lead_count: int
    first_email_seen_at: str
    last_seen_at: str

    def to_row(self) -> dict[str, str]:
        return {
            "account_id": self.account_id,
            "profile_url": self.profile_url,
            "nickname": self.nickname,
            "bio_text": self.bio_text,
            "creator_segment": self.creator_segment,
            "relevance_score": f"{self.relevance_score:.2f}",
            "email": self.email,
            "email_confidence": f"{self.email_confidence:.2f}",
            "lead_count": str(self.lead_count),
            "first_email_seen_at": self.first_email_seen_at,
            "last_seen_at": self.last_seen_at,
        }


@dataclass
class DiscoveryQueueItem:
    id: int
    profile_url: str
    account_id: str
    source_type: str
    source_seed_account_id: str
    search_term: str
    priority: float
    status: str
    attempt_count: int


@dataclass
class PersistOutcome:
    new_contactable_creator: bool
    new_email_leads: int


@dataclass
class WeeklyGrowthReport:
    window_days: int
    generated_at: str
    new_contactable_creators: int
    new_email_leads: int
    new_promoted_seeds: int
    risk_abort_count: int
    top_search_terms: list[dict[str, int | str]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class CollectWindowUsage:
    run_count: int
    attempted_accounts: int
    processed_search_terms: int


class CrawlerStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                create table if not exists crawl_runs (
                    id integer primary key autoincrement,
                    run_type text not null,
                    seed_url text not null default '',
                    safe_mode integer not null default 0,
                    crawl_budget integer,
                    status text not null default 'running',
                    started_at text not null,
                    finished_at text,
                    attempted_accounts integer not null default 0,
                    succeeded_accounts integer not null default 0,
                    failed_accounts integer not null default 0,
                    lead_counts_json text not null default '{}',
                    aborted integer not null default 0,
                    abort_reason text,
                    errors_json text not null default '[]',
                    queued_candidates integer not null default 0,
                    processed_search_terms_json text not null default '[]',
                    new_contactable_creators integer not null default 0,
                    promoted_seeds integer not null default 0
                );

                create table if not exists creator_accounts (
                    account_id text primary key,
                    profile_url text not null,
                    nickname text not null,
                    bio_text text not null,
                    visible_metadata_json text not null,
                    creator_segment text not null,
                    relevance_score real not null default 0,
                    first_seen_at text not null,
                    last_seen_at text not null,
                    last_crawl_status text not null,
                    last_crawl_error text
                );

                create table if not exists account_observations (
                    id integer primary key autoincrement,
                    run_id integer not null references crawl_runs(id) on delete cascade,
                    account_id text not null,
                    profile_url text not null,
                    nickname text not null,
                    bio_text text not null,
                    visible_metadata_json text not null,
                    creator_segment text not null,
                    relevance_score real not null default 0,
                    source_type text not null,
                    source_from text not null default '',
                    crawl_status text not null,
                    crawl_error text,
                    discovery_depth integer not null default 0,
                    observed_at text not null
                );

                create table if not exists contact_leads (
                    id integer primary key autoincrement,
                    account_id text not null,
                    lead_type text not null,
                    normalized_value text not null,
                    source_field text not null,
                    best_confidence real not null,
                    latest_raw_snippet text not null,
                    latest_extractor_name text not null,
                    first_seen_at text not null,
                    last_seen_at text not null,
                    unique(account_id, lead_type, normalized_value)
                );

                create table if not exists contact_lead_observations (
                    id integer primary key autoincrement,
                    run_id integer not null references crawl_runs(id) on delete cascade,
                    account_id text not null,
                    lead_type text not null,
                    normalized_value text not null,
                    raw_snippet text not null,
                    confidence real not null,
                    extractor_name text not null,
                    source_field text not null,
                    observed_at text not null
                );

                create table if not exists discovery_edges (
                    id integer primary key autoincrement,
                    from_account_id text not null,
                    to_account_id text not null,
                    edge_type text not null,
                    seed_account_id text not null default '',
                    min_depth integer not null,
                    first_seen_at text not null,
                    last_seen_at text not null,
                    seen_count integer not null default 1,
                    unique(from_account_id, to_account_id, edge_type, seed_account_id)
                );

                create table if not exists seed_pool (
                    account_id text primary key,
                    seed_kind text not null,
                    is_active integer not null default 1,
                    first_seen_at text not null,
                    last_seen_at text not null,
                    promoted_at text,
                    last_productive_at text
                );

                create table if not exists search_terms (
                    term text primary key,
                    source_type text not null,
                    source_value text not null,
                    is_active integer not null default 1,
                    cooldown_until text,
                    last_selected_at text,
                    last_result_count integer not null default 0,
                    last_new_contactable_count integer not null default 0,
                    created_at text not null,
                    updated_at text not null
                );

                create table if not exists search_term_activity (
                    id integer primary key autoincrement,
                    run_id integer references crawl_runs(id) on delete set null,
                    term text not null,
                    candidate_count integer not null default 0,
                    new_contactable_count integer not null default 0,
                    created_at text not null
                );

                create table if not exists discovery_queue (
                    id integer primary key autoincrement,
                    profile_url text not null unique,
                    account_id text not null default '',
                    source_type text not null,
                    source_seed_account_id text not null default '',
                    search_term text not null default '',
                    priority real not null default 0,
                    status text not null default 'pending',
                    next_attempt_at text not null,
                    attempt_count integer not null default 0,
                    last_error text not null default '',
                    discovered_at text not null,
                    last_seen_at text not null
                );

                create index if not exists idx_contact_leads_type on contact_leads(lead_type, first_seen_at);
                create index if not exists idx_discovery_queue_status on discovery_queue(status, next_attempt_at, priority);
                create index if not exists idx_search_terms_active on search_terms(is_active, cooldown_until, last_selected_at);
                """
            )

    def start_run(
        self,
        *,
        run_type: str,
        seed_url: str = "",
        safe_mode: bool,
        crawl_budget: int | None,
        started_at: datetime | None = None,
    ) -> int:
        started_iso = _isoformat(started_at)
        with self.connect() as conn:
            cursor = conn.execute(
                """
                insert into crawl_runs (
                    run_type, seed_url, safe_mode, crawl_budget, started_at, status
                ) values (?, ?, ?, ?, ?, 'running')
                """,
                (run_type, seed_url, int(safe_mode), crawl_budget, started_iso),
            )
            return int(cursor.lastrowid)

    def finalize_run(
        self,
        run_id: int,
        *,
        attempted_accounts: int,
        succeeded_accounts: int,
        failed_accounts: int,
        lead_counts: dict[str, int],
        errors: Sequence[dict[str, str]],
        aborted: bool,
        abort_reason: str | None,
        queued_candidates: int = 0,
        processed_search_terms: Sequence[str] = (),
        new_contactable_creators: int = 0,
        promoted_seeds: int = 0,
        finished_at: datetime | None = None,
    ) -> None:
        finished_iso = _isoformat(finished_at)
        with self.connect() as conn:
            conn.execute(
                """
                update crawl_runs
                set status = 'completed',
                    finished_at = ?,
                    attempted_accounts = ?,
                    succeeded_accounts = ?,
                    failed_accounts = ?,
                    lead_counts_json = ?,
                    aborted = ?,
                    abort_reason = ?,
                    errors_json = ?,
                    queued_candidates = ?,
                    processed_search_terms_json = ?,
                    new_contactable_creators = ?,
                    promoted_seeds = ?
                where id = ?
                """,
                (
                    finished_iso,
                    attempted_accounts,
                    succeeded_accounts,
                    failed_accounts,
                    _json_dumps(lead_counts),
                    int(aborted),
                    abort_reason,
                    _json_dumps(list(errors)),
                    queued_candidates,
                    _json_dumps(list(processed_search_terms)),
                    new_contactable_creators,
                    promoted_seeds,
                    run_id,
                ),
            )

    def record_crawl_result(
        self,
        result: CrawlResult,
        *,
        run_type: str,
        safe_mode: bool,
        started_at: datetime | None = None,
        crawl_budget: int | None = None,
    ) -> int:
        started = _ensure_utc(started_at)
        run_id = self.start_run(
            run_type=run_type,
            seed_url=result.run_report.seed_url,
            safe_mode=safe_mode,
            crawl_budget=crawl_budget,
            started_at=started,
        )
        lead_map: dict[str, list[ContactLead]] = {}
        for lead in result.contact_leads:
            lead_map.setdefault(lead.account_id, []).append(lead)

        for account in result.accounts:
            self.persist_account_snapshot(
                run_id=run_id,
                account=account,
                leads=lead_map.get(account.account_id, []),
                observed_at=started,
            )

        self.finalize_run(
            run_id,
            attempted_accounts=result.run_report.attempted_accounts,
            succeeded_accounts=result.run_report.succeeded_accounts,
            failed_accounts=result.run_report.failed_accounts,
            lead_counts=result.run_report.lead_counts,
            errors=result.run_report.errors,
            aborted=result.run_report.aborted,
            abort_reason=result.run_report.abort_reason,
            finished_at=started,
        )
        return run_id

    def persist_account_snapshot(
        self,
        *,
        run_id: int,
        account: AccountRecord,
        leads: Sequence[ContactLead],
        observed_at: datetime | None = None,
    ) -> PersistOutcome:
        observed_iso = _isoformat(observed_at)
        new_contactable_creator = False
        new_email_leads = 0

        with self.connect() as conn:
            existing_account = conn.execute(
                "select 1 from creator_accounts where account_id = ?",
                (account.account_id,),
            ).fetchone()
            if existing_account is None:
                conn.execute(
                    """
                    insert into creator_accounts (
                        account_id, profile_url, nickname, bio_text, visible_metadata_json,
                        creator_segment, relevance_score, first_seen_at, last_seen_at,
                        last_crawl_status, last_crawl_error
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account.account_id,
                        account.profile_url,
                        account.nickname,
                        account.bio_text,
                        _json_dumps(account.visible_metadata),
                        account.creator_segment,
                        account.relevance_score,
                        observed_iso,
                        observed_iso,
                        account.crawl_status,
                        account.crawl_error,
                    ),
                )
            else:
                conn.execute(
                    """
                    update creator_accounts
                    set profile_url = ?,
                        nickname = ?,
                        bio_text = ?,
                        visible_metadata_json = ?,
                        creator_segment = ?,
                        relevance_score = ?,
                        last_seen_at = ?,
                        last_crawl_status = ?,
                        last_crawl_error = ?
                    where account_id = ?
                    """,
                    (
                        account.profile_url,
                        account.nickname,
                        account.bio_text,
                        _json_dumps(account.visible_metadata),
                        account.creator_segment,
                        account.relevance_score,
                        observed_iso,
                        account.crawl_status,
                        account.crawl_error,
                        account.account_id,
                    ),
                )

            conn.execute(
                """
                insert into account_observations (
                    run_id, account_id, profile_url, nickname, bio_text,
                    visible_metadata_json, creator_segment, relevance_score,
                    source_type, source_from, crawl_status, crawl_error,
                    discovery_depth, observed_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    account.account_id,
                    account.profile_url,
                    account.nickname,
                    account.bio_text,
                    _json_dumps(account.visible_metadata),
                    account.creator_segment,
                    account.relevance_score,
                    account.source_type,
                    account.source_from or "",
                    account.crawl_status,
                    account.crawl_error,
                    account.discovery_depth,
                    observed_iso,
                ),
            )

            for lead in leads:
                had_email_before = False
                if lead.lead_type == "email":
                    had_email_before = (
                        conn.execute(
                            """
                            select 1
                            from contact_leads
                            where account_id = ? and lead_type = 'email'
                            limit 1
                            """,
                            (account.account_id,),
                        ).fetchone()
                        is not None
                    )
                existing_lead = conn.execute(
                    """
                    select best_confidence
                    from contact_leads
                    where account_id = ? and lead_type = ? and normalized_value = ?
                    """,
                    (lead.account_id, lead.lead_type, lead.normalized_value),
                ).fetchone()
                if existing_lead is None:
                    conn.execute(
                        """
                        insert into contact_leads (
                            account_id, lead_type, normalized_value, source_field,
                            best_confidence, latest_raw_snippet, latest_extractor_name,
                            first_seen_at, last_seen_at
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            lead.account_id,
                            lead.lead_type,
                            lead.normalized_value,
                            lead.source_field,
                            lead.confidence,
                            lead.raw_snippet,
                            lead.extractor_name,
                            observed_iso,
                            observed_iso,
                        ),
                    )
                    if lead.lead_type == "email":
                        new_email_leads += 1
                        if not had_email_before:
                            new_contactable_creator = True
                else:
                    best_confidence = max(float(existing_lead["best_confidence"]), lead.confidence)
                    conn.execute(
                        """
                        update contact_leads
                        set best_confidence = ?,
                            latest_raw_snippet = ?,
                            latest_extractor_name = ?,
                            last_seen_at = ?
                        where account_id = ? and lead_type = ? and normalized_value = ?
                        """,
                        (
                            best_confidence,
                            lead.raw_snippet,
                            lead.extractor_name,
                            observed_iso,
                            lead.account_id,
                            lead.lead_type,
                            lead.normalized_value,
                        ),
                    )
                conn.execute(
                    """
                    insert into contact_lead_observations (
                        run_id, account_id, lead_type, normalized_value, raw_snippet,
                        confidence, extractor_name, source_field, observed_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        lead.account_id,
                        lead.lead_type,
                        lead.normalized_value,
                        lead.raw_snippet,
                        lead.confidence,
                        lead.extractor_name,
                        lead.source_field,
                        observed_iso,
                    ),
                )

            if account.source_from and account.source_type not in {"seed", "refresh"}:
                seed_account_id = account.source_from if account.source_type == "search_result" else ""
                existing_edge = conn.execute(
                    """
                    select seen_count, min_depth
                    from discovery_edges
                    where from_account_id = ? and to_account_id = ? and edge_type = ? and seed_account_id = ?
                    """,
                    (
                        account.source_from,
                        account.account_id,
                        account.source_type,
                        seed_account_id,
                    ),
                ).fetchone()
                if existing_edge is None:
                    conn.execute(
                        """
                        insert into discovery_edges (
                            from_account_id, to_account_id, edge_type, seed_account_id,
                            min_depth, first_seen_at, last_seen_at, seen_count
                        ) values (?, ?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            account.source_from,
                            account.account_id,
                            account.source_type,
                            seed_account_id,
                            account.discovery_depth,
                            observed_iso,
                            observed_iso,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        update discovery_edges
                        set min_depth = ?,
                            last_seen_at = ?,
                            seen_count = ?
                        where from_account_id = ? and to_account_id = ? and edge_type = ? and seed_account_id = ?
                        """,
                        (
                            min(int(existing_edge["min_depth"]), account.discovery_depth),
                            observed_iso,
                            int(existing_edge["seen_count"]) + 1,
                            account.source_from,
                            account.account_id,
                            account.source_type,
                            seed_account_id,
                        ),
                    )

        return PersistOutcome(
            new_contactable_creator=new_contactable_creator,
            new_email_leads=new_email_leads,
        )

    def list_contactable_creators(
        self,
        *,
        lead_type: str = "email",
        creator_segment: str = "creator",
        min_relevance_score: float = 0.0,
        limit: int = 100,
    ) -> list[ContactableCreator]:
        fetch_limit = max(limit * 5, limit)
        with self.connect() as conn:
            rows = conn.execute(
                """
                select
                    ca.account_id,
                    ca.profile_url,
                    ca.nickname,
                    ca.bio_text,
                    ca.creator_segment,
                    ca.relevance_score,
                    (
                        select cl.normalized_value
                        from contact_leads cl
                        where cl.account_id = ca.account_id and cl.lead_type = ?
                        order by cl.best_confidence desc, cl.first_seen_at asc
                        limit 1
                    ) as email,
                    (
                        select cl.best_confidence
                        from contact_leads cl
                        where cl.account_id = ca.account_id and cl.lead_type = ?
                        order by cl.best_confidence desc, cl.first_seen_at asc
                        limit 1
                    ) as email_confidence,
                    (
                        select count(*)
                        from contact_leads cl
                        where cl.account_id = ca.account_id
                    ) as lead_count,
                    (
                        select min(cl.first_seen_at)
                        from contact_leads cl
                        where cl.account_id = ca.account_id and cl.lead_type = ?
                    ) as first_email_seen_at,
                    ca.last_seen_at
                from creator_accounts ca
                where ca.creator_segment = ?
                  and ca.relevance_score >= ?
                  and ca.last_crawl_status = 'success'
                  and exists (
                      select 1
                      from contact_leads cl
                      where cl.account_id = ca.account_id and cl.lead_type = ?
                  )
                order by ca.relevance_score desc, email_confidence desc, ca.last_seen_at desc
                limit ?
                """,
                (
                    lead_type,
                    lead_type,
                    lead_type,
                    creator_segment,
                    min_relevance_score,
                    lead_type,
                    fetch_limit,
                ),
            ).fetchall()

        deduped: list[ContactableCreator] = []
        seen_profile_urls: set[str] = set()
        for row in rows:
            profile_key = canonicalize_profile_url(row["profile_url"])
            if profile_key in seen_profile_urls:
                continue
            seen_profile_urls.add(profile_key)
            deduped.append(
                ContactableCreator(
                    account_id=row["account_id"],
                    profile_url=row["profile_url"],
                    nickname=row["nickname"],
                    bio_text=row["bio_text"],
                    creator_segment=row["creator_segment"],
                    relevance_score=float(row["relevance_score"]),
                    email=row["email"],
                    email_confidence=float(row["email_confidence"]),
                    lead_count=int(row["lead_count"]),
                    first_email_seen_at=row["first_email_seen_at"],
                    last_seen_at=row["last_seen_at"],
                )
            )
            if len(deduped) >= limit:
                break
        return deduped

    def list_creator_account_ids(self) -> set[str]:
        with self.connect() as conn:
            rows = conn.execute("select account_id from creator_accounts").fetchall()
        return {str(row["account_id"]) for row in rows if row["account_id"]}

    def seed_default_search_terms(self, *, now: datetime | None = None) -> None:
        seed_terms = list(SEARCH_QUERY_GROUPS["beauty"])
        for _, query in TOPIC_QUERY_HINTS:
            if query not in seed_terms:
                seed_terms.append(query)
        self.upsert_search_terms(
            seed_terms,
            source_type="bootstrap",
            source_value="system",
            now=now,
        )

    def upsert_search_terms(
        self,
        terms: Iterable[str],
        *,
        source_type: str,
        source_value: str,
        now: datetime | None = None,
    ) -> None:
        now_iso = _isoformat(now)
        with self.connect() as conn:
            for term in terms:
                normalized = " ".join(str(term).split()).strip()
                if not normalized:
                    continue
                existing = conn.execute(
                    "select source_type, source_value from search_terms where term = ?",
                    (normalized,),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        insert into search_terms (
                            term, source_type, source_value, created_at, updated_at
                        ) values (?, ?, ?, ?, ?)
                        """,
                        (normalized, source_type, source_value, now_iso, now_iso),
                    )
                    continue
                if source_type == "creator" and existing["source_type"] != "creator":
                    conn.execute(
                        """
                        update search_terms
                        set source_type = ?, source_value = ?, updated_at = ?
                        where term = ?
                        """,
                        (source_type, source_value, now_iso, normalized),
                    )

    def select_search_terms(self, *, limit: int, now: datetime | None = None) -> list[str]:
        now_iso = _isoformat(now)
        with self.connect() as conn:
            rows = conn.execute(
                """
                select term
                from search_terms
                where is_active = 1
                  and (cooldown_until is null or cooldown_until <= ?)
                order by
                    case when last_selected_at is null then 0 else 1 end,
                    last_selected_at asc,
                    rowid asc
                limit ?
                """,
                (now_iso, limit),
            ).fetchall()
            terms = [str(row["term"]) for row in rows]
            if terms:
                conn.executemany(
                    "update search_terms set last_selected_at = ?, updated_at = ? where term = ?",
                    [(now_iso, now_iso, term) for term in terms],
                )
        return terms

    def record_search_term_outcome(
        self,
        term: str,
        *,
        candidate_count: int,
        new_contactable_count: int,
        now: datetime | None = None,
        run_id: int | None = None,
    ) -> None:
        moment = _ensure_utc(now)
        now_iso = moment.isoformat()
        cooldown_until = None
        if candidate_count == 0 and new_contactable_count == 0:
            cooldown_until = (moment + timedelta(days=3)).isoformat()
        elif new_contactable_count == 0:
            cooldown_until = (moment + timedelta(days=1)).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                update search_terms
                set cooldown_until = ?,
                    last_result_count = ?,
                    last_new_contactable_count = ?,
                    updated_at = ?
                where term = ?
                """,
                (
                    cooldown_until,
                    candidate_count,
                    new_contactable_count,
                    now_iso,
                    term,
                ),
            )
            conn.execute(
                """
                insert into search_term_activity (
                    run_id, term, candidate_count, new_contactable_count, created_at
                ) values (?, ?, ?, ?, ?)
                """,
                (run_id, term, candidate_count, new_contactable_count, now_iso),
            )

    def get_collect_window_usage(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> CollectWindowUsage:
        start_iso = _isoformat(window_start)
        end_iso = _isoformat(window_end)
        with self.connect() as conn:
            rows = conn.execute(
                """
                select attempted_accounts, processed_search_terms_json
                from crawl_runs
                where run_type = 'collect_nightly'
                  and started_at >= ?
                  and started_at < ?
                """,
                (start_iso, end_iso),
            ).fetchall()

        attempted_accounts = 0
        processed_search_terms = 0
        for row in rows:
            attempted_accounts += int(row["attempted_accounts"] or 0)
            try:
                processed_search_terms += len(
                    json.loads(row["processed_search_terms_json"] or "[]")
                )
            except Exception:
                continue
        return CollectWindowUsage(
            run_count=len(rows),
            attempted_accounts=attempted_accounts,
            processed_search_terms=processed_search_terms,
        )

    def enqueue_discovery_candidates(
        self,
        candidates: Sequence[dict[str, object]],
        *,
        source_type: str,
        source_seed_account_id: str,
        search_term: str,
        now: datetime | None = None,
    ) -> int:
        now_iso = _isoformat(now)
        inserted = 0
        with self.connect() as conn:
            for candidate in candidates:
                profile_url = str(candidate.get("profile_url", "")).strip()
                if not profile_url:
                    continue
                account_id = str(candidate.get("account_id", "")).strip()
                priority = float(candidate.get("priority", 0.5))
                existing = conn.execute(
                    """
                    select id, status, priority
                    from discovery_queue
                    where profile_url = ?
                       or (? != '' and account_id = ?)
                    """,
                    (profile_url, account_id, account_id),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        insert into discovery_queue (
                            profile_url, account_id, source_type, source_seed_account_id,
                            search_term, priority, status, next_attempt_at,
                            discovered_at, last_seen_at
                        ) values (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                        """,
                        (
                            profile_url,
                            account_id,
                            source_type,
                            source_seed_account_id,
                            search_term,
                            priority,
                            now_iso,
                            now_iso,
                            now_iso,
                        ),
                    )
                    inserted += 1
                    continue

                next_status = existing["status"]
                if source_type == "refresh" and next_status != "processing":
                    next_status = "pending"
                conn.execute(
                    """
                    update discovery_queue
                    set account_id = case when account_id = '' then ? else account_id end,
                        profile_url = case when account_id = ? then ? else profile_url end,
                        source_type = ?,
                        source_seed_account_id = ?,
                        search_term = case when search_term = '' then ? else search_term end,
                        priority = ?,
                        status = ?,
                        next_attempt_at = case when ? = 'pending' then ? else next_attempt_at end,
                        last_seen_at = ?
                    where id = ?
                    """,
                    (
                        account_id,
                        account_id,
                        profile_url,
                        source_type,
                        source_seed_account_id,
                        search_term,
                        max(float(existing["priority"]), priority),
                        next_status,
                        next_status,
                        now_iso,
                        now_iso,
                        int(existing["id"]),
                    ),
                )
        return inserted

    def dequeue_discovery_candidates(
        self,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> list[DiscoveryQueueItem]:
        now_iso = _isoformat(now)
        with self.connect() as conn:
            rows = conn.execute(
                """
                select id, profile_url, account_id, source_type, source_seed_account_id,
                       search_term, priority, status, attempt_count
                from discovery_queue
                where status = 'pending'
                  and next_attempt_at <= ?
                order by priority desc, discovered_at asc, id asc
                limit ?
                """,
                (now_iso, limit),
            ).fetchall()
        return [
            DiscoveryQueueItem(
                id=int(row["id"]),
                profile_url=row["profile_url"],
                account_id=row["account_id"],
                source_type=row["source_type"],
                source_seed_account_id=row["source_seed_account_id"],
                search_term=row["search_term"],
                priority=float(row["priority"]),
                status=row["status"],
                attempt_count=int(row["attempt_count"]),
            )
            for row in rows
        ]

    def mark_queue_item_processing(self, item_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                update discovery_queue
                set status = 'processing',
                    attempt_count = attempt_count + 1
                where id = ?
                """,
                (item_id,),
            )

    def mark_queue_item_done(
        self,
        item_id: int,
        *,
        account_id: str,
        now: datetime | None = None,
    ) -> None:
        now_iso = _isoformat(now)
        with self.connect() as conn:
            conn.execute(
                """
                update discovery_queue
                set status = 'done',
                    account_id = ?,
                    last_seen_at = ?,
                    last_error = ''
                where id = ?
                """,
                (account_id, now_iso, item_id),
            )

    def mark_queue_item_failed(
        self,
        item_id: int,
        *,
        error: str,
        now: datetime | None = None,
        retry_after_hours: int = 24,
    ) -> None:
        now_dt = _ensure_utc(now)
        next_attempt = (now_dt + timedelta(hours=retry_after_hours)).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                update discovery_queue
                set status = 'pending',
                    last_error = ?,
                    next_attempt_at = ?
                where id = ?
                """,
                (error, next_attempt, item_id),
            )

    def mark_queue_item_filtered(
        self,
        item_id: int,
        *,
        error: str,
        now: datetime | None = None,
    ) -> None:
        now_iso = _isoformat(now)
        with self.connect() as conn:
            conn.execute(
                """
                update discovery_queue
                set status = 'filtered',
                    last_error = ?,
                    last_seen_at = ?
                where id = ?
                """,
                (error, now_iso, item_id),
            )

    def enqueue_refresh_candidates(
        self,
        *,
        limit: int,
        now: datetime | None = None,
        refresh_after_days: int = 14,
    ) -> int:
        if limit <= 0:
            return 0
        now_dt = _ensure_utc(now)
        cutoff_iso = (now_dt - timedelta(days=refresh_after_days)).isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                """
                select account_id, profile_url
                from creator_accounts
                where last_seen_at <= ?
                  and last_crawl_status = 'success'
                order by last_seen_at asc
                limit ?
                """,
                (cutoff_iso, limit),
            ).fetchall()
        candidates = [
            {
                "profile_url": row["profile_url"],
                "account_id": row["account_id"],
                "priority": 0.25,
            }
            for row in rows
        ]
        return self.enqueue_discovery_candidates(
            candidates,
            source_type="refresh",
            source_seed_account_id="",
            search_term="",
            now=now_dt,
        )

    def upsert_seed_account(
        self,
        account_id: str,
        *,
        seed_kind: str,
        now: datetime | None = None,
        productive: bool = False,
    ) -> bool:
        now_iso = _isoformat(now)
        with self.connect() as conn:
            existing = conn.execute(
                "select 1 from seed_pool where account_id = ?",
                (account_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    insert into seed_pool (
                        account_id, seed_kind, first_seen_at, last_seen_at,
                        promoted_at, last_productive_at
                    ) values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account_id,
                        seed_kind,
                        now_iso,
                        now_iso,
                        now_iso if seed_kind == "promoted_seed" else None,
                        now_iso if productive else None,
                    ),
                )
                return True

            conn.execute(
                """
                update seed_pool
                set seed_kind = ?,
                    last_seen_at = ?,
                    last_productive_at = case when ? then ? else last_productive_at end
                where account_id = ?
                """,
                (seed_kind, now_iso, int(productive), now_iso, account_id),
            )
            return False

    def build_weekly_growth_report(
        self,
        *,
        days: int = 7,
        now: datetime | None = None,
    ) -> WeeklyGrowthReport:
        now_dt = _ensure_utc(now)
        start_iso = (now_dt - timedelta(days=days)).isoformat()
        now_iso = now_dt.isoformat()
        with self.connect() as conn:
            new_contactable_creators = int(
                conn.execute(
                    """
                    select count(distinct account_id)
                    from contact_leads
                    where lead_type = 'email'
                      and first_seen_at >= ?
                      and first_seen_at <= ?
                    """,
                    (start_iso, now_iso),
                ).fetchone()[0]
            )
            new_email_leads = int(
                conn.execute(
                    """
                    select count(*)
                    from contact_leads
                    where lead_type = 'email'
                      and first_seen_at >= ?
                      and first_seen_at <= ?
                    """,
                    (start_iso, now_iso),
                ).fetchone()[0]
            )
            new_promoted_seeds = int(
                conn.execute(
                    """
                    select count(*)
                    from seed_pool
                    where seed_kind = 'promoted_seed'
                      and promoted_at is not null
                      and promoted_at >= ?
                      and promoted_at <= ?
                    """,
                    (start_iso, now_iso),
                ).fetchone()[0]
            )
            risk_abort_count = int(
                conn.execute(
                    """
                    select count(*)
                    from crawl_runs
                    where aborted = 1
                      and started_at >= ?
                      and started_at <= ?
                    """,
                    (start_iso, now_iso),
                ).fetchone()[0]
            )
            top_rows = conn.execute(
                """
                select term, sum(candidate_count) as candidate_count, sum(new_contactable_count) as new_contactable_count
                from search_term_activity
                where created_at >= ? and created_at <= ?
                group by term
                order by new_contactable_count desc, candidate_count desc, term asc
                limit 5
                """,
                (start_iso, now_iso),
            ).fetchall()

        return WeeklyGrowthReport(
            window_days=days,
            generated_at=now_iso,
            new_contactable_creators=new_contactable_creators,
            new_email_leads=new_email_leads,
            new_promoted_seeds=new_promoted_seeds,
            risk_abort_count=risk_abort_count,
            top_search_terms=[
                {
                    "term": row["term"],
                    "candidate_count": int(row["candidate_count"]),
                    "new_contactable_count": int(row["new_contactable_count"]),
                }
                for row in top_rows
            ],
        )
