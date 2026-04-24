from __future__ import annotations

from urllib.parse import urljoin, urlparse

DEFAULT_BASE_URL = "https://www.xiaohongshu.com"


def resolve_profile_url(profile_url: str, base_url: str = DEFAULT_BASE_URL) -> str:
    return urljoin(f"{base_url.rstrip('/')}/", profile_url)


def extract_account_id_from_profile_url(profile_url: str) -> str:
    path_parts = [part for part in urlparse(profile_url).path.split("/") if part]
    for index in range(len(path_parts) - 2):
        if path_parts[index] == "user" and path_parts[index + 1] == "profile":
            return path_parts[index + 2]
    if path_parts:
        return path_parts[-1]
    return profile_url


def canonicalize_profile_url(profile_url: str, base_url: str = DEFAULT_BASE_URL) -> str:
    resolved = resolve_profile_url(profile_url, base_url=base_url)
    parsed = urlparse(resolved)
    account_id = extract_account_id_from_profile_url(resolved)
    if not account_id:
        return resolved
    scheme = parsed.scheme or urlparse(base_url).scheme or "https"
    netloc = parsed.netloc or urlparse(base_url).netloc
    return f"{scheme}://{netloc}/user/profile/{account_id}"


def build_profile_dedupe_key(
    profile_url: str,
    account_id: str = "",
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> str:
    normalized_account_id = account_id.strip() or extract_account_id_from_profile_url(profile_url)
    if normalized_account_id:
        return f"account:{normalized_account_id}"
    return f"url:{canonicalize_profile_url(profile_url, base_url=base_url)}"
