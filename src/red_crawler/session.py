from __future__ import annotations

import hashlib
import json
import os
import pickle
import random
import re
import shutil
import string
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Protocol
from urllib.parse import quote, unquote, urljoin, urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
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
        "Security Verification",
        "Scan with logged-in",
        "REDNote APP",
        "QR code expires",
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
DEFAULT_COSMETICS_HOMEFEED_URL = (
    "https://www.xiaohongshu.com/explore?channel_id=homefeed.cosmetics_v3"
)
LOGIN_DIALOG_CLOSE_SELECTORS = (
    "button[aria-label='关闭']",
    "[aria-label='关闭']",
    "button[title='关闭']",
    "[title='关闭']",
    ".login-container .close",
    ".login-modal .close",
    ".login-dialog .close",
    ".login .close",
    ".modal .close",
    ".reds-modal .close",
    ".close-circle",
    ".icon-close",
    "button:has-text('关闭')",
)
SUPPORTED_INTERACTION_MODES = ("playwright", "os-mouse")
SUPPORTED_BROWSER_MODES = ("local", "bright-data")
SUPPORTED_ROTATION_MODES = ("none", "session")
BRIGHT_DATA_BROWSER_API_ENDPOINT_ENVS = (
    "BRIGHT_DATA_BROWSER_API_ENDPOINT",
    "BRIGHT_DATA_BROWSER_API_URL",
)
BRIGHT_DATA_BROWSER_API_AUTH_ENV = "BRIGHT_DATA_BROWSER_API_AUTH"
BRIGHT_DATA_BROWSER_API_HOST = "brd.superproxy.io:9222"
ROTATABLE_HTTP_STATUSES = {403, 429}
USER_AGENT_POOL = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)
ACCEPT_LANGUAGE_POOL = (
    "zh-CN,zh;q=0.9,en;q=0.8",
    "zh-CN,zh;q=0.9",
    "zh-CN,zh-Hans;q=0.9,en-US;q=0.8,en;q=0.7",
)


class ProxyRotationRequired(RiskControlTriggered):
    pass


def generate_browser_session_id(length: int = 10) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def build_random_headers(
    *,
    rng: random.Random | None = None,
    identity: str | None = None,
) -> dict[str, str]:
    if identity is not None:
        digest = hashlib.sha256(identity.encode("utf-8")).digest()
        user_agent = USER_AGENT_POOL[
            int.from_bytes(digest[:4], byteorder="big") % len(USER_AGENT_POOL)
        ]
        accept_language = ACCEPT_LANGUAGE_POOL[
            int.from_bytes(digest[4:8], byteorder="big") % len(ACCEPT_LANGUAGE_POOL)
        ]
    else:
        chooser = rng or random
        user_agent = chooser.choice(USER_AGENT_POOL)
        accept_language = chooser.choice(ACCEPT_LANGUAGE_POOL)
    chrome_major = re.search(r"Chrome/(\d+)", user_agent)
    major = chrome_major.group(1) if chrome_major else "124"
    platform = '"macOS"' if "Macintosh" in user_agent else '"Windows"'
    return {
        "User-Agent": user_agent,
        "Accept-Language": accept_language,
        "Sec-CH-UA": f'"Chromium";v="{major}", "Google Chrome";v="{major}", "Not-A.Brand";v="99"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": platform,
    }


def build_header_identity(
    *,
    browser_mode: str,
    browser_session_id: str,
    proxy_url: str,
) -> str:
    if proxy_url:
        return f"proxy:{proxy_url}"
    if browser_mode == "bright-data":
        return f"bright-data:{browser_session_id}"
    return "local-direct"


def build_playwright_proxy(proxy_url: str) -> dict[str, str]:
    value = proxy_url.strip()
    if not value:
        raise ValueError("proxy URL must not be empty")
    if "://" not in value:
        value = f"http://{value}"
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError("proxy URL must include host, for example http://host:port")
    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port is not None:
        server = f"{server}:{parsed.port}"
    proxy = {"server": server}
    if parsed.username:
        proxy["username"] = unquote(parsed.username)
    if parsed.password:
        proxy["password"] = unquote(parsed.password)
    return proxy


def build_bright_data_browser_api_endpoint(
    *,
    endpoint: str | None = None,
    auth: str | None = None,
    session_id: str | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    env = os.environ if environ is None else environ
    resolved_endpoint = (endpoint or "").strip()
    if not resolved_endpoint:
        for env_name in BRIGHT_DATA_BROWSER_API_ENDPOINT_ENVS:
            resolved_endpoint = env.get(env_name, "").strip()
            if resolved_endpoint:
                break
    if resolved_endpoint:
        if not resolved_endpoint.startswith("wss://"):
            raise ValueError("Bright Data Browser API endpoint must start with wss://")
        return resolved_endpoint.replace("{session}", session_id or "")

    resolved_auth = (auth or env.get(BRIGHT_DATA_BROWSER_API_AUTH_ENV, "")).strip()
    if not resolved_auth:
        env_names = ", ".join(
            (*BRIGHT_DATA_BROWSER_API_ENDPOINT_ENVS, BRIGHT_DATA_BROWSER_API_AUTH_ENV)
        )
        raise RuntimeError(
            "Bright Data Browser API mode requires --browser-endpoint, --browser-auth, "
            f"or one of these environment variables: {env_names}"
        )
    if ":" not in resolved_auth:
        raise ValueError("Bright Data Browser API auth must be formatted as USER:PASS")
    if session_id:
        resolved_auth = resolved_auth.replace("{session}", session_id)
    username, password = resolved_auth.split(":", 1)
    return (
        f"wss://{quote(username, safe='')}:{quote(password, safe='')}"
        f"@{BRIGHT_DATA_BROWSER_API_HOST}"
    )


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


def classify_high_risk_url(url: str) -> str | None:
    if "/website-login/captcha" in url:
        return "login_required"
    return None


class MouseAutomationBackend(Protocol):
    drives_system_cursor: bool

    def move(self, page: Page, x: float, y: float, *, steps: int) -> None: ...

    def click(self, page: Page, x: float, y: float, *, delay_ms: int) -> bool: ...

    def wheel(self, page: Page, *, delta_y: int) -> bool: ...


@dataclass
class PlaywrightMouseBackend:
    drives_system_cursor: bool = False

    def move(self, page: Page, x: float, y: float, *, steps: int) -> None:
        mouse = getattr(page, "mouse", None)
        if mouse is None:
            return
        move = getattr(mouse, "move", None)
        if callable(move):
            move(x, y, steps=steps)

    def click(self, page: Page, x: float, y: float, *, delay_ms: int) -> bool:
        mouse = getattr(page, "mouse", None)
        if mouse is None:
            return False
        click = getattr(mouse, "click", None)
        if callable(click):
            click(x, y, delay=delay_ms)
            return True
        down = getattr(mouse, "down", None)
        up = getattr(mouse, "up", None)
        if callable(down) and callable(up):
            down()
            up()
            return True
        return False

    def wheel(self, page: Page, *, delta_y: int) -> bool:
        mouse = getattr(page, "mouse", None)
        if mouse is None:
            return False
        wheel = getattr(mouse, "wheel", None)
        if callable(wheel):
            wheel(0, delta_y)
            return True
        return False


@dataclass
class OSMouseBackend:
    run_fn: Callable[..., object] = subprocess.run
    which_fn: Callable[[str], str | None] = shutil.which
    sleep_fn: Callable[[float], None] = time.sleep
    platform: str = sys.platform
    _xdotool_checked: bool = False
    drives_system_cursor: bool = True

    def _ensure_linux_xdotool(self) -> None:
        if self.platform.startswith("linux"):
            if not self._xdotool_checked:
                if self.which_fn("xdotool") is None:
                    raise RuntimeError(
                        "interaction mode 'os-mouse' requires xdotool to be installed on Linux"
                    )
                self._xdotool_checked = True
            return
        raise RuntimeError(
            f"interaction mode 'os-mouse' is currently supported only on Linux; current platform is {self.platform}"
        )

    def move(self, page: Page, x: float, y: float, *, steps: int) -> None:
        self._ensure_linux_xdotool()
        target_x, target_y = self._viewport_to_screen_point(page, x, y)
        start_x, start_y = self._current_cursor_position()
        step_count = max(1, steps)
        for step_index in range(1, step_count + 1):
            next_x = round(start_x + (target_x - start_x) * step_index / step_count)
            next_y = round(start_y + (target_y - start_y) * step_index / step_count)
            self._run_command(["xdotool", "mousemove", "--sync", str(next_x), str(next_y)])
            if step_index < step_count:
                self.sleep_fn(0.012)

    def click(self, page: Page, x: float, y: float, *, delay_ms: int) -> bool:
        self.move(page, x, y, steps=1)
        if delay_ms > 0:
            self.sleep_fn(delay_ms / 1000.0)
        self._run_command(["xdotool", "click", "1"])
        return True

    def wheel(self, page: Page, *, delta_y: int) -> bool:
        self._ensure_linux_xdotool()
        repeats = max(1, min(12, round(abs(delta_y) / 120)))
        button = "4" if delta_y < 0 else "5"
        self._run_command(
            ["xdotool", "click", "--repeat", str(repeats), "--delay", "70", button]
        )
        return True

    def _current_cursor_position(self) -> tuple[int, int]:
        result = self._run_command(
            ["xdotool", "getmouselocation", "--shell"],
            capture_output=True,
        )
        output = str(getattr(result, "stdout", "") or "")
        x = 0
        y = 0
        for line in output.splitlines():
            if line.startswith("X="):
                x = int(line[2:])
            elif line.startswith("Y="):
                y = int(line[2:])
        return x, y

    def _viewport_to_screen_point(self, page: Page, x: float, y: float) -> tuple[int, int]:
        metrics = page.evaluate(
            """
            () => ({
              screenX: typeof window.screenX === "number" ? window.screenX : (window.screenLeft || 0),
              screenY: typeof window.screenY === "number" ? window.screenY : (window.screenTop || 0),
              outerWidth: typeof window.outerWidth === "number" ? window.outerWidth : window.innerWidth,
              outerHeight: typeof window.outerHeight === "number" ? window.outerHeight : window.innerHeight,
              innerWidth: typeof window.innerWidth === "number" ? window.innerWidth : 0,
              innerHeight: typeof window.innerHeight === "number" ? window.innerHeight : 0
            })
            """
        )
        screen_x = int(metrics.get("screenX", 0))
        screen_y = int(metrics.get("screenY", 0))
        outer_width = int(metrics.get("outerWidth", 0))
        outer_height = int(metrics.get("outerHeight", 0))
        inner_width = int(metrics.get("innerWidth", 0))
        inner_height = int(metrics.get("innerHeight", 0))
        left_chrome = max(0, round((outer_width - inner_width) / 2))
        top_chrome = max(0, outer_height - inner_height)
        return (
            screen_x + left_chrome + round(x),
            screen_y + top_chrome + round(y),
        )

    def _run_command(self, argv: list[str], *, capture_output: bool = False) -> object:
        kwargs = {"check": True}
        if capture_output:
            kwargs["capture_output"] = True
            kwargs["text"] = True
        return self.run_fn(argv, **kwargs)


def build_mouse_backend(
    interaction_mode: str,
    *,
    run_fn: Callable[..., object] = subprocess.run,
    which_fn: Callable[[str], str | None] = shutil.which,
    sleep_fn: Callable[[float], None] = time.sleep,
    platform: str = sys.platform,
) -> MouseAutomationBackend:
    if interaction_mode == "playwright":
        return PlaywrightMouseBackend()
    if interaction_mode == "os-mouse":
        return OSMouseBackend(
            run_fn=run_fn,
            which_fn=which_fn,
            sleep_fn=sleep_fn,
            platform=platform,
        )
    raise ValueError(
        f"interaction_mode must be one of: {', '.join(SUPPORTED_INTERACTION_MODES)}"
    )


@dataclass
class SafeModeController:
    enabled: bool
    sleep_fn: Callable[[float], None] = time.sleep
    log_fn: Callable[[str], None] = lambda _message: None
    rng: random.Random = field(default_factory=random.Random)
    mouse_backend: MouseAutomationBackend = field(default_factory=PlaywrightMouseBackend)
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
        if not self.mouse_backend.drives_system_cursor:
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
            if self.mouse_backend.drives_system_cursor:
                raise

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
                x, y, _steps = self._move_mouse_to_box(page, box)
                if self.mouse_backend.click(
                    page,
                    x,
                    y,
                    delay_ms=round(self.rng.uniform(200, 420)),
                ):
                    return True
        except Exception:
            if self.mouse_backend.drives_system_cursor:
                raise
        if not self.enabled and not self.mouse_backend.drives_system_cursor:
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
            return self.mouse_backend.click(
                page,
                x,
                y,
                delay_ms=round(self.rng.uniform(200, 420)),
            )
        except Exception:
            if self.mouse_backend.drives_system_cursor:
                raise
        return False

    def _move_mouse_to_reading_zone(self, page: Page) -> None:
        width, height = self._viewport_dimensions(page)
        x_ratio = self.rng.uniform(0.34, 0.72)
        y_ratio = self.rng.uniform(0.18, 0.68)
        steps = max(4, int(self.rng.uniform(4, 10)))
        try:
            self.mouse_backend.move(page, width * x_ratio, height * y_ratio, steps=steps)
        except Exception:
            if self.mouse_backend.drives_system_cursor:
                raise

    def _move_mouse_to_box(self, page: Page, box: dict[str, float]) -> tuple[float, float, int]:
        offset_x = self.rng.uniform(0.35, 0.68)
        offset_y = self.rng.uniform(0.28, 0.72)
        steps = max(4, int(self.rng.uniform(4, 10)))
        x = box["x"] + box["width"] * offset_x
        y = box["y"] + box["height"] * offset_y
        self.mouse_backend.move(page, x, y, steps=steps)
        return x, y, steps

    def _wheel_scroll(self, page: Page, *, delta_ratio: float) -> None:
        _, height = self._viewport_dimensions(page)
        delta_y = max(1, int(abs(height * delta_ratio)))
        if delta_ratio < 0:
            delta_y = -delta_y
        if self.mouse_backend.wheel(page, delta_y=delta_y):
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
    def __init__(
        self,
        storage_state: str | None = None,
        headless: bool = False,
        browser_mode: str = "local",
        browser_endpoint: str | None = None,
        browser_auth: str | None = None,
        rotation_mode: str = "none",
        browser_session_id: str | None = None,
        randomize_headers: bool = True,
        proxy_url: str | None = None,
    ):
        self.storage_state = str(storage_state) if storage_state else ""
        self.headless = headless
        self.browser_mode = browser_mode
        self.browser_endpoint = browser_endpoint
        self.browser_auth = browser_auth
        self.rotation_mode = rotation_mode
        self.browser_session_id = browser_session_id or generate_browser_session_id()
        self.randomize_headers = randomize_headers
        self.proxy_url = proxy_url.strip() if proxy_url else ""
        header_identity = build_header_identity(
            browser_mode=self.browser_mode,
            browser_session_id=self.browser_session_id,
            proxy_url=self.proxy_url,
        )
        self.extra_http_headers = (
            build_random_headers(identity=header_identity) if randomize_headers else {}
        )
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    def __enter__(self) -> "BrowserSession":
        storage_state_path = Path(self.storage_state) if self.storage_state else None
        if storage_state_path is not None and not storage_state_path.exists():
            raise FileNotFoundError(
                f"storage state file not found: {storage_state_path.as_posix()}"
            )
        if self.browser_mode not in SUPPORTED_BROWSER_MODES:
            raise ValueError(
                f"browser_mode must be one of: {', '.join(SUPPORTED_BROWSER_MODES)}"
            )
        if self.rotation_mode not in SUPPORTED_ROTATION_MODES:
            raise ValueError(
                f"rotation_mode must be one of: {', '.join(SUPPORTED_ROTATION_MODES)}"
            )
        self._playwright = sync_playwright().start()
        if self.browser_mode == "bright-data":
            endpoint = build_bright_data_browser_api_endpoint(
                endpoint=self.browser_endpoint,
                auth=self.browser_auth,
                session_id=self.browser_session_id,
            )
            self._browser = self._playwright.chromium.connect_over_cdp(endpoint)
            self._context = self._new_remote_context(storage_state_path)
        else:
            launch_kwargs = {"headless": self.headless}
            if self.proxy_url:
                launch_kwargs["proxy"] = build_playwright_proxy(self.proxy_url)
            self._browser = self._playwright.chromium.launch(**launch_kwargs)
            fp = (
                _get_or_create_fingerprint(storage_state_path)
                if storage_state_path is not None
                else FingerprintGenerator(os=("windows",)).generate()
            )
            context_kwargs = {"fingerprint": fp}
            if storage_state_path is not None:
                context_kwargs["storage_state"] = str(storage_state_path)
            if self.extra_http_headers:
                context_kwargs["extra_http_headers"] = self.extra_http_headers
            self._context = NewContext(self._browser, **context_kwargs)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
            self._context = None
        elif self._context is not None:
            self._context.browser.close()
            self._context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def _new_remote_context(self, storage_state_path: Path | None) -> BrowserContext:
        if self._browser is None:
            raise RuntimeError("browser session is not started")
        try:
            context_kwargs = {}
            if self.extra_http_headers:
                context_kwargs["extra_http_headers"] = self.extra_http_headers
            if storage_state_path is None:
                return self._browser.new_context(**context_kwargs)
            context_kwargs["storage_state"] = str(storage_state_path)
            return self._browser.new_context(**context_kwargs)
        except Exception:
            if not self._browser.contexts:
                raise
            context = self._browser.contexts[0]
            if storage_state_path is not None:
                self._apply_storage_state_to_context(context, storage_state_path)
            return context

    def _apply_storage_state_to_context(
        self,
        context: BrowserContext,
        storage_state_path: Path,
    ) -> None:
        state = json.loads(storage_state_path.read_text(encoding="utf-8"))
        cookies = state.get("cookies", [])
        if cookies:
            context.add_cookies(cookies)
        origins = state.get("origins", [])
        if not origins:
            return
        page = context.new_page()
        try:
            for origin_state in origins:
                origin = str(origin_state.get("origin", "")).strip()
                local_storage = origin_state.get("localStorage", [])
                if not origin or not local_storage:
                    continue
                page.goto(origin, wait_until="domcontentloaded", timeout=30000)
                page.evaluate(
                    """
                    entries => {
                      for (const entry of entries) {
                        window.localStorage.setItem(entry.name, entry.value);
                      }
                    }
                    """,
                    local_storage,
                )
        finally:
            page.close()

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
        interaction_mode: str = "playwright",
        mouse_backend: MouseAutomationBackend | None = None,
        search_scroll_rounds: int = 2,
        cache_dir: str | Path | None = None,
        cache_ttl_days: int = 7,
        time_fn: Callable[[], float] = time.time,
    ):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.interaction_mode = interaction_mode
        self.search_scroll_rounds = max(int(search_scroll_rounds), 0)
        self.mouse_backend = mouse_backend or build_mouse_backend(interaction_mode)
        self.safe_mode_controller = safe_mode_controller or SafeModeController(
            enabled=safe_mode,
            log_fn=print if safe_mode else (lambda _message: None),
            mouse_backend=self.mouse_backend,
        )
        self.safe_mode_controller.mouse_backend = self.mouse_backend
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
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            self._raise_if_high_risk_page(page, exc)
            if not self._page_has_readable_body(page):
                raise
            response = None
        if response is not None and response.status >= 400:
            if response.status in ROTATABLE_HTTP_STATUSES:
                raise ProxyRotationRequired(f"http_{response.status}")
            self.safe_mode_controller.on_risk_event(
                reason=f"http_{response.status}"
            )
            raise RuntimeError(f"page request failed with status {response.status}")
        self._raise_if_high_risk_page(page)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        self._dismiss_login_dialogs(page)
        body_text = page.locator("body").inner_text()
        self._raise_if_high_risk_page(page, body_text=body_text)
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
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            self._raise_if_high_risk_page(page, exc)
            if not self._page_has_readable_body(page):
                raise
            response = None
        if response is not None and response.status >= 400:
            if response.status in ROTATABLE_HTTP_STATUSES:
                raise ProxyRotationRequired(f"http_{response.status}")
            self.safe_mode_controller.on_risk_event(
                reason=f"http_{response.status}"
            )
            raise RuntimeError(f"page request failed with status {response.status}")
        self._raise_if_high_risk_page(page)
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
            if response.status in ROTATABLE_HTTP_STATUSES:
                raise ProxyRotationRequired(f"http_{response.status}")
            self.safe_mode_controller.on_risk_event(
                reason=f"http_{response.status}"
            )
            raise RuntimeError(f"page request failed with status {response.status}")
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        self._dismiss_login_dialogs(page)
        search_input = self._first_matching_locator(page, SEARCH_INPUT_SELECTORS)
        if search_input is None:
            if self.interaction_mode == "os-mouse":
                raise RuntimeError(
                    "os-mouse interaction mode requires a visible search input on the page"
                )
            return None
        if not self._submit_search_query_via_input(page, search_input, query):
            if self.interaction_mode == "os-mouse":
                raise RuntimeError(
                    "os-mouse interaction mode failed to submit the search query through the visible search input"
                )
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
            self._dismiss_login_dialogs(page)
            body_text = page.locator("body").inner_text()
            self._raise_if_high_risk_page(page, body_text=body_text)
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
                    if self.interaction_mode == "os-mouse":
                        raise RuntimeError(
                            "os-mouse interaction mode failed to click the target search result"
                        )
                    return None
            except Exception:
                if self.interaction_mode == "os-mouse":
                    raise
                return None
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception:
                pass
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            self._dismiss_login_dialogs(page)
            body_text = page.locator("body").inner_text()
            risk_type = self._classify_page_after_dialog_dismissal(page, body_text)
            if risk_type is not None:
                self.safe_mode_controller.on_risk_event(reason=risk_type)
                raise RuntimeError(f"high risk page detected: {risk_type}")
            self._page_kind = "profile"
            self.safe_mode_controller.after_page_load(page, page_kind="profile")
            self.safe_mode_controller.on_success()
            return page.content()
        if self.interaction_mode == "os-mouse":
            raise RuntimeError(
                "os-mouse interaction mode could not find the target profile inside the active search results"
            )
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
            if self.interaction_mode == "os-mouse":
                raise RuntimeError(
                    "os-mouse interaction mode found a back button but could not click it"
                )
        if self.interaction_mode == "os-mouse":
            raise RuntimeError(
                "os-mouse interaction mode requires a visible page back button to return to search results"
            )
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
        self._dismiss_login_dialogs(page)
        return True

    def _classify_page_after_dialog_dismissal(
        self,
        page: Page,
        body_text: str,
    ) -> str | None:
        page_url = str(getattr(page, "url", ""))
        risk_type = classify_high_risk_url(page_url) or classify_high_risk_page(body_text)
        if risk_type != "login_required":
            return risk_type
        if not self._dismiss_login_dialogs(page):
            return risk_type
        try:
            page.wait_for_timeout(500)
        except Exception:
            pass
        refreshed_text = page.locator("body").inner_text()
        refreshed_risk_type = classify_high_risk_url(
            page_url
        ) or classify_high_risk_page(refreshed_text)
        return None if refreshed_risk_type == "login_required" else refreshed_risk_type

    def _raise_if_high_risk_page(
        self,
        page: Page,
        exc: Exception | None = None,
        *,
        body_text: str | None = None,
    ) -> None:
        risk_type = classify_high_risk_url(str(getattr(page, "url", "")))
        if risk_type is None:
            try:
                text = (
                    body_text
                    if body_text is not None
                    else page.locator("body").inner_text()
                )
            except Exception:
                text = ""
            risk_type = self._classify_page_after_dialog_dismissal(page, text)
        if risk_type is None:
            return
        self.safe_mode_controller.on_risk_event(reason=risk_type)
        if exc is not None:
            raise RiskControlTriggered(risk_type) from exc
        raise RiskControlTriggered(risk_type)

    def _page_has_readable_body(self, page: Page) -> bool:
        try:
            return bool(page.locator("body").inner_text().strip())
        except Exception:
            return False

    def _dismiss_login_dialogs(self, page: Page) -> bool:
        dismissed = False
        for selector in LOGIN_DIALOG_CLOSE_SELECTORS:
            try:
                locator = page.locator(selector)
            except Exception:
                continue
            try:
                count = locator.count()
            except Exception:
                count = 1
            for index in range(min(count, 3)):
                try:
                    target = locator.nth(index) if hasattr(locator, "nth") else locator
                    is_visible = getattr(target, "is_visible", None)
                    if callable(is_visible) and not is_visible(timeout=500):
                        continue
                    click = getattr(target, "click", None)
                    if not callable(click):
                        continue
                    click(timeout=1000)
                    dismissed = True
                    try:
                        page.wait_for_timeout(300)
                    except Exception:
                        pass
                except Exception:
                    continue
        return dismissed

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
        if htmls is None and self.interaction_mode != "os-mouse":
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

    def fetch_homefeed_result_htmls(
        self,
        source_url: str = DEFAULT_COSMETICS_HOMEFEED_URL,
    ) -> List[str]:
        cache_key = f"homefeed:{source_url}"
        cached = self._search_html_cache.get(cache_key)
        if cached is not None:
            return list(cached)
        cache_path = self._cache_path("search", cache_key)
        if cache_path is not None and cache_path.exists():
            if self._is_cache_fresh(cache_path):
                htmls = json.loads(cache_path.read_text(encoding="utf-8"))
                self._search_html_cache[cache_key] = list(htmls)
                return list(htmls)
            self.safe_mode_controller.log_fn("safe-mode: disk cache expired for homefeed")
        htmls = self._load_search_result_htmls(
            source_url,
            scroll_rounds=self.search_scroll_rounds,
        )
        self._remember_active_search_results(cache_key, htmls)
        self._search_html_cache[cache_key] = list(htmls)
        if cache_path is not None:
            cache_path.write_text(
                json.dumps(htmls, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.safe_mode_controller.log_fn("safe-mode: wrote homefeed cache to disk")
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
