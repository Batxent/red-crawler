from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List

from red_crawler.models import ContactLead

EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
OBFUSCATED_EMAIL_RE = re.compile(
    r"([A-Za-z0-9._%+-]+)\s*(?:@|艾特|at|AT)\s*([A-Za-z0-9-]+)\s*(?:\.|点)\s*(com|cn|net)"
)
OBFUSCATED_QQ_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])([1-9]\d{4,11})\s*@\s*(?:qq|QQ|q|Q|企鹅|🐧)\s*(?:\.|点)\s*com\b"
)
QQ_MAIL_LABEL_RE = re.compile(
    r"(?:q邮箱|Q邮箱|qq邮箱|QQ邮箱|企鹅邮箱|🐧邮箱)\s*[:：]?\s*([1-9]\d{4,11})"
)
PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
WECHAT_RE = re.compile(
    r"(?:(?:微信|vx|v x|wx|w x|VX|WX|v信|微(?:信|x)|薇|薇信|卫星|卫星号)\s*[:：]?\s*|(?<![A-Za-z0-9_])[vV]\s*[:：]\s*)"
    r"([A-Za-z][A-Za-z0-9_-]{5,19})"
)
REMARK_CONTACT_ID_RE = re.compile(
    r"(?<![A-Za-z0-9_-])([A-Za-z][A-Za-z0-9_-]{5,19})\s*[（(][^）)]*备注[^）)]*[）)]"
)
BUSINESS_CONTACT_ID_RE = re.compile(
    r"(?:🈴|(?<![\u4e00-\u9fff])合|合作|商务)\s*[:：]?\s*([A-Za-z][A-Za-z0-9_-]{5,19})"
)
QQ_RE = re.compile(r"(?:QQ|qq|扣扣)\s*[:：]?\s*([1-9]\d{4,11})")
BUSINESS_NOTE_RE = re.compile(r"([^，。；;\n]*(?:备注|品牌名)[^，。；;\n]*)")
MANAGER_RE = re.compile(r"([^，。；;\n]*(?:经纪人|商务对接|商务联系)[^，。；;\n]*)")
REDIRECT_ACCOUNT_RE = re.compile(r"((?:日常在|小号在|大号在|备用号在)\s*@[\w\u4e00-\u9fff._-]+)")
SOFT_WECHAT_HINT_RE = re.compile(
    r"([^，。；;\n]*(?:加[Vv]|加微|加薇)[^，。；;\n]*(?:置顶|自取)[^，。；;\n]*|"
    r"[^，。；;\n]*微[^，。；;\n]{0,4}[:：]\s*置顶自取[^，。；;\n]*)"
)
EMAIL_ASCII_CONFUSABLES = {
    "a": "аɑαᥲ",
    "b": "ЬƅᏏ",
    "c": "сϲᥴⅽ",
    "d": "ԁⅾ",
    "e": "еҽєεᥱ℮",
    "f": "ғϝ",
    "g": "ɡց",
    "h": "һհᏂ",
    "i": "іɩιӏᎥı",
    "j": "јʝ",
    "k": "κкⲕ",
    "l": "ⅼӏᥣƖ",
    "m": "мⅿ",
    "n": "ոпᥒռη",
    "o": "оοօⲟ",
    "p": "рρⲣ",
    "q": "ԛզ",
    "r": "гᴦ",
    "s": "ѕꜱ",
    "t": "тτ",
    "u": "υսᥙᴜ",
    "v": "νѵ",
    "w": "ԝա",
    "x": "хχ",
    "y": "уүγ",
    "z": "ᴢΖ",
    "0": "ΟОՕօ०",
    "1": "ΙІӀ",
}
EMAIL_HOMOGLYPH_TRANSLATION = str.maketrans(
    {
        char: ascii_char
        for ascii_char, confusables in EMAIL_ASCII_CONFUSABLES.items()
        for char in confusables
    }
)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()


def _normalize_email_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = normalized.translate(EMAIL_HOMOGLYPH_TRANSLATION)
    normalized = "".join(
        char for char in normalized if not unicodedata.category(char).startswith("M")
    )
    normalized = re.sub(r"\.c(?:[^\w\s@.]|\ufe0f){1,4}m\b", ".com", normalized)
    normalized = re.sub(
        r"([1-9]\d{4,11})\s*(?:🐧|企鹅|QQ|qq|q|Q)\s*(?:\.|点)\s*(?:📧|邮箱|mail|MAIL)",
        r"\1@qq.com",
        normalized,
    )
    normalized = re.sub(
        r"([1-9]\d{4,11})(?:\s|[^\w@]){0,12}(?:🐧+|企鹅|QQ|qq|q|Q)\s*(?:[.·・点]\s*)?(?:com|c\s*(?:🔘|⭕|○|o|O|0)?\s*m|📧|邮箱|mail|MAIL)",
        r"\1@qq.com",
        normalized,
    )
    return normalized


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
    email_text = _normalize_email_text(text)
    leads: List[ContactLead] = []

    for match in EMAIL_RE.finditer(email_text):
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

    for match in OBFUSCATED_EMAIL_RE.finditer(email_text):
        email = f"{match.group(1).lower()}@{match.group(2).lower()}.{match.group(3).lower()}"
        leads.append(
            ContactLead(
                account_id=account_id,
                lead_type="email",
                normalized_value=email,
                raw_snippet=match.group(0).strip(" ，。;；"),
                confidence=0.9,
                extractor_name="obfuscated_email_regex",
                source_field="bio",
                dedupe_key=f"email:{email}",
            )
        )

    for match in OBFUSCATED_QQ_EMAIL_RE.finditer(email_text):
        email = f"{match.group(1)}@qq.com"
        leads.append(
            ContactLead(
                account_id=account_id,
                lead_type="email",
                normalized_value=email,
                raw_snippet=match.group(0).strip(" ，。;；"),
                confidence=0.92,
                extractor_name="obfuscated_qq_email_regex",
                source_field="bio",
                dedupe_key=f"email:{email}",
            )
        )

    for match in QQ_MAIL_LABEL_RE.finditer(email_text):
        email = f"{match.group(1)}@qq.com"
        leads.append(
            ContactLead(
                account_id=account_id,
                lead_type="email",
                normalized_value=email,
                raw_snippet=match.group(0).strip(" ，。;；"),
                confidence=0.9,
                extractor_name="qq_mail_label_regex",
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

    for match in REMARK_CONTACT_ID_RE.finditer(text):
        value = match.group(1).lower()
        leads.append(
            ContactLead(
                account_id=account_id,
                lead_type="wechat",
                normalized_value=value,
                raw_snippet=match.group(0).strip(" ，。;；"),
                confidence=0.76,
                extractor_name="remark_contact_id_regex",
                source_field="bio",
                dedupe_key=f"wechat:{value}",
            )
        )

    for match in BUSINESS_CONTACT_ID_RE.finditer(text):
        value = match.group(1).lower()
        leads.append(
            ContactLead(
                account_id=account_id,
                lead_type="wechat",
                normalized_value=value,
                raw_snippet=match.group(0).strip(" ，。;；"),
                confidence=0.74,
                extractor_name="business_contact_id_regex",
                source_field="bio",
                dedupe_key=f"wechat:{value}",
            )
        )

    for match in QQ_RE.finditer(text):
        value = match.group(1)
        leads.append(
            ContactLead(
                account_id=account_id,
                lead_type="qq",
                normalized_value=value,
                raw_snippet=match.group(0).strip(" ，。;；"),
                confidence=0.78,
                extractor_name="qq_regex",
                source_field="bio",
                dedupe_key=f"qq:{value}",
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

    for match in REDIRECT_ACCOUNT_RE.finditer(text):
        snippet = match.group(1).strip(" ，。;；")
        leads.append(
            ContactLead(
                account_id=account_id,
                lead_type="other_hint",
                normalized_value=snippet,
                raw_snippet=snippet,
                confidence=0.46,
                extractor_name="redirect_account_regex",
                source_field="bio",
                dedupe_key=f"other_hint:{snippet}",
            )
        )

    for match in SOFT_WECHAT_HINT_RE.finditer(text):
        snippet = match.group(1).strip(" ，。;；")
        leads.append(
            ContactLead(
                account_id=account_id,
                lead_type="other_hint",
                normalized_value=snippet,
                raw_snippet=snippet,
                confidence=0.4,
                extractor_name="soft_wechat_hint_regex",
                source_field="bio",
                dedupe_key=f"other_hint:{snippet}",
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
