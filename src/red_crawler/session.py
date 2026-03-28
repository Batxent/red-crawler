from __future__ import annotations

import re
from pathlib import Path
from typing import List
from urllib.parse import quote, urljoin

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright


class BrowserSession:
    def __init__(self, storage_state: str, headless: bool = True):
        self.storage_state = str(storage_state)
        self.headless = headless
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None

    def __enter__(self) -> "BrowserSession":
        storage_state_path = Path(self.storage_state)
        if not storage_state_path.exists():
            raise FileNotFoundError(
                f"storage state file not found: {storage_state_path.as_posix()}"
            )
        self._playwright = sync_playwright().start()
        browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = browser.new_context(storage_state=self.storage_state)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._context is not None:
            self._context.browser.close()
            self._context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("browser session is not started")
        return self._context

    def new_page(self) -> Page:
        return self.context.new_page()


class PlaywrightCrawlerClient:
    def __init__(self, session: BrowserSession, base_url: str = "https://www.xiaohongshu.com"):
        self.session = session
        self.base_url = base_url.rstrip("/")

    def _load_html(self, url: str) -> str:
        page = self.session.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if response is not None and response.status >= 400:
                raise RuntimeError(f"page request failed with status {response.status}")
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            body_text = page.locator("body").inner_text()
            if "未连接到服务器，刷新一下试试" in body_text:
                page.reload(wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
            return page.content()
        finally:
            page.close()

    def fetch_profile_html(self, profile_url: str) -> str:
        return self._load_html(profile_url)

    def fetch_note_recommendation_html(self, profile_url: str) -> List[str]:
        profile_html = self.fetch_profile_html(profile_url)
        note_links = extract_note_detail_urls(profile_html, self.base_url, max_results=3)
        return [self._load_html(note_url) for note_url in note_links]

    def fetch_search_result_html(self, query: str) -> str:
        search_url = f"{self.base_url}/search_result?keyword={quote(query)}&source=web_explore_feed"
        return self._load_html(search_url)


def save_login_storage_state(
    output_path: str | Path,
    login_url: str = "https://www.xiaohongshu.com",
) -> None:
    state_path = Path(output_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
            print("登录完成后，回到终端按回车保存 storage_state...", end="", flush=True)
            with open("/dev/tty", "r", encoding="utf-8") as tty:
                tty.readline()
            context.storage_state(path=str(state_path))
            print(f"\nsaved to {state_path}")
        finally:
            browser.close()


def open_xiaohongshu(
    storage_state: str | Path,
    open_url: str = "https://www.xiaohongshu.com",
) -> None:
    storage_state_path = Path(storage_state)
    if not storage_state_path.exists():
        raise FileNotFoundError(
            f"storage state file not found: {storage_state_path.as_posix()}"
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(storage_state_path))
        page = context.new_page()
        try:
            page.goto(open_url, wait_until="domcontentloaded", timeout=30000)
            print("浏览器已打开，回到终端按回车关闭会话...", end="", flush=True)
            with open("/dev/tty", "r", encoding="utf-8") as tty:
                tty.readline()
        finally:
            browser.close()


def extract_note_detail_urls(
    profile_html: str,
    base_url: str = "https://www.xiaohongshu.com",
    max_results: int = 3,
) -> List[str]:
    note_links: List[str] = []
    for href in re.findall(r'href="([^"]*/user/profile/[^"]+xsec_source=pc_user[^"]*)"', profile_html):
        resolved = urljoin(f"{base_url.rstrip('/')}/", href.replace("&amp;", "&"))
        if resolved not in note_links:
            note_links.append(resolved)
        if len(note_links) >= max_results:
            break
    return note_links
