from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AccountRecord:
    account_id: str
    profile_url: str
    nickname: str
    bio_text: str
    visible_metadata: Dict[str, Any]
    source_type: str
    source_from: Optional[str]
    crawl_status: str
    crawl_error: Optional[str]
    discovery_depth: int = 0
    creator_segment: str = ""
    relevance_score: float = 0.0

    def to_row(self) -> Dict[str, str]:
        import json

        return {
            "account_id": self.account_id,
            "profile_url": self.profile_url,
            "nickname": self.nickname,
            "bio_text": self.bio_text,
            "visible_metadata": json.dumps(
                self.visible_metadata, ensure_ascii=False, sort_keys=True
            ),
            "creator_segment": self.creator_segment,
            "relevance_score": f"{self.relevance_score:.2f}",
            "source_type": self.source_type,
            "source_from": self.source_from or "",
            "crawl_status": self.crawl_status,
            "crawl_error": self.crawl_error or "",
        }


@dataclass
class ContactLead:
    account_id: str
    lead_type: str
    normalized_value: str
    raw_snippet: str
    confidence: float
    extractor_name: str
    source_field: str
    dedupe_key: str

    def to_row(self) -> Dict[str, str]:
        return {
            "account_id": self.account_id,
            "lead_type": self.lead_type,
            "normalized_value": self.normalized_value,
            "raw_snippet": self.raw_snippet,
            "confidence": f"{self.confidence:.2f}",
            "extractor_name": self.extractor_name,
            "source_field": self.source_field,
            "dedupe_key": self.dedupe_key,
        }


@dataclass
class RunReport:
    seed_url: str
    attempted_accounts: int
    succeeded_accounts: int
    failed_accounts: int
    lead_counts: Dict[str, int]
    aborted: bool = False
    abort_reason: Optional[str] = None
    errors: List[Dict[str, str]] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CrawlResult:
    accounts: List[AccountRecord]
    contact_leads: List[ContactLead]
    run_report: RunReport
