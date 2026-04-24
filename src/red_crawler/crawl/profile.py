from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from red_crawler.models import AccountRecord
from red_crawler.profile_url import extract_account_id_from_profile_url

DEFAULT_BASE_URL = "https://www.xiaohongshu.com"
FAILURE_TEXT_MARKERS = (
    "未连接到服务器，刷新一下试试",
    "点击刷新",
)


def _text_from_first(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = re.sub(r"\s+", " ", " ".join(node.stripped_strings)).strip()
            if text:
                return text
    return ""


def _parse_interaction_counts(soup: BeautifulSoup) -> dict[str, str]:
    interaction_map: dict[str, str] = {}
    for item in soup.select(".data-info .user-interactions > div, .user-interactions > div"):
        count = _text_from_first(item, [".count"])
        label = _text_from_first(item, [".shows"])
        if count and label:
            interaction_map[label] = count
    return interaction_map


def _extract_account_id(text: str, profile_url: str) -> str:
    match = re.search(r"账号ID[:：]?\s*([A-Za-z0-9_-]+)", text)
    if match:
        return match.group(1)
    return extract_account_id_from_profile_url(profile_url)


def parse_profile_html(
    html: str,
    profile_url: str,
    source_type: str,
    source_from: Optional[str],
) -> AccountRecord:
    soup = BeautifulSoup(html, "html.parser")
    container_text = soup.get_text(" ", strip=True)
    if any(marker in container_text for marker in FAILURE_TEXT_MARKERS):
        raise ValueError("profile page did not load: server connection error page")

    tags = [
        " ".join(tag.stripped_strings)
        for tag in soup.select(".user-tags span, .profile-tags span, .tag, .user-tags .tag-item")
        if " ".join(tag.stripped_strings)
    ]

    visible_metadata = {}
    location = _text_from_first(soup, [".user-location", "[data-field='location']"])
    followers = _text_from_first(
        soup, [".user-followers", "[data-field='followers']", ".followers"]
    )
    red_id_text = _text_from_first(soup, [".user-redId"])
    ip_location_text = _text_from_first(soup, [".user-IP"])
    if location:
        visible_metadata["location"] = location
    if followers:
        followers = re.sub(r"^粉丝\s*", "", followers)
        visible_metadata["followers"] = followers
    if red_id_text:
        visible_metadata["red_id"] = re.sub(r"^小红书号[:：]?\s*", "", red_id_text)
    if ip_location_text:
        visible_metadata["ip_location"] = re.sub(r"^IP属地[:：]?\s*", "", ip_location_text).strip()
    if tags:
        visible_metadata["tags"] = tags
    interaction_map = _parse_interaction_counts(soup)
    if interaction_map.get("关注"):
        visible_metadata["following"] = interaction_map["关注"]
    if interaction_map.get("粉丝"):
        visible_metadata["followers"] = interaction_map["粉丝"]
    if interaction_map.get("获赞与收藏"):
        visible_metadata["likes_and_collects"] = interaction_map["获赞与收藏"]

    nickname = _text_from_first(
        soup,
        ["h1.user-name", ".user-name", "h1.nickname", "[data-testid='user-name']", ".user-basic .user-name"],
    )
    bio_text = _text_from_first(
        soup,
        [".user-bio", ".desc", "[data-testid='user-bio']", ".profile-desc", ".user-desc"],
    )
    account_id = _extract_account_id(container_text, profile_url)
    if not nickname and not bio_text and not visible_metadata:
        raise ValueError("profile page did not load: expected profile content missing")

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
    discovery_depth: int = 0,
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
        discovery_depth=discovery_depth,
    )
