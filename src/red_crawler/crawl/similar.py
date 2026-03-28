from __future__ import annotations

from collections import deque
from typing import Dict, List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

DEFAULT_BASE_URL = "https://www.xiaohongshu.com"


def _extract_account_id_from_url(profile_url: str) -> str:
    return urlparse(profile_url).path.rstrip("/").split("/")[-1]


def extract_similar_profiles(
    html: str,
    base_profile_url: str,
    max_results: int,
) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    base_account_id = _extract_account_id_from_url(base_profile_url)
    containers = soup.select(
        "section.recommend-users, .recommend-users, .recommended-users, "
        ".recommend-user-list, .user-recommend-list, [data-testid='recommend-users']"
    )
    seen = set()
    results: List[Dict[str, str]] = []

    for container in containers:
        for anchor in container.select("a[href*='/user/profile/']"):
            href = anchor.get("href", "").strip()
            if not href:
                continue
            profile_url = urljoin(base_profile_url or DEFAULT_BASE_URL, href)
            account_id = anchor.get("data-user-id") or _extract_account_id_from_url(profile_url)
            if not account_id or account_id in seen or account_id == base_account_id:
                continue
            nickname = " ".join(anchor.stripped_strings)
            seen.add(account_id)
            results.append(
                {
                    "account_id": account_id,
                    "profile_url": profile_url,
                    "nickname": nickname,
                }
            )
            if len(results) >= max_results:
                return results

    if results:
        return results

    for anchor in soup.select(".comment-inner-container .author-wrapper a[href*='/user/profile/']"):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        profile_url = urljoin(base_profile_url or DEFAULT_BASE_URL, href)
        account_id = _extract_account_id_from_url(profile_url)
        if not account_id or account_id in seen or account_id == base_account_id:
            continue
        nickname = " ".join(anchor.stripped_strings)
        if not nickname:
            continue
        seen.add(account_id)
        results.append(
            {
                "account_id": account_id,
                "profile_url": profile_url,
                "nickname": nickname,
            }
        )
        if len(results) >= max_results:
            break
    return results


def expand_recommendation_graph(
    seed_account_id: str,
    graph: Dict[str, List[str]],
    max_accounts: int,
    max_depth: int,
) -> List[str]:
    visited = []
    seen = {seed_account_id}
    queue = deque([(seed_account_id, 0)])

    while queue and len(visited) < max_accounts:
        account_id, depth = queue.popleft()
        visited.append(account_id)
        if depth >= max_depth:
            continue
        for neighbor in graph.get(account_id, []):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append((neighbor, depth + 1))
    return visited
