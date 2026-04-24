from __future__ import annotations

import hashlib
import json
import os
import pickle
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List
from urllib.parse import quote, urljoin

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright
from playwright_stealth import Stealth
from browserforge.injectors.playwright import NewContext
from browserforge.fingerprints import FingerprintGenerator, Fingerprint
from red_crawler.profile_url import (
    canonicalize_profile_url,
    extract_account_id_from_profile_url,
)


class RiskControlTriggered(RuntimeError):
    pass


def apply_stealth(page: Page) -> None:
    Stealth().apply_stealth_sync(page)


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
SEARCH_INPUT_SELECTORS = (
    "input[type='search']",
    "input[placeholder*='搜索']",
    "input[placeholder*='搜']",
    ".search-input input",
    ".search-bar input",
    ".search-container input",
)
BACK_BUTTON_SELECTORS = (
    "button[aria-label='返回']",
    "[aria-label='返回']",
    ".back-button",
    "button.back",
    ".back",
    ".nav-back",
    ".left-area .back",
)
SEARCH_RESULT_CARD_SELECTOR = ".card-bottom-wrapper a.author[href*='/user/profile/']"


def _get_or_create_fingerprint(storage_state_path: Path) -> Fingerprint:
    fp_path = storage_state_path.with_suffix(".fingerprint.pkl")
    if fp_path.exists():
        try:
            with open(fp_path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    fp = FingerprintGenerator(os=("windows",)).generate()
    try:
        if not storage_state_path.parent.exists():
            storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(fp_path, "wb") as f:
            pickle.dump(fp, f)
    except Exception:
        pass
    return fp


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
    pause_every: int = 4
    risk_threshold: int = 2
    request_count: int = 0
    consecutive_risk_events: int = 0

    def before_request(self) -> None:
        if not self.enabled:
            return
        self.request_count += 1
        delay = self.rng.uniform(12.0, 28.0)
        self.log_fn(
            f"safe-mode: sleeping {delay:.1f}s before request #{self.request_count}"
        )
        self.sleep_fn(delay)
        if self.request_count % self.pause_every == 0:
            pause = self.rng.uniform(80.0, 210.0)
            self.log_fn(
                f"safe-mode: taking a longer {pause:.1f}s pause after {self.request_count} requests"
            )
            self.sleep_fn(pause)

    def after_page_load(self, page: Page, *, page_kind: str) -> None:
        if not self.enabled:
            return
        dwell = (
            self.rng.uniform(7.0, 16.0)
            if page_kind == "search"
            else self.rng.uniform(10.0, 24.0)
        )
        self.log_fn(f"safe-mode: dwelling {dwell:.1f}s on {page_kind} page")
        self.sleep_fn(dwell)

        if page_kind != "profile":
            return

        if self.rng.random() < 0.82:
            self._perform_human_scroll(
                page,
                max_steps=3,
                min_ratio=0.12,
                max_ratio=0.34,
                settle_min=2.5,
                settle_max=5.5,
                page_kind=page_kind,
            )

            if self.rng.random() < 0.4:
                self._perform_human_scroll(
                    page,
                    max_steps=2,
                    min_ratio=0.2,
                    max_ratio=0.4,
                    settle_min=4.0,
                    settle_max=8.5,
                    page_kind=page_kind,
                )

    def after_search_scroll(self, *, round_number: int) -> None:
        if not self.enabled:
            return
        settle = self.rng.uniform(3.5, 8.0)
        self.log_fn(
            f"safe-mode: settling for {settle:.1f}s after search scroll #{round_number}"
        )
        self.sleep_fn(settle)

    def perform_search_scroll(self, page: Page, *, round_number: int) -> None:
        if not self.enabled:
            self._wheel_scroll(page, delta_ratio=0.95)
            return
        self._perform_human_scroll(
            page,
            max_steps=3,
            min_ratio=0.16,
            max_ratio=0.3,
            settle_min=1.2,
            settle_max=3.2,
            page_kind="search",
        )
        if self.rng.random() < 0.22:
            self._wheel_scroll(page, delta_ratio=-0.10)
            reverse_settle = self.rng.uniform(0.8, 2.0)
            self.log_fn(
                f"safe-mode: settling for {reverse_settle:.1f}s after a short reverse scroll on search page"
            )
            self.sleep_fn(reverse_settle)
        self.after_search_scroll(round_number=round_number)

    def inspect_search_result(
        self,
        page: Page,
        anchor: object,
        *,
        result_index: int,
    ) -> None:
        if not self.enabled:
            return
        try:
            hover = getattr(anchor, "hover", None)
            if callable(hover):
                hover(timeout=5000)
        except Exception:
            pass
        hover_settle = self.rng.uniform(0.9, 2.4)
        self.log_fn(
            f"safe-mode: pausing {hover_settle:.1f}s while inspecting search result #{result_index}"
        )
        self.sleep_fn(hover_settle)
        try:
            bounding_box = getattr(anchor, "bounding_box", None)
            box = bounding_box() if callable(bounding_box) else None
            if box:
                self._move_mouse_to_box(page, box)
        except Exception:
            pass

    def reorient_on_search_page(self, page: Page) -> None:
        if not self.enabled:
            return
        if self.rng.random() < 0.58:
            direction = -1 if self.rng.random() < 0.45 else 1
            ratio = self.rng.uniform(0.04, 0.11)
            self._wheel_scroll(page, delta_ratio=direction * ratio)
            settle = self.rng.uniform(0.8, 1.9)
            self.log_fn(
                f"safe-mode: settling for {settle:.1f}s while reorienting on search page"
            )
            self.sleep_fn(settle)

    def _perform_human_scroll(
        self,
        page: Page,
        *,
        max_steps: int,
        min_ratio: float,
        max_ratio: float,
        settle_min: float,
        settle_max: float,
        page_kind: str,
    ) -> None:
        step_count = max(1, min(max_steps, int(self.rng.uniform(1, max_steps + 0.999))))
        for step_index in range(step_count):
            scroll_ratio = self.rng.uniform(min_ratio, max_ratio)
            self._move_mouse_to_reading_zone(page)
            self._wheel_scroll(page, delta_ratio=scroll_ratio)
            settle = self.rng.uniform(settle_min, settle_max)
            self.log_fn(
                f"safe-mode: settling for {settle:.1f}s after scroll step {step_index + 1} on {page_kind} page"
            )
            self.sleep_fn(settle)

    def click_search_result(self, page: Page, anchor: object, *, timeout: int) -> bool:
        try:
            bounding_box = getattr(anchor, "bounding_box", None)
            box = bounding_box() if callable(bounding_box) else None
            if box:
                x, y, steps = self._move_mouse_to_box(page, box)
                mouse = getattr(page, "mouse", None)
                if mouse is not None:
                    click = getattr(mouse, "click", None)
                    if callable(click):
                        click(x, y, delay=round(self.rng.uniform(40, 140)))
                        return True
                    down = getattr(mouse, "down", None)
                    up = getattr(mouse, "up", None)
                    if callable(down) and callable(up):
                        down()
                        up()
                        return True
        except Exception:
            pass
        if not self.enabled:
            try:
                click = getattr(anchor, "click", None)
                if callable(click):
                    click(timeout=timeout)
                    return True
            except Exception:
                pass
        return False

    def click_locator_with_mouse(self, page: Page, locator: object) -> bool:
        try:
            bounding_box = getattr(locator, "bounding_box", None)
            box = bounding_box() if callable(bounding_box) else None
            if not box:
                return False
            x, y, _steps = self._move_mouse_to_box(page, box)
            mouse = getattr(page, "mouse", None)
            if mouse is None:
                return False
            click = getattr(mouse, "click", None)
            if callable(click):
                click(x, y, delay=round(self.rng.uniform(40, 140)))
                return True
            down = getattr(mouse, "down", None)
            up = getattr(mouse, "up", None)
            if callable(down) and callable(up):
                down()
                up()
                return True
        except Exception:
            pass
        return False

    def _move_mouse_to_reading_zone(self, page: Page) -> None:
        mouse = getattr(page, "mouse", None)
        if mouse is None:
            return
        width, height = self._viewport_dimensions(page)
        x_ratio = self.rng.uniform(0.34, 0.72)
        y_ratio = self.rng.uniform(0.18, 0.68)
        steps = max(4, int(self.rng.uniform(4, 10)))
        try:
            mouse.move(width * x_ratio, height * y_ratio, steps=steps)
        except Exception:
            pass

    def _move_mouse_to_box(self, page: Page, box: dict[str, float]) -> tuple[float, float, int]:
        mouse = getattr(page, "mouse", None)
        offset_x = self.rng.uniform(0.35, 0.68)
        offset_y = self.rng.uniform(0.28, 0.72)
        steps = max(4, int(self.rng.uniform(4, 10)))
        x = box["x"] + box["width"] * offset_x
        y = box["y"] + box["height"] * offset_y
        if mouse is not None:
            mouse.move(x, y, steps=steps)
        return x, y, steps

    def _wheel_scroll(self, page: Page, *, delta_ratio: float) -> None:
        mouse = getattr(page, "mouse", None)
        _, height = self._viewport_dimensions(page)
        delta_y = max(1, int(abs(height * delta_ratio)))
        if delta_ratio < 0:
            delta_y = -delta_y
        if mouse is not None:
            wheel = getattr(mouse, "wheel", None)
            if callable(wheel):
                wheel(0, delta_y)
                return
        page.evaluate(
            "window.scrollBy(0, Math.round(window.innerHeight * %s))"
            % f"{delta_ratio:.2f}"
        )

    def _viewport_dimensions(self, page: Page) -> tuple[int, int]:
        viewport = getattr(page, "viewport_size", None)
        if isinstance(viewport, dict):
            width = int(viewport.get("width", 1280))
            height = int(viewport.get("height", 900))
            return width, height
        return 1280, 900

    def on_risk_event(self, reason: str | None = None) -> None:
        if not self.enabled:
            return
        self.consecutive_risk_events += 1
        pause = self.rng.uniform(150.0, 360.0)
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
    def __init__(self, storage_state: str, headless: bool = False):
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
        fp = _get_or_create_fingerprint(storage_state_path)
        self._context = NewContext(
            browser,
            fingerprint=fp,
            storage_state=self.storage_state,
        )
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
        page = self.context.new_page()
        apply_stealth(page)
        return page


class PlaywrightCrawlerClient:
    def __init__(
        self,
        session: BrowserSession,
        base_url: str = "https://www.xiaohongshu.com",
        safe_mode: bool = False,
        safe_mode_controller: SafeModeController | None = None,
        search_scroll_rounds: int = 2,
        cache_dir: str | Path | None = None,
        cache_ttl_days: int = 7,
        time_fn: Callable[[], float] = time.time,
    ):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.search_scroll_rounds = max(int(search_scroll_rounds), 0)
        self.safe_mode_controller = safe_mode_controller or SafeModeController(
            enabled=safe_mode,
            log_fn=print if safe_mode else (lambda _message: None),
        )
        self._profile_html_cache: dict[str, str] = {}
        self._search_html_cache: dict[str, List[str]] = {}
        self._page: Page | None = None
        self._page_kind: str | None = None
        self._active_search_query: str | None = None
        self._active_search_result_urls: set[str] = set()
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.cache_ttl_seconds = max(cache_ttl_days, 0) * 24 * 60 * 60
        self.time_fn = time_fn
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / "profiles").mkdir(exist_ok=True)
            (self.cache_dir / "search").mkdir(exist_ok=True)

    def _cache_path(self, kind: str, key: str) -> Path | None:
        if self.cache_dir is None:
            return None
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        suffix = ".json" if kind == "search" else ".html"
        return self.cache_dir / kind / f"{digest}{suffix}"

    def _is_cache_fresh(self, cache_path: Path) -> bool:
        if self.cache_ttl_seconds <= 0:
            return False
        age = self.time_fn() - cache_path.stat().st_mtime
        return age <= self.cache_ttl_seconds

    def _load_html(self, url: str) -> str:
        self.safe_mode_controller.before_request()
        clicked_html = self._load_profile_from_active_search_page(url)
        if clicked_html is not None:
            return clicked_html
        page = self._get_page()
        response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if response is not None and response.status >= 400:
            self.safe_mode_controller.on_risk_event(
                reason=f"http_{response.status}"
            )
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
            self.safe_mode_controller.on_risk_event(
                reason="server_connection_error"
            )
            page.reload(wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
        self._page_kind = "profile"
        self.safe_mode_controller.after_page_load(page, page_kind="profile")
        self.safe_mode_controller.on_success()
        return page.content()

    def _load_search_result_htmls(self, url: str, scroll_rounds: int = 2) -> List[str]:
        self.safe_mode_controller.before_request()
        page = self._get_page()
        response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if response is not None and response.status >= 400:
            self.safe_mode_controller.on_risk_event(
                reason=f"http_{response.status}"
            )
            raise RuntimeError(f"page request failed with status {response.status}")
        return self._capture_search_result_htmls(page, scroll_rounds=scroll_rounds)

    def _load_search_result_htmls_via_ui(
        self,
        query: str,
        *,
        scroll_rounds: int = 2,
    ) -> List[str] | None:
        self.safe_mode_controller.before_request()
        page = self._get_page()
        response = page.goto(self.base_url, wait_until="domcontentloaded", timeout=30000)
        if response is not None and response.status >= 400:
            self.safe_mode_controller.on_risk_event(
                reason=f"http_{response.status}"
            )
            raise RuntimeError(f"page request failed with status {response.status}")
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        search_input = self._first_matching_locator(page, SEARCH_INPUT_SELECTORS)
        if search_input is None:
            return None
        if not self._submit_search_query_via_input(page, search_input, query):
            return None
        return self._capture_search_result_htmls(page, scroll_rounds=scroll_rounds)

    def _capture_search_result_htmls(
        self,
        page: Page,
        *,
        scroll_rounds: int,
    ) -> List[str]:
        html_snapshots: List[str] = []
        last_length = -1
        self._page_kind = "search"
        self.safe_mode_controller.after_page_load(page, page_kind="search")

        for round_number in range(scroll_rounds + 1):
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

            card_count = page.locator(SEARCH_RESULT_CARD_SELECTOR).count()
            self.safe_mode_controller.perform_search_scroll(
                page,
                round_number=round_number + 1,
            )
            if not self.safe_mode_controller.enabled:
                page.wait_for_timeout(1200)
            if card_count == last_length:
                break
            last_length = card_count

        self.safe_mode_controller.on_success()
        return html_snapshots

    def _get_page(self) -> Page:
        if self._page is not None:
            try:
                if not self._page.is_closed():
                    return self._page
            except Exception:
                pass
        self._page = self.session.new_page()
        return self._page

    def _load_profile_from_active_search_page(self, profile_url: str) -> str | None:
        canonical_target = canonicalize_profile_url(profile_url, self.base_url)
        if canonical_target not in self._active_search_result_urls:
            return None
        page = self._get_page()
        if not self._return_to_active_search_page(page):
            return None

        target_account_id = extract_account_id_from_profile_url(profile_url)
        candidates = page.locator(SEARCH_RESULT_CARD_SELECTOR)
        try:
            count = candidates.count()
        except Exception:
            return None

        for index in range(count):
            anchor = candidates.nth(index)
            try:
                href = anchor.get_attribute("href") or ""
            except Exception:
                continue
            resolved = urljoin(f"{self.base_url.rstrip('/')}/", href)
            if (
                canonicalize_profile_url(resolved, self.base_url) != canonical_target
                and extract_account_id_from_profile_url(resolved) != target_account_id
            ):
                continue
            try:
                self.safe_mode_controller.inspect_search_result(
                    page,
                    anchor,
                    result_index=index + 1,
                )
                if not self.safe_mode_controller.click_search_result(
                    page,
                    anchor,
                    timeout=5000,
                ):
                    return None
            except Exception:
                return None
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception:
                pass
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            body_text = page.locator("body").inner_text()
            risk_type = classify_high_risk_page(body_text)
            if risk_type is not None:
                self.safe_mode_controller.on_risk_event(reason=risk_type)
                raise RuntimeError(f"high risk page detected: {risk_type}")
            self._page_kind = "profile"
            self.safe_mode_controller.after_page_load(page, page_kind="profile")
            self.safe_mode_controller.on_success()
            return page.content()
        return None

    def _return_to_active_search_page(self, page: Page) -> bool:
        if self._page_kind == "search":
            return True
        if self._active_search_query is None:
            return False
        back_button = self._first_matching_locator(page, BACK_BUTTON_SELECTORS)
        if back_button is not None:
            try:
                scroll_into_view = getattr(back_button, "scroll_into_view_if_needed", None)
                if callable(scroll_into_view):
                    scroll_into_view(timeout=5000)
            except Exception:
                pass
            if self.safe_mode_controller.click_locator_with_mouse(page, back_button):
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=30000)
                except Exception:
                    pass
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                self._page_kind = "search"
                self.safe_mode_controller.reorient_on_search_page(page)
                return True
        try:
            page.go_back(wait_until="domcontentloaded", timeout=30000)
        except Exception:
            return False
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        self._page_kind = "search"
        self.safe_mode_controller.reorient_on_search_page(page)
        return True

    def _first_matching_locator(
        self,
        page: Page,
        selectors: tuple[str, ...],
    ) -> object | None:
        for selector in selectors:
            try:
                locator = page.locator(selector)
            except Exception:
                continue
            count = getattr(locator, "count", None)
            if callable(count):
                try:
                    if count() <= 0:
                        continue
                except Exception:
                    continue
                nth = getattr(locator, "nth", None)
                if callable(nth):
                    try:
                        return nth(0)
                    except Exception:
                        continue
            return locator
        return None

    def _submit_search_query_via_input(
        self,
        page: Page,
        search_input: object,
        query: str,
    ) -> bool:
        try:
            scroll_into_view = getattr(search_input, "scroll_into_view_if_needed", None)
            if callable(scroll_into_view):
                scroll_into_view(timeout=5000)
        except Exception:
            pass
        if not self.safe_mode_controller.click_locator_with_mouse(page, search_input):
            return False
        if self.safe_mode_controller.enabled:
            settle = self.safe_mode_controller.rng.uniform(0.5, 1.4)
            self.safe_mode_controller.log_fn(
                f"safe-mode: settling for {settle:.1f}s before typing search query"
            )
            self.safe_mode_controller.sleep_fn(settle)
        keyboard = getattr(page, "keyboard", None)
        if keyboard is None:
            return False
        press = getattr(keyboard, "press", None)
        if callable(press):
            for combo in ("Control+A", "Meta+A"):
                try:
                    press(combo)
                    break
                except Exception:
                    continue
            try:
                press("Backspace")
            except Exception:
                pass
        type_text = getattr(keyboard, "type", None)
        if not callable(type_text):
            return False
        delay = round(
            self.safe_mode_controller.rng.uniform(60, 140)
            if self.safe_mode_controller.enabled
            else 80
        )
        type_text(query, delay=delay)
        if callable(press):
            try:
                press("Enter")
            except Exception:
                return False
        else:
            return False
        return True

    def _remember_active_search_results(self, query: str, htmls: List[str]) -> None:
        active_urls: set[str] = set()
        for html in htmls:
            for href in re.findall(r'href="([^"]*/user/profile/[^"]*)"', html):
                resolved = urljoin(f"{self.base_url.rstrip('/')}/", href.replace("&amp;", "&"))
                active_urls.add(canonicalize_profile_url(resolved, self.base_url))
        self._active_search_query = query
        self._active_search_result_urls = active_urls

    def fetch_profile_html(self, profile_url: str) -> str:
        cached = self._profile_html_cache.get(profile_url)
        if cached is not None:
            return cached
        cache_path = self._cache_path("profiles", profile_url)
        if cache_path is not None and cache_path.exists():
            if self._is_cache_fresh(cache_path):
                self.safe_mode_controller.log_fn(
                    "safe-mode: loaded profile from disk cache"
                )
                html = cache_path.read_text(encoding="utf-8")
                self._profile_html_cache[profile_url] = html
                return html
            self.safe_mode_controller.log_fn(
                "safe-mode: disk cache expired for profile"
            )
        html = self._load_html(profile_url)
        self._profile_html_cache[profile_url] = html
        if cache_path is not None:
            cache_path.write_text(html, encoding="utf-8")
            self.safe_mode_controller.log_fn("safe-mode: wrote profile cache to disk")
        return html

    def fetch_note_recommendation_html(self, profile_url: str) -> List[str]:
        profile_html = self.fetch_profile_html(profile_url)
        note_links = extract_note_detail_urls(
            profile_html, self.base_url, max_results=3
        )
        return [self._load_html(note_url) for note_url in note_links]

    def fetch_search_result_htmls(self, query: str) -> List[str]:
        cached = self._search_html_cache.get(query)
        if cached is not None:
            return list(cached)
        cache_path = self._cache_path("search", query)
        if cache_path is not None and cache_path.exists():
            if self._is_cache_fresh(cache_path):
                self.safe_mode_controller.log_fn(
                    "safe-mode: loaded search from disk cache"
                )
                htmls = json.loads(cache_path.read_text(encoding="utf-8"))
                self._search_html_cache[query] = list(htmls)
                return list(htmls)
            self.safe_mode_controller.log_fn("safe-mode: disk cache expired for search")
        search_url = f"{self.base_url}/search_result?keyword={quote(query)}&source=web_explore_feed"
        htmls = self._load_search_result_htmls_via_ui(
            query,
            scroll_rounds=self.search_scroll_rounds,
        )
        if htmls is None:
            htmls = self._load_search_result_htmls(
                search_url,
                scroll_rounds=self.search_scroll_rounds,
            )
        self._remember_active_search_results(query, htmls)
        self._search_html_cache[query] = list(htmls)
        if cache_path is not None:
            cache_path.write_text(
                json.dumps(htmls, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.safe_mode_controller.log_fn("safe-mode: wrote search cache to disk")
        return list(htmls)


def save_login_storage_state(
    output_path: str | Path,
    login_url: str = "https://www.xiaohongshu.com",
) -> None:
    state_path = Path(output_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fp = _get_or_create_fingerprint(state_path)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = NewContext(
            browser,
            fingerprint=fp,
        )
        page = context.new_page()
        apply_stealth(page)
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
            print("登录完成后，回到终端按回车保存 storage_state...", end="", flush=True)
            with open("/dev/tty", "r", encoding="utf-8") as tty:
                tty.readline()
            context.storage_state(path=str(state_path))
            print(f"\nsaved to {state_path}")
        finally:
            browser.close()



def _storage_state_has_auth_cookie(state: dict) -> bool:
    for cookie in state.get("cookies", []):
        domain = str(cookie.get("domain", ""))
        name = str(cookie.get("name", "")).lower()
        if "xiaohongshu.com" not in domain:
            continue
        if name in {"web_session", "web_session_id", "xsecappid"}:
            return True
    return False


def _write_login_qr_status(session_path: Path, status: dict) -> None:
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def wait_for_qr_login_storage_state(
    output_path: str | Path,
    *,
    login_url: str = "https://www.xiaohongshu.com",
    qr_path: str | Path,
    session_path: str | Path,
    timeout_seconds: int = 180,
) -> None:
    state_path = Path(output_path)
    qr_image_path = Path(qr_path)
    session_json_path = Path(session_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    qr_image_path.parent.mkdir(parents=True, exist_ok=True)
    fp = _get_or_create_fingerprint(state_path)
    deadline = time.time() + timeout_seconds

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = NewContext(browser, fingerprint=fp)
        page = context.new_page()
        apply_stealth(page)
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            page.screenshot(path=str(qr_image_path), full_page=True)
            _write_login_qr_status(
                session_json_path,
                {
                    "status": "waiting_for_scan",
                    "pid": os.getpid(),
                    "storage_state": str(state_path),
                    "qr_path": str(qr_image_path),
                    "login_url": login_url,
                    "deadline_epoch": deadline,
                },
            )
            while time.time() < deadline:
                state = context.storage_state()
                if _storage_state_has_auth_cookie(state):
                    context.storage_state(path=str(state_path))
                    _write_login_qr_status(
                        session_json_path,
                        {
                            "status": "authenticated",
                            "pid": os.getpid(),
                            "storage_state": str(state_path),
                            "qr_path": str(qr_image_path),
                            "login_url": login_url,
                        },
                    )
                    return
                page.wait_for_timeout(2000)

            _write_login_qr_status(
                session_json_path,
                {
                    "status": "timeout",
                    "pid": os.getpid(),
                    "storage_state": str(state_path),
                    "qr_path": str(qr_image_path),
                    "login_url": login_url,
                },
            )
            raise TimeoutError("timed out waiting for QR login")
        except Exception as exc:
            if not session_json_path.exists() or json.loads(
                session_json_path.read_text(encoding="utf-8")
            ).get("status") not in {"authenticated", "timeout"}:
                _write_login_qr_status(
                    session_json_path,
                    {
                        "status": "error",
                        "pid": os.getpid(),
                        "storage_state": str(state_path),
                        "qr_path": str(qr_image_path),
                        "login_url": login_url,
                        "error": str(exc),
                    },
                )
            raise
        finally:
            browser.close()


def start_qr_login_storage_state(
    output_path: str | Path,
    *,
    login_url: str = "https://www.xiaohongshu.com",
    qr_path: str | Path,
    session_path: str | Path,
    timeout_seconds: int = 180,
) -> int:
    state_path = Path(output_path)
    qr_image_path = Path(qr_path)
    session_json_path = Path(session_path)
    log_path = session_json_path.with_suffix(".log")
    session_json_path.parent.mkdir(parents=True, exist_ok=True)
    _write_login_qr_status(
        session_json_path,
        {
            "status": "starting",
            "storage_state": str(state_path),
            "qr_path": str(qr_image_path),
            "login_url": login_url,
        },
    )
    command = [
        sys.executable,
        "-m",
        "red_crawler.cli",
        "login-qr-worker",
        "--save-state",
        str(state_path),
        "--login-url",
        login_url,
        "--qr-path",
        str(qr_image_path),
        "--session-path",
        str(session_json_path),
        "--timeout",
        str(timeout_seconds),
    ]
    with log_path.open("ab") as log_file:
        kwargs = {
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
            "close_fds": os.name != "nt",
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **kwargs)
    status = json.loads(session_json_path.read_text(encoding="utf-8"))
    status["pid"] = process.pid
    status["log_path"] = str(log_path)
    _write_login_qr_status(session_json_path, status)
    for _ in range(30):
        if qr_image_path.exists():
            break
        time.sleep(0.5)
    return process.pid


def open_xiaohongshu(
    storage_state: str | Path,
    open_url: str = "https://www.xiaohongshu.com",
) -> None:
    storage_state_path = Path(storage_state)
    if not storage_state_path.exists():
        raise FileNotFoundError(
            f"storage state file not found: {storage_state_path.as_posix()}"
        )

    fp = _get_or_create_fingerprint(storage_state_path)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = NewContext(
            browser,
            fingerprint=fp,
            storage_state=str(storage_state_path),
        )
        page = context.new_page()
        apply_stealth(page)
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
    for href in re.findall(
        r'href="([^"]*/user/profile/[^"]+xsec_source=pc_user[^"]*)"', profile_html
    ):
        resolved = urljoin(f"{base_url.rstrip('/')}/", href.replace("&amp;", "&"))
        if resolved not in note_links:
            note_links.append(resolved)
        if len(note_links) >= max_results:
            break
    return note_links
