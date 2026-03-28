from __future__ import annotations

import re
from typing import Iterable, List

from red_crawler.models import ContactLead

EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
WECHAT_RE = re.compile(
    r"(?:微信|vx|wx|vx|VX|WX|v信|微(?:信|x))\s*[:：]?\s*([A-Za-z][A-Za-z0-9_-]{5,19})"
)
BUSINESS_NOTE_RE = re.compile(r"([^，。；;\n]*(?:备注|品牌名)[^，。；;\n]*)")
MANAGER_RE = re.compile(r"([^，。；;\n]*(?:经纪人|商务对接|商务联系)[^，。；;\n]*)")


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()


def _dedupe(leads: Iterable[ContactLead]) -> List[ContactLead]:
    deduped = {}
    for lead in leads:
        existing = deduped.get(lead.dedupe_key)
        if existing is None or existing.confidence < lead.confidence:
            deduped[lead.dedupe_key] = lead
    return sorted(
        deduped.values(),
        key=lambda item: (-item.confidence, item.lead_type, item.normalized_value),
    )


def extract_contact_leads(account_id: str, bio_text: str) -> List[ContactLead]:
    text = _clean_text(bio_text)
    leads: List[ContactLead] = []

    for match in EMAIL_RE.finditer(text):
        email = match.group(1).lower()
        leads.append(
            ContactLead(
                account_id=account_id,
                lead_type="email",
                normalized_value=email,
                raw_snippet=match.group(1),
                confidence=0.96,
                extractor_name="email_regex",
                source_field="bio",
                dedupe_key=f"email:{email}",
            )
        )

    for match in PHONE_RE.finditer(text):
        phone = match.group(1)
        leads.append(
            ContactLead(
                account_id=account_id,
                lead_type="phone",
                normalized_value=phone,
                raw_snippet=phone,
                confidence=0.95,
                extractor_name="phone_regex",
                source_field="bio",
                dedupe_key=f"phone:{phone}",
            )
        )

    for match in WECHAT_RE.finditer(text):
        value = match.group(1).lower()
        leads.append(
            ContactLead(
                account_id=account_id,
                lead_type="wechat",
                normalized_value=value,
                raw_snippet=match.group(0).strip(" ，。;；"),
                confidence=0.98,
                extractor_name="wechat_regex",
                source_field="bio",
                dedupe_key=f"wechat:{value}",
            )
        )

    for match in BUSINESS_NOTE_RE.finditer(text):
        snippet = match.group(1).strip(" ，。;；")
        leads.append(
            ContactLead(
                account_id=account_id,
                lead_type="business_note",
                normalized_value=snippet,
                raw_snippet=snippet,
                confidence=0.48,
                extractor_name="business_note_regex",
                source_field="bio",
                dedupe_key=f"business_note:{snippet}",
            )
        )

    for match in MANAGER_RE.finditer(text):
        snippet = match.group(1).strip(" ，。;；")
        leads.append(
            ContactLead(
                account_id=account_id,
                lead_type="manager",
                normalized_value=snippet,
                raw_snippet=snippet,
                confidence=0.58,
                extractor_name="manager_regex",
                source_field="bio",
                dedupe_key=f"manager:{snippet}",
            )
        )

    if not leads and "商务合作" in text:
        snippet = "可接商务合作" if "可接商务合作" in text else "商务合作"
        leads.append(
            ContactLead(
                account_id=account_id,
                lead_type="other_hint",
                normalized_value=snippet,
                raw_snippet=snippet,
                confidence=0.42,
                extractor_name="business_hint_keyword",
                source_field="bio",
                dedupe_key=f"other_hint:{snippet}",
            )
        )

    return _dedupe(leads)
