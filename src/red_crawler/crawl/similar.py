from __future__ import annotations

from collections import deque
import re
from typing import Dict, List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

DEFAULT_BASE_URL = "https://www.xiaohongshu.com"
DOMAIN_CLUSTERS = {
    "beauty": ("美妆", "护肤", "彩妆", "化妆", "妆容", "试色", "口红", "成分"),
    "fashion": ("穿搭", "时尚", "搭配", "OOTD"),
    "lifestyle": ("探店", "旅行", "美食"),
}
DOMAIN_HINTS = tuple(hint for hints in DOMAIN_CLUSTERS.values() for hint in hints)
SEARCH_QUERY_GROUPS = {
    "beauty": ("美妆博主", "护肤博主", "彩妆博主", "化妆博主"),
    "fashion": ("穿搭博主", "时尚博主", "搭配博主", "OOTD"),
    "lifestyle": ("探店博主", "旅行博主", "美食博主"),
}
TOPIC_QUERY_HINTS = (
    ("抗痘", "抗痘博主"),
    ("长痘", "抗痘博主"),
    ("痘肌", "痘肌护肤"),
    ("敏感肌", "敏感肌护肤"),
    ("油痘肌", "油痘肌护肤"),
)
STUDIO_HINTS = ("工作室", "机构", "官方", "品牌", "公司", "团队", "MCN")
PRO_ARTIST_HINTS = ("化妆师", "彩妆师", "makeup artist", "Makeup Artist")
CREATOR_HINTS = DOMAIN_HINTS + ("博主", "分享", "教程")


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

    return results


def extract_search_result_profiles(
    html: str,
    max_results: int,
    base_url: str = DEFAULT_BASE_URL,
) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    results: List[Dict[str, str]] = []

    for anchor in soup.select(".card-bottom-wrapper a.author[href*='/user/profile/']"):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        profile_url = urljoin(f"{base_url.rstrip('/')}/", href)
        account_id = _extract_account_id_from_url(profile_url)
        nickname = re.sub(r"\s+\d{2,4}[-/]\d{1,2}[-/]\d{1,2}$", "", " ".join(anchor.stripped_strings)).strip()
        nickname = re.sub(r"\s+\d{1,2}-\d{1,2}$", "", nickname).strip()
        if not account_id or account_id in seen or not nickname:
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


def build_search_queries(seed_account: Dict[str, object]) -> List[str]:
    visible_metadata = seed_account.get("visible_metadata", {}) or {}
    tags = visible_metadata.get("tags", []) or []
    if isinstance(tags, str):
        tags = [tags]

    queries = []
    matched_cluster = _matched_cluster(
        {
            "bio_text": seed_account.get("bio_text", ""),
            "visible_metadata": {"tags": tags},
        }
    )
    if matched_cluster is not None:
        queries.extend(SEARCH_QUERY_GROUPS[matched_cluster])
    else:
        for cluster_name, cluster_hints in DOMAIN_CLUSTERS.items():
            for hint in cluster_hints:
                if hint in str(seed_account.get("bio_text", "")):
                    queries.extend(SEARCH_QUERY_GROUPS[cluster_name])
                    break
            if queries:
                break

    seed_text = _account_text(seed_account)
    for hint, query in TOPIC_QUERY_HINTS:
        if hint in seed_text:
            queries.append(query)

    seen = set()
    deduped = []
    for query in queries:
        query = re.sub(r"\s+", " ", query).strip()
        if query and query not in seen:
            seen.add(query)
            deduped.append(query)
    return deduped


def parse_follower_count(value: str) -> float:
    text = value.strip()
    if not text:
        return 0
    multiplier = 1
    if text.endswith("万"):
        multiplier = 10000
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return 0


def _account_text(account: Dict[str, object]) -> str:
    meta = account.get("visible_metadata", {}) or {}
    return " ".join(
        [str(account.get("nickname", "")), str(account.get("bio_text", ""))]
        + list(meta.get("tags", []) or [])
    )


def _matched_cluster(seed_account: Dict[str, object]) -> str | None:
    seed_text = _account_text(seed_account)
    for cluster_name, hints in DOMAIN_CLUSTERS.items():
        if any(hint in seed_text for hint in hints):
            return cluster_name
    return None


def classify_creator_segment(account: Dict[str, object]) -> str:
    text = _account_text(account)
    lowered = text.lower()
    if any(hint.lower() in lowered for hint in STUDIO_HINTS):
        return "studio"
    if any(hint.lower() in lowered for hint in PRO_ARTIST_HINTS):
        return "professional_artist"
    if any(hint.lower() in lowered for hint in CREATOR_HINTS):
        return "creator"
    return "general"


def score_creator_relevance(
    seed_account: Dict[str, object],
    candidate_account: Dict[str, object],
) -> float:
    candidate_meta = candidate_account.get("visible_metadata", {}) or {}
    candidate_followers = parse_follower_count(str(candidate_meta.get("followers", "")))
    candidate_text = _account_text(candidate_account)
    segment = classify_creator_segment(candidate_account)
    score = 0.0

    matched_cluster = _matched_cluster(seed_account)
    if matched_cluster is None:
        score += 0.25 if "博主" in candidate_text else 0.0
    else:
        cluster_hints = DOMAIN_CLUSTERS[matched_cluster]
        if any(hint in candidate_text for hint in cluster_hints):
            score += 0.55
        else:
            return 0.0

    if candidate_followers >= 500_000:
        score += 0.28
    elif candidate_followers >= 100_000:
        score += 0.22
    elif candidate_followers >= 10_000:
        score += 0.15
    elif candidate_followers >= 1_000:
        score += 0.08

    if segment == "creator":
        score += 0.17
    elif segment == "professional_artist":
        score += 0.08
    elif segment == "studio":
        score -= 0.12

    return round(max(0.0, min(score, 1.0)), 2)


def is_relevant_creator_candidate(
    seed_account: Dict[str, object],
    candidate_account: Dict[str, object],
    min_followers: int = 1000,
) -> bool:
    candidate_meta = candidate_account.get("visible_metadata", {}) or {}
    candidate_followers = parse_follower_count(str(candidate_meta.get("followers", "")))
    if candidate_followers < min_followers:
        return False
    return score_creator_relevance(seed_account, candidate_account) >= 0.7


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
