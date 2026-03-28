from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List
from urllib.parse import quote, urljoin

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright


class RiskControlTriggered(RuntimeError):
    pass


HIGH_RISK_PAGE_MARKERS = {
    "verification": (
        "安全验证",
        "请完成验证",
        "请完成安全验证",
        "验证后继续访问",
    ),
    "login_required": (
        "登录后查看更多",
        "登录后查看",
        "请先登录",
        "扫码登录",
    ),
}


def classify_high_risk_page(body_text: str) -> str | None:
    text = body_text.strip()
    for risk_type, markers in HIGH_RISK_PAGE_MARKERS.items():
        if any(marker in text for marker in markers):
            return risk_type
    return None


@dataclass
class SafeModeController:
    enabled: bool
    sleep_fn: Callable[[float], None] = time.sleep
    log_fn: Callable[[str], None] = lambda _message: None
    rng: random.Random = field(default_factory=random.Random)
    pause_every: int = 5
    risk_threshold: int = 2
    request_count: int = 0
    consecutive_risk_events: int = 0

    def before_request(self) -> None:
        if not self.enabled:
            return
        self.request_count += 1
        delay = self.rng.uniform(1.5, 3.5)
        self.log_fn(f"safe-mode: sleeping {delay:.1f}s before request #{self.request_count}")
        self.sleep_fn(delay)
        if self.request_count % self.pause_every == 0:
            pause = self.rng.uniform(8.0, 15.0)
            self.log_fn(
                f"safe-mode: taking a longer {pause:.1f}s pause after {self.request_count} requests"
            )
            self.sleep_fn(pause)

    def on_risk_event(self, reason: str | None = None) -> None:
        if not self.enabled:
            return
        self.consecutive_risk_events += 1
        pause = self.rng.uniform(20.0, 40.0)
        reason_suffix = f" ({reason})" if reason else ""
        self.log_fn(
            f"safe-mode: backing off for {pause:.1f}s after risk signal #{self.consecutive_risk_events}{reason_suffix}"
        )
        self.sleep_fn(pause)
        if self.consecutive_risk_events >= self.risk_threshold:
            self.log_fn(
                "safe-mode: circuit breaker triggered after "
                f"{self.consecutive_risk_events} consecutive risk signals"
            )
            raise RiskControlTriggered("risk control threshold reached")

    def on_success(self) -> None:
        self.consecutive_risk_events = 0


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
    def __init__(
        self,
        session: BrowserSession,
        base_url: str = "https://www.xiaohongshu.com",
        safe_mode: bool = False,
        safe_mode_controller: SafeModeController | None = None,
    ):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.safe_mode_controller = safe_mode_controller or SafeModeController(
            enabled=safe_mode,
            log_fn=print if safe_mode else (lambda _message: None),
        )

    def _load_html(self, url: str) -> str:
        self.safe_mode_controller.before_request()
        page = self.session.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if response is not None and response.status >= 400:
                self.safe_mode_controller.on_risk_event(reason=f"http_{response.status}")
                raise RuntimeError(f"page request failed with status {response.status}")
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            body_text = page.locator("body").inner_text()
            risk_type = classify_high_risk_page(body_text)
            if risk_type is not None:
                self.safe_mode_controller.on_risk_event(reason=risk_type)
                raise RuntimeError(f"high risk page detected: {risk_type}")
            if "未连接到服务器，刷新一下试试" in body_text:
                self.safe_mode_controller.on_risk_event(reason="server_connection_error")
                page.reload(wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
            self.safe_mode_controller.on_success()
            return page.content()
        finally:
            page.close()

    def _load_search_result_htmls(self, url: str, scroll_rounds: int = 3) -> List[str]:
        self.safe_mode_controller.before_request()
        page = self.session.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if response is not None and response.status >= 400:
                self.safe_mode_controller.on_risk_event(reason=f"http_{response.status}")
                raise RuntimeError(f"page request failed with status {response.status}")
            html_snapshots: List[str] = []
            last_length = -1

            for _ in range(scroll_rounds + 1):
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                body_text = page.locator("body").inner_text()
                risk_type = classify_high_risk_page(body_text)
                if risk_type is not None:
                    self.safe_mode_controller.on_risk_event(reason=risk_type)
                    raise RuntimeError(f"high risk page detected: {risk_type}")
                html = page.content()
                if html not in html_snapshots:
                    html_snapshots.append(html)

                card_count = page.locator(".card-bottom-wrapper a.author[href*='/user/profile/']").count()
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1200)
                if card_count == last_length:
                    break
                last_length = card_count

            self.safe_mode_controller.on_success()
            return html_snapshots
        finally:
            page.close()

    def fetch_profile_html(self, profile_url: str) -> str:
        return self._load_html(profile_url)

    def fetch_note_recommendation_html(self, profile_url: str) -> List[str]:
        profile_html = self.fetch_profile_html(profile_url)
        note_links = extract_note_detail_urls(profile_html, self.base_url, max_results=3)
        return [self._load_html(note_url) for note_url in note_links]

    def fetch_search_result_htmls(self, query: str) -> List[str]:
        search_url = f"{self.base_url}/search_result?keyword={quote(query)}&source=web_explore_feed"
        return self._load_search_result_htmls(search_url)


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
