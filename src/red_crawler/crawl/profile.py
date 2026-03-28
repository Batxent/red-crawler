from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from red_crawler.models import AccountRecord

DEFAULT_BASE_URL = "https://www.xiaohongshu.com"


def _text_from_first(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = " ".join(node.stripped_strings)
            if text:
                return text
    return ""


def _extract_account_id(text: str, profile_url: str) -> str:
    match = re.search(r"账号ID[:：]?\s*([A-Za-z0-9_-]+)", text)
    if match:
        return match.group(1)
    path = urlparse(profile_url).path.rstrip("/")
    if path:
        return path.split("/")[-1]
    return profile_url


def parse_profile_html(
    html: str,
    profile_url: str,
    source_type: str,
    source_from: Optional[str],
) -> AccountRecord:
    soup = BeautifulSoup(html, "html.parser")
    container_text = soup.get_text(" ", strip=True)

    tags = [
        " ".join(tag.stripped_strings)
        for tag in soup.select(".user-tags span, .profile-tags span, .tag")
        if " ".join(tag.stripped_strings)
    ]

    visible_metadata = {}
    location = _text_from_first(soup, [".user-location", "[data-field='location']"])
    followers = _text_from_first(
        soup, [".user-followers", "[data-field='followers']", ".followers"]
    )
    if location:
        visible_metadata["location"] = location
    if followers:
        followers = re.sub(r"^粉丝\s*", "", followers)
        visible_metadata["followers"] = followers
    if tags:
        visible_metadata["tags"] = tags

    nickname = _text_from_first(
        soup,
        ["h1.user-name", ".user-name", "h1.nickname", "[data-testid='user-name']"],
    )
    bio_text = _text_from_first(
        soup,
        [".user-bio", ".desc", "[data-testid='user-bio']", ".profile-desc"],
    )
    account_id = _extract_account_id(container_text, profile_url)

    return AccountRecord(
        account_id=account_id,
        profile_url=profile_url,
        nickname=nickname or account_id,
        bio_text=bio_text,
        visible_metadata=visible_metadata,
        source_type=source_type,
        source_from=source_from,
        crawl_status="success",
        crawl_error=None,
    )


def build_failed_account_record(
    profile_url: str,
    source_type: str,
    source_from: Optional[str],
    error: str,
) -> AccountRecord:
    return AccountRecord(
        account_id=_extract_account_id("", profile_url),
        profile_url=profile_url,
        nickname="",
        bio_text="",
        visible_metadata={},
        source_type=source_type,
        source_from=source_from,
        crawl_status="failed",
        crawl_error=error,
    )
