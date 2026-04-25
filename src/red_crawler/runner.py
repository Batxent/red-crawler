from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional, Protocol, Tuple

from red_crawler.crawl.profile import build_failed_account_record, parse_profile_html
from red_crawler.crawl.similar import (
    build_search_queries,
    classify_creator_segment,
    extract_search_result_profiles,
    extract_similar_profiles,
    is_relevant_creator_candidate,
    parse_follower_count,
    score_creator_relevance,
)
from red_crawler.extract.contacts import extract_contact_leads
from red_crawler.models import AccountRecord, ContactLead, CrawlResult, RunReport
from red_crawler.profile_url import build_profile_dedupe_key
from red_crawler.session import (
    BrowserSession,
    DEFAULT_COSMETICS_HOMEFEED_URL,
    PlaywrightCrawlerClient,
    RiskControlTriggered,
)


class CrawlClient(Protocol):
    def fetch_profile_html(self, profile_url: str) -> str: ...

    def fetch_note_recommendation_html(self, profile_url: str) -> list[str]: ...

    def fetch_search_result_htmls(self, query: str) -> list[str]: ...

    def fetch_homefeed_result_htmls(self, source_url: str) -> list[str]: ...


@dataclass
class CrawlConfig:
    seed_url: str
    output_dir: str = "output"
    storage_state: str = ""
    max_accounts: int = 20
    max_depth: int = 2
    include_note_recommendations: bool = False
    safe_mode: bool = False
    interaction_mode: str = "playwright"
    browser_mode: str = "local"
    browser_endpoint: str | None = None
    browser_auth: str | None = None
    cache_dir: str | None = None
    cache_ttl_days: int = 7
    gender_filter: str | None = None


@dataclass
class SearchCrawlConfig:
    search_term: str
    output_dir: str = "output"
    storage_state: str = ""
    max_accounts: int = 20
    search_scroll_rounds: int = 2
    min_followers: int = 0
    min_relevance_score: float = 0.0
    creator_only: bool = False
    safe_mode: bool = False
    interaction_mode: str = "playwright"
    browser_mode: str = "local"
    browser_endpoint: str | None = None
    browser_auth: str | None = None
    cache_dir: str | None = None
    cache_ttl_days: int = 7
    gender_filter: str | None = None


@dataclass
class HomefeedCrawlConfig:
    output_dir: str
    storage_state: str = ""
    homefeed_url: str = DEFAULT_COSMETICS_HOMEFEED_URL
    max_accounts: int = 20
    search_scroll_rounds: int = 2
    min_followers: int = 0
    min_relevance_score: float = 0.0
    creator_only: bool = False
    safe_mode: bool = False
    interaction_mode: str = "playwright"
    browser_mode: str = "local"
    browser_endpoint: str | None = None
    browser_auth: str | None = None
    cache_dir: str | None = None
    cache_ttl_days: int = 7
    gender_filter: str | None = None


def _normalize_gender_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"", "all", "any", "全部", "不限"}:
        return None
    if normalized in {"male", "m", "man", "men", "男", "男性", "男生", "男的"}:
        return "male"
    if normalized in {"female", "f", "woman", "women", "女", "女性", "女生", "女的"}:
        return "female"
    raise ValueError("gender_filter must be one of: male, female, 男, 女")


def _infer_gender(account: AccountRecord) -> str | None:
    tags = account.visible_metadata.get("tags", [])
    tag_text = " ".join(str(tag) for tag in tags) if isinstance(tags, list) else str(tags)
    text = f"{account.nickname} {account.bio_text} {tag_text}"
    female_markers = ("女生", "女孩", "女博主", "女性", "姐妹", "宝妈", "辣妈", "妈妈")
    male_markers = ("男生", "男孩", "男博主", "男性", "型男", "男士")
    female_score = sum(marker in text for marker in female_markers)
    male_score = sum(marker in text for marker in male_markers)
    if female_score > male_score:
        return "female"
    if male_score > female_score:
        return "male"
    return None


def _matches_gender_filter(account: AccountRecord, gender_filter: str | None) -> bool:
    if gender_filter is None:
        return True
    inferred_gender = _infer_gender(account)
    if inferred_gender:
        account.visible_metadata["gender"] = inferred_gender
    return inferred_gender == gender_filter


def run_crawl_seed(config: CrawlConfig) -> CrawlResult:
    with BrowserSession(
        config.storage_state,
        browser_mode=config.browser_mode,
        browser_endpoint=config.browser_endpoint,
        browser_auth=config.browser_auth,
    ) as session:
        client = PlaywrightCrawlerClient(
            session,
            safe_mode=config.safe_mode,
            interaction_mode=config.interaction_mode,
            cache_dir=config.cache_dir,
            cache_ttl_days=config.cache_ttl_days,
        )
        return run_crawl_seed_with_client(config, client)


def run_crawl_search(config: SearchCrawlConfig) -> CrawlResult:
    with BrowserSession(
        config.storage_state,
        browser_mode=config.browser_mode,
        browser_endpoint=config.browser_endpoint,
        browser_auth=config.browser_auth,
    ) as session:
        client = PlaywrightCrawlerClient(
            session,
            safe_mode=config.safe_mode,
            interaction_mode=config.interaction_mode,
            search_scroll_rounds=config.search_scroll_rounds,
            cache_dir=config.cache_dir,
            cache_ttl_days=config.cache_ttl_days,
        )
        return run_crawl_search_with_client(config, client)


def run_crawl_homefeed(config: HomefeedCrawlConfig) -> CrawlResult:
    with BrowserSession(
        config.storage_state,
        browser_mode=config.browser_mode,
        browser_endpoint=config.browser_endpoint,
        browser_auth=config.browser_auth,
    ) as session:
        client = PlaywrightCrawlerClient(
            session,
            safe_mode=config.safe_mode,
            interaction_mode=config.interaction_mode,
            search_scroll_rounds=config.search_scroll_rounds,
            cache_dir=config.cache_dir,
            cache_ttl_days=config.cache_ttl_days,
        )
        return run_crawl_homefeed_with_client(config, client)


def run_crawl_homefeed_with_client(
    config: HomefeedCrawlConfig, client: CrawlClient
) -> CrawlResult:
    gender_filter = _normalize_gender_filter(config.gender_filter)
    accounts: list[AccountRecord] = []
    contact_leads: list[ContactLead] = []
    errors: list[dict[str, str]] = []
    aborted = False
    abort_reason: str | None = None
    queued_keys: set[str] = set()
    source_payload: Dict[str, object] = {
        "bio_text": "彩妆博主",
        "visible_metadata": {"tags": ["彩妆", "美妆"]},
    }

    try:
        html_snapshots = client.fetch_homefeed_result_htmls(config.homefeed_url)
    except RiskControlTriggered as exc:
        aborted = True
        abort_reason = str(exc)
        errors.append({"source": config.homefeed_url, "error": str(exc)})
        html_snapshots = []

    candidates: list[dict[str, object]] = []
    for html in html_snapshots:
        remaining_slots = config.max_accounts - len(queued_keys)
        if remaining_slots <= 0:
            break
        for candidate in extract_search_result_profiles(
            html=html,
            max_results=remaining_slots,
        ):
            candidate_key = build_profile_dedupe_key(
                candidate["profile_url"],
                str(candidate.get("account_id", "")),
            )
            if candidate_key in queued_keys:
                continue
            queued_keys.add(candidate_key)
            candidates.append(candidate)
            if len(candidates) >= config.max_accounts:
                break

    for candidate in candidates:
        profile_url = str(candidate["profile_url"])
        try:
            html = client.fetch_profile_html(profile_url)
            account = parse_profile_html(
                html=html,
                profile_url=profile_url,
                source_type="homefeed",
                source_from=config.homefeed_url,
            )
            account.discovery_depth = 0
            account_payload = {
                "nickname": account.nickname,
                "bio_text": account.bio_text,
                "visible_metadata": account.visible_metadata,
            }
            account.creator_segment = classify_creator_segment(account_payload)
            account.relevance_score = score_creator_relevance(
                seed_account=source_payload,
                candidate_account=account_payload,
            )
            follower_count = parse_follower_count(
                str(account.visible_metadata.get("followers", ""))
            )
            if config.creator_only and account.creator_segment != "creator":
                continue
            if follower_count < max(config.min_followers, 0):
                continue
            if account.relevance_score < config.min_relevance_score:
                continue
            if _matches_gender_filter(account, gender_filter):
                accounts.append(account)
                contact_leads.extend(
                    extract_contact_leads(
                        account_id=account.account_id,
                        bio_text=account.bio_text,
                    )
                )
        except RiskControlTriggered as exc:
            aborted = True
            abort_reason = str(exc)
            errors.append({"profile_url": profile_url, "error": str(exc)})
            break
        except Exception as exc:
            accounts.append(
                build_failed_account_record(
                    profile_url=profile_url,
                    source_type="homefeed",
                    source_from=config.homefeed_url,
                    error=str(exc),
                    discovery_depth=0,
                )
            )
            errors.append({"profile_url": profile_url, "error": str(exc)})

    lead_counts = dict(sorted(Counter(lead.lead_type for lead in contact_leads).items()))
    failed_accounts = sum(1 for account in accounts if account.crawl_status != "success")
    return CrawlResult(
        accounts=accounts,
        contact_leads=contact_leads,
        run_report=RunReport(
            seed_url=f"homefeed:{config.homefeed_url}",
            attempted_accounts=len(accounts),
            succeeded_accounts=len(accounts) - failed_accounts,
            failed_accounts=failed_accounts,
            lead_counts=lead_counts,
            aborted=aborted,
            abort_reason=abort_reason,
            errors=errors,
        ),
    )


def run_crawl_search_with_client(
    config: SearchCrawlConfig, client: CrawlClient
) -> CrawlResult:
    gender_filter = _normalize_gender_filter(config.gender_filter)
    accounts: list[AccountRecord] = []
    contact_leads: list[ContactLead] = []
    errors: list[dict[str, str]] = []
    aborted = False
    abort_reason: str | None = None
    queued_keys: set[str] = set()
    query_payload: Dict[str, object] = {
        "bio_text": config.search_term,
        "visible_metadata": {"tags": [config.search_term]},
    }

    try:
        search_htmls = client.fetch_search_result_htmls(config.search_term)
    except RiskControlTriggered as exc:
        aborted = True
        abort_reason = str(exc)
        errors.append({"search_term": config.search_term, "error": str(exc)})
        search_htmls = []

    candidates: list[dict[str, object]] = []
    for search_html in search_htmls:
        remaining_slots = config.max_accounts - len(queued_keys)
        if remaining_slots <= 0:
            break
        for candidate in extract_search_result_profiles(
            html=search_html,
            max_results=remaining_slots,
        ):
            candidate_key = build_profile_dedupe_key(
                candidate["profile_url"],
                str(candidate.get("account_id", "")),
            )
            if candidate_key in queued_keys:
                continue
            queued_keys.add(candidate_key)
            candidates.append(candidate)
            if len(candidates) >= config.max_accounts:
                break

    for candidate in candidates:
        profile_url = str(candidate["profile_url"])
        try:
            html = client.fetch_profile_html(profile_url)
            account = parse_profile_html(
                html=html,
                profile_url=profile_url,
                source_type="search_result",
                source_from=None,
            )
            account.discovery_depth = 0
            account_payload = {
                "nickname": account.nickname,
                "bio_text": account.bio_text,
                "visible_metadata": account.visible_metadata,
            }
            account.creator_segment = classify_creator_segment(account_payload)
            account.relevance_score = score_creator_relevance(
                seed_account=query_payload,
                candidate_account=account_payload,
            )
            candidate_tags = account.visible_metadata.get("tags", []) or []
            if isinstance(candidate_tags, str):
                candidate_tags = [candidate_tags]
            candidate_text = " ".join(
                [account.nickname, account.bio_text]
                + [str(tag) for tag in candidate_tags]
            )
            normalized_search_term = " ".join(config.search_term.split()).strip()
            search_term_matched = False
            if normalized_search_term and normalized_search_term in candidate_text:
                search_term_matched = True
            elif (
                normalized_search_term.endswith("博主")
                and normalized_search_term[:-2]
                and normalized_search_term[:-2] in candidate_text
                and "博主" in candidate_text
            ):
                search_term_matched = True
            if search_term_matched:
                account.relevance_score = round(min(account.relevance_score + 0.25, 1.0), 2)
            follower_count = parse_follower_count(
                str(account.visible_metadata.get("followers", ""))
            )
            if config.creator_only and account.creator_segment != "creator":
                continue
            if follower_count < max(config.min_followers, 0):
                continue
            if account.relevance_score < config.min_relevance_score:
                continue
            if _matches_gender_filter(account, gender_filter):
                accounts.append(account)
                contact_leads.extend(
                    extract_contact_leads(
                        account_id=account.account_id,
                        bio_text=account.bio_text,
                    )
                )
        except RiskControlTriggered as exc:
            aborted = True
            abort_reason = str(exc)
            errors.append({"profile_url": profile_url, "error": str(exc)})
            break
        except Exception as exc:
            accounts.append(
                build_failed_account_record(
                    profile_url=profile_url,
                    source_type="search_result",
                    source_from=None,
                    error=str(exc),
                    discovery_depth=0,
                )
            )
            errors.append({"profile_url": profile_url, "error": str(exc)})

    lead_counts = dict(sorted(Counter(lead.lead_type for lead in contact_leads).items()))
    failed_accounts = sum(1 for account in accounts if account.crawl_status != "success")
    return CrawlResult(
        accounts=accounts,
        contact_leads=contact_leads,
        run_report=RunReport(
            seed_url=f"search:{config.search_term}",
            attempted_accounts=len(accounts),
            succeeded_accounts=len(accounts) - failed_accounts,
            failed_accounts=failed_accounts,
            lead_counts=lead_counts,
            aborted=aborted,
            abort_reason=abort_reason,
            errors=errors,
        ),
    )


def run_crawl_seed_with_client(
    config: CrawlConfig, client: CrawlClient
) -> CrawlResult:
    gender_filter = _normalize_gender_filter(config.gender_filter)
    seed_queue_key = build_profile_dedupe_key(config.seed_url)
    queue: Deque[Tuple[str, int, str, Optional[str]]] = deque(
        [(config.seed_url, 0, "seed", None)]
    )
    queued_keys = {seed_queue_key}
    accounts: list[AccountRecord] = []
    contact_leads: list[ContactLead] = []
    errors: list[dict[str, str]] = []
    aborted = False
    abort_reason: str | None = None
    seed_reference_payload: Dict[str, object] | None = None

    while queue and len(accounts) < config.max_accounts:
        profile_url, depth, source_type, source_from = queue.popleft()
        try:
            html = client.fetch_profile_html(profile_url)
            account = parse_profile_html(
                html=html,
                profile_url=profile_url,
                source_type=source_type,
                source_from=source_from,
            )
            account.discovery_depth = depth
            account.creator_segment = classify_creator_segment(
                {
                    "nickname": account.nickname,
                    "bio_text": account.bio_text,
                    "visible_metadata": account.visible_metadata,
                }
            )
            if source_type == "seed":
                seed_reference_payload = {
                    "nickname": account.nickname,
                    "bio_text": account.bio_text,
                    "visible_metadata": account.visible_metadata,
                }
            account.relevance_score = 1.0 if source_type == "seed" else 0.0
            if _matches_gender_filter(account, gender_filter):
                accounts.append(account)
                contact_leads.extend(
                    extract_contact_leads(
                        account_id=account.account_id,
                        bio_text=account.bio_text,
                    )
                )
        except RiskControlTriggered as exc:
            aborted = True
            abort_reason = str(exc)
            errors.append({"profile_url": profile_url, "error": str(exc)})
            break
        except Exception as exc:
            accounts.append(
                build_failed_account_record(
                    profile_url=profile_url,
                    source_type=source_type,
                    source_from=source_from,
                    error=str(exc),
                    discovery_depth=depth,
                )
            )
            errors.append({"profile_url": profile_url, "error": str(exc)})
            continue

        if depth >= config.max_depth or len(accounts) >= config.max_accounts:
            continue

        remaining_slots = config.max_accounts - len(queued_keys)
        if remaining_slots <= 0:
            continue

        recommendation_candidates = [
            {**candidate, "source_type": "profile_recommendation"}
            for candidate in extract_similar_profiles(
                html=html,
                base_profile_url=profile_url,
                max_results=remaining_slots,
            )
        ]
        if config.include_note_recommendations:
            for note_html in client.fetch_note_recommendation_html(profile_url):
                extra_slots = config.max_accounts - len(queued_keys)
                if extra_slots <= 0:
                    break
                recommendation_candidates.extend(
                    [
                        {**candidate, "source_type": "note_recommendation"}
                        for candidate in extract_similar_profiles(
                            html=note_html,
                            base_profile_url=profile_url,
                            max_results=extra_slots,
                        )
                    ]
                )

        if not recommendation_candidates:
            search_candidates = []
            seed_payload: Dict[str, object] = {
                "bio_text": account.bio_text,
                "visible_metadata": account.visible_metadata,
            }
            for query in build_search_queries(seed_payload):
                extra_slots = config.max_accounts - len(queued_keys)
                if extra_slots <= 0:
                    break
                try:
                    search_htmls = client.fetch_search_result_htmls(query)
                except RiskControlTriggered as exc:
                    aborted = True
                    abort_reason = str(exc)
                    errors.append({"profile_url": profile_url, "error": str(exc)})
                    break
                for search_html in search_htmls:
                    extra_slots = config.max_accounts - len(queued_keys)
                    if extra_slots <= 0:
                        break
                    search_candidates.extend(
                        extract_search_result_profiles(
                            html=search_html,
                            max_results=extra_slots,
                        )
                    )
                if aborted:
                    break

            filtered_search_candidates = []
            for candidate in search_candidates:
                candidate_url = candidate["profile_url"]
                candidate_key = build_profile_dedupe_key(
                    candidate_url,
                    str(candidate.get("account_id", "")),
                )
                if candidate_key in queued_keys:
                    continue
                try:
                    candidate_html = client.fetch_profile_html(candidate_url)
                    candidate_account = parse_profile_html(
                        html=candidate_html,
                        profile_url=candidate_url,
                        source_type="recommended",
                        source_from=account.account_id,
                    )
                except RiskControlTriggered as exc:
                    aborted = True
                    abort_reason = str(exc)
                    errors.append({"profile_url": candidate_url, "error": str(exc)})
                    break
                except Exception:
                    continue
                candidate_payload = {
                    "nickname": candidate_account.nickname,
                    "bio_text": candidate_account.bio_text,
                    "visible_metadata": candidate_account.visible_metadata,
                }
                if is_relevant_creator_candidate(
                    seed_account=seed_payload,
                    candidate_account=candidate_payload,
                ):
                    filtered_search_candidates.append(candidate)
            if aborted:
                break

            recommendation_candidates = [
                {**candidate, "source_type": "search_result"}
                for candidate in filtered_search_candidates
            ]

        for candidate in recommendation_candidates:
            candidate_url = candidate["profile_url"]
            candidate_key = build_profile_dedupe_key(
                candidate_url,
                str(candidate.get("account_id", "")),
            )
            if candidate_key in queued_keys:
                continue
            queued_keys.add(candidate_key)
            queue.append(
                (
                    candidate_url,
                    depth + 1,
                    str(candidate.get("source_type", "recommended")),
                    account.account_id,
                )
            )
            if len(queued_keys) >= config.max_accounts:
                break
        if aborted:
            break

    lead_counts = dict(sorted(Counter(lead.lead_type for lead in contact_leads).items()))
    failed_accounts = sum(1 for account in accounts if account.crawl_status != "success")

    if accounts:
        seed_payload = seed_reference_payload or {
            "nickname": accounts[0].nickname,
            "bio_text": accounts[0].bio_text,
            "visible_metadata": accounts[0].visible_metadata,
        }
        for account in accounts:
            if account.crawl_status != "success":
                continue
            account_payload = {
                "nickname": account.nickname,
                "bio_text": account.bio_text,
                "visible_metadata": account.visible_metadata,
            }
            account.creator_segment = classify_creator_segment(account_payload)
            if account.source_type != "seed":
                account.relevance_score = score_creator_relevance(
                    seed_account=seed_payload,
                    candidate_account=account_payload,
                )

    return CrawlResult(
        accounts=accounts,
        contact_leads=contact_leads,
        run_report=RunReport(
            seed_url=config.seed_url,
            attempted_accounts=len(accounts),
            succeeded_accounts=len(accounts) - failed_accounts,
            failed_accounts=failed_accounts,
            lead_counts=lead_counts,
            aborted=aborted,
            abort_reason=abort_reason,
            errors=errors,
        ),
    )
