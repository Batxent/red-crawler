from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional, Protocol, Tuple

from red_crawler.crawl.profile import build_failed_account_record, parse_profile_html
from red_crawler.crawl.similar import extract_similar_profiles
from red_crawler.extract.contacts import extract_contact_leads
from red_crawler.models import AccountRecord, ContactLead, CrawlResult, RunReport
from red_crawler.session import BrowserSession, PlaywrightCrawlerClient


class CrawlClient(Protocol):
    def fetch_profile_html(self, profile_url: str) -> str: ...

    def fetch_note_recommendation_html(self, profile_url: str) -> list[str]: ...


@dataclass
class CrawlConfig:
    seed_url: str
    storage_state: str
    output_dir: str
    max_accounts: int = 20
    max_depth: int = 1
    include_note_recommendations: bool = False


def run_crawl_seed(config: CrawlConfig) -> CrawlResult:
    with BrowserSession(config.storage_state) as session:
        client = PlaywrightCrawlerClient(session)
        return run_crawl_seed_with_client(config, client)


def run_crawl_seed_with_client(
    config: CrawlConfig, client: CrawlClient
) -> CrawlResult:
    queue: Deque[Tuple[str, int, str, Optional[str]]] = deque(
        [(config.seed_url, 0, "seed", None)]
    )
    queued_urls = {config.seed_url}
    accounts: list[AccountRecord] = []
    contact_leads: list[ContactLead] = []
    errors: list[dict[str, str]] = []

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
            accounts.append(account)
            contact_leads.extend(
                extract_contact_leads(
                    account_id=account.account_id,
                    bio_text=account.bio_text,
                )
            )
        except Exception as exc:
            accounts.append(
                build_failed_account_record(
                    profile_url=profile_url,
                    source_type=source_type,
                    source_from=source_from,
                    error=str(exc),
                )
            )
            errors.append({"profile_url": profile_url, "error": str(exc)})
            continue

        if depth >= config.max_depth or len(accounts) >= config.max_accounts:
            continue

        remaining_slots = config.max_accounts - len(queued_urls)
        if remaining_slots <= 0:
            continue

        recommendation_candidates = extract_similar_profiles(
            html=html,
            base_profile_url=profile_url,
            max_results=remaining_slots,
        )
        if config.include_note_recommendations:
            for note_html in client.fetch_note_recommendation_html(profile_url):
                extra_slots = config.max_accounts - len(queued_urls)
                if extra_slots <= 0:
                    break
                recommendation_candidates.extend(
                    extract_similar_profiles(
                        html=note_html,
                        base_profile_url=profile_url,
                        max_results=extra_slots,
                    )
                )

        for candidate in recommendation_candidates:
            candidate_url = candidate["profile_url"]
            if candidate_url in queued_urls:
                continue
            queued_urls.add(candidate_url)
            queue.append(
                (
                    candidate_url,
                    depth + 1,
                    "recommended",
                    account.account_id,
                )
            )
            if len(queued_urls) >= config.max_accounts:
                break

    lead_counts = dict(sorted(Counter(lead.lead_type for lead in contact_leads).items()))
    failed_accounts = sum(1 for account in accounts if account.crawl_status != "success")

    return CrawlResult(
        accounts=accounts,
        contact_leads=contact_leads,
        run_report=RunReport(
            seed_url=config.seed_url,
            attempted_accounts=len(accounts),
            succeeded_accounts=len(accounts) - failed_accounts,
            failed_accounts=failed_accounts,
            lead_counts=lead_counts,
            errors=errors,
        ),
    )
