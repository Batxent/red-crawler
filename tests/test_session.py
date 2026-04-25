import time

import red_crawler.session as session_module
from red_crawler.session import (
    BrowserSession,
    build_bright_data_browser_api_endpoint,
    build_mouse_backend,
    apply_stealth,
    classify_high_risk_page,
    OSMouseBackend,
    PlaywrightCrawlerClient,
    RiskControlTriggered,
    SafeModeController,
    extract_note_detail_urls,
)


def test_build_bright_data_browser_api_endpoint_from_auth():
    endpoint = build_bright_data_browser_api_endpoint(
        auth="brd-customer-123-zone-main:pass@word",
        environ={},
    )

    assert (
        endpoint
        == "wss://brd-customer-123-zone-main:pass%40word@brd.superproxy.io:9222"
    )


def test_build_bright_data_browser_api_endpoint_prefers_explicit_endpoint():
    endpoint = build_bright_data_browser_api_endpoint(
        endpoint="wss://user:pass@custom.example:9222",
        auth="ignored:ignored",
        environ={},
    )

    assert endpoint == "wss://user:pass@custom.example:9222"


def test_browser_session_connects_to_bright_data_cdp(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    state_path.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    captured = {}

    class FakeContext:
        pass

    class FakeBrowser:
        contexts = []

        def new_context(self, **kwargs):
            captured["new_context_kwargs"] = kwargs
            return FakeContext()

        def close(self):
            captured["browser_closed"] = True

    class FakeChromium:
        def connect_over_cdp(self, endpoint):
            captured["endpoint"] = endpoint
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def stop(self):
            captured["playwright_stopped"] = True

    class FakeSyncPlaywright:
        def start(self):
            captured["started"] = True
            return FakePlaywright()

    monkeypatch.setattr(session_module, "sync_playwright", lambda: FakeSyncPlaywright())

    with BrowserSession(
        str(state_path),
        browser_mode="bright-data",
        browser_auth="user:pass",
    ) as browser_session:
        assert isinstance(browser_session.context, FakeContext)

    assert captured == {
        "started": True,
        "endpoint": "wss://user:pass@brd.superproxy.io:9222",
        "new_context_kwargs": {"storage_state": str(state_path)},
        "browser_closed": True,
        "playwright_stopped": True,
    }


def test_apply_stealth_uses_stealth_api(monkeypatch):
    calls = []

    class FakeStealth:
        def apply_stealth_sync(self, page):
            calls.append(page)

    monkeypatch.setattr(session_module, "Stealth", FakeStealth)

    page = object()
    apply_stealth(page)

    assert calls == [page]


def test_extract_note_detail_urls_prefers_profile_note_routes():
    html = """
    <div>
      <a href="/explore/63184102000000001103a3e7"></a>
      <a href="/user/profile/user-001/63184102000000001103a3e7?xsec_token=abc&amp;xsec_source=pc_user"></a>
      <a href="/user/profile/user-001/69c0ff760000000022001b5d?xsec_token=def&amp;xsec_source=pc_user"></a>
      <a href="/user/profile/user-001/63184102000000001103a3e7?xsec_token=abc&amp;xsec_source=pc_user"></a>
    </div>
    """

    urls = extract_note_detail_urls(
        profile_html=html,
        base_url="https://www.xiaohongshu.com",
        max_results=3,
    )

    assert urls == [
        "https://www.xiaohongshu.com/user/profile/user-001/63184102000000001103a3e7?xsec_token=abc&xsec_source=pc_user",
        "https://www.xiaohongshu.com/user/profile/user-001/69c0ff760000000022001b5d?xsec_token=def&xsec_source=pc_user",
    ]


def test_build_mouse_backend_rejects_unknown_mode():
    try:
        build_mouse_backend("invalid-mode")
    except ValueError as exc:
        assert str(exc) == "interaction_mode must be one of: playwright, os-mouse"
    else:
        raise AssertionError("expected ValueError")


def test_os_mouse_backend_uses_xdotool_commands():
    commands = []

    class Result:
        def __init__(self, stdout=""):
            self.stdout = stdout

    def fake_run(argv, check, capture_output=False, text=False):
        commands.append((argv, capture_output, text))
        if argv[:2] == ["xdotool", "getmouselocation"]:
            return Result("X=100\nY=200\n")
        return Result()

    class FakePage:
        def evaluate(self, _script):
            return {
                "screenX": 20,
                "screenY": 30,
                "outerWidth": 1400,
                "outerHeight": 1000,
                "innerWidth": 1280,
                "innerHeight": 900,
            }

    backend = OSMouseBackend(
        run_fn=fake_run,
        which_fn=lambda name: "/usr/bin/xdotool" if name == "xdotool" else None,
        sleep_fn=lambda _seconds: None,
        platform="linux",
    )

    backend.move(FakePage(), 50, 60, steps=2)
    backend.click(FakePage(), 70, 80, delay_ms=0)
    backend.wheel(FakePage(), delta_y=240)

    assert commands == [
        (["xdotool", "getmouselocation", "--shell"], True, True),
        (["xdotool", "mousemove", "--sync", "115", "195"], False, False),
        (["xdotool", "mousemove", "--sync", "130", "190"], False, False),
        (["xdotool", "getmouselocation", "--shell"], True, True),
        (["xdotool", "mousemove", "--sync", "150", "210"], False, False),
        (["xdotool", "click", "1"], False, False),
        (["xdotool", "click", "--repeat", "2", "--delay", "70", "5"], False, False),
    ]


def test_safe_mode_controller_adds_jitter_and_backoff():
    sleeps = []
    logs = []

    class FakeRandom:
        def __init__(self):
            self.values = iter([12.8, 18.4, 26.1, 140.0, 220.0])

        def uniform(self, _a, _b):
            return next(self.values)

    controller = SafeModeController(
        enabled=True,
        sleep_fn=sleeps.append,
        log_fn=logs.append,
        rng=FakeRandom(),
        pause_every=3,
    )

    controller.before_request()
    controller.before_request()
    controller.before_request()
    controller.on_risk_event()

    assert sleeps == [12.8, 18.4, 26.1, 140.0, 220.0]
    assert logs == [
        "safe-mode: sleeping 12.8s before request #1",
        "safe-mode: sleeping 18.4s before request #2",
        "safe-mode: sleeping 26.1s before request #3",
        "safe-mode: taking a longer 140.0s pause after 3 requests",
        "safe-mode: backing off for 220.0s after risk signal #1",
    ]


def test_safe_mode_controller_uses_wider_before_request_sleep_window():
    recorded_ranges = []

    class RangeRandom:
        def uniform(self, start, end):
            recorded_ranges.append((start, end))
            return 14.6

    controller = SafeModeController(
        enabled=True,
        sleep_fn=lambda _seconds: None,
        log_fn=lambda _message: None,
        rng=RangeRandom(),
        pause_every=99,
    )

    controller.before_request()

    assert recorded_ranges == [(12.0, 28.0)]


def test_safe_mode_controller_adds_post_load_dwell_and_scroll():
    sleeps = []
    logs = []
    mouse_moves = []
    mouse_wheels = []

    class FakeRandom:
        def __init__(self):
            self.uniform_values = iter(
                [14.2, 1.2, 0.45, 0.38, 6.2, 0.18, 3.1, 1.1, 0.52, 0.44, 7.1, 0.26, 5.6]
            )
            self.random_values = iter([0.2, 0.3])

        def uniform(self, _start, _end):
            return next(self.uniform_values)

        def random(self):
            return next(self.random_values)

    class FakePage:
        viewport_size = {"width": 1280, "height": 900}
        mouse = type(
            "Mouse",
            (),
            {
                "move": lambda _self, x, y, steps: mouse_moves.append((x, y, steps)),
                "wheel": lambda _self, dx, dy: mouse_wheels.append((dx, dy)),
            },
        )()

    controller = SafeModeController(
        enabled=True,
        sleep_fn=sleeps.append,
        log_fn=logs.append,
        rng=FakeRandom(),
    )

    controller.after_page_load(FakePage(), page_kind="profile")

    assert sleeps == [14.2, 3.1, 5.6]
    assert mouse_wheels == [
        (0, 405),
        (0, 468),
    ]
    assert len(mouse_moves) == 2
    assert logs == [
        "safe-mode: dwelling 14.2s on profile page",
        "safe-mode: settling for 3.1s after scroll step 1 on profile page",
        "safe-mode: settling for 5.6s after scroll step 1 on profile page",
    ]


def test_safe_mode_controller_adds_search_scroll_settle():
    sleeps = []
    logs = []

    class FixedRandom:
        def uniform(self, _start, _end):
            return 4.7

    controller = SafeModeController(
        enabled=True,
        sleep_fn=sleeps.append,
        log_fn=logs.append,
        rng=FixedRandom(),
    )

    controller.after_search_scroll(round_number=2)

    assert sleeps == [4.7]
    assert logs == ["safe-mode: settling for 4.7s after search scroll #2"]


def test_safe_mode_controller_performs_human_search_scroll():
    sleeps = []
    logs = []
    mouse_moves = []
    mouse_wheels = []

    class FakeRandom:
        def __init__(self):
            self.uniform_values = iter([1.4, 0.43, 0.31, 5.8, 0.18, 1.5, 1.8])
            self.random_values = iter([0.6])

        def uniform(self, _start, _end):
            return next(self.uniform_values)

        def random(self):
            return next(self.random_values)

    class FakePage:
        viewport_size = {"width": 1280, "height": 900}
        mouse = type(
            "Mouse",
            (),
            {
                "move": lambda _self, x, y, steps: mouse_moves.append((x, y, steps)),
                "wheel": lambda _self, dx, dy: mouse_wheels.append((dx, dy)),
            },
        )()

    controller = SafeModeController(
        enabled=True,
        sleep_fn=sleeps.append,
        log_fn=logs.append,
        rng=FakeRandom(),
    )

    controller.perform_search_scroll(FakePage(), round_number=2)

    assert mouse_wheels == [
        (0, 387),
    ]
    assert len(mouse_moves) == 1
    assert sleeps == [1.5, 1.8]
    assert logs == [
        "safe-mode: settling for 1.5s after scroll step 1 on search page",
        "safe-mode: settling for 1.8s after search scroll #2",
    ]


def test_safe_mode_controller_inspects_search_result_before_click():
    sleeps = []
    logs = []
    hover_calls = []
    mouse_moves = []

    class FakeRandom:
        def __init__(self):
            self.uniform_values = iter([1.3, 0.52, 0.61, 6.2])

        def uniform(self, _start, _end):
            return next(self.uniform_values)

    class FakeMouse:
        def move(self, x, y, steps):
            mouse_moves.append((x, y, steps))

    class FakePage:
        mouse = FakeMouse()

    class FakeAnchor:
        def scroll_into_view_if_needed(self, timeout):
            hover_calls.append(("scroll", timeout))

        def hover(self, timeout):
            hover_calls.append(("hover", timeout))

        def bounding_box(self):
            return {"x": 10, "y": 20, "width": 100, "height": 80}

    controller = SafeModeController(
        enabled=True,
        sleep_fn=sleeps.append,
        log_fn=logs.append,
        rng=FakeRandom(),
    )

    controller.inspect_search_result(FakePage(), FakeAnchor(), result_index=3)

    assert hover_calls == [("hover", 5000)]
    assert sleeps == [1.3]
    assert logs == ["safe-mode: pausing 1.3s while inspecting search result #3"]
    assert mouse_moves == [(62.0, 68.8, 6)]


def test_safe_mode_controller_skips_dom_hover_in_os_mouse_mode():
    sleeps = []
    hover_calls = []
    move_calls = []

    class FakeRandom:
        def __init__(self):
            self.uniform_values = iter([1.1, 0.5, 0.5, 5.0])

        def uniform(self, _start, _end):
            return next(self.uniform_values)

    class FakeBackend:
        drives_system_cursor = True

        def move(self, page, x, y, *, steps):
            move_calls.append((x, y, steps))

        def click(self, page, x, y, *, delay_ms):
            return True

        def wheel(self, page, *, delta_y):
            return True

    class FakeAnchor:
        def hover(self, timeout):
            hover_calls.append(timeout)

        def bounding_box(self):
            return {"x": 10, "y": 20, "width": 100, "height": 80}

    controller = SafeModeController(
        enabled=True,
        sleep_fn=sleeps.append,
        log_fn=lambda _message: None,
        rng=FakeRandom(),
        mouse_backend=FakeBackend(),
    )

    controller.inspect_search_result(object(), FakeAnchor(), result_index=1)

    assert hover_calls == []
    assert sleeps == [1.1]
    assert move_calls == [(60.0, 60.0, 5)]


def test_safe_mode_controller_reorients_on_search_page():
    sleeps = []
    logs = []
    mouse_wheels = []

    class FakeRandom:
        def __init__(self):
            self.uniform_values = iter([0.08, 1.4])
            self.random_values = iter([0.4, 0.7])

        def uniform(self, _start, _end):
            return next(self.uniform_values)

        def random(self):
            return next(self.random_values)

    class FakePage:
        viewport_size = {"width": 1280, "height": 900}
        mouse = type(
            "Mouse",
            (),
            {"wheel": lambda _self, dx, dy: mouse_wheels.append((dx, dy))},
        )()

    controller = SafeModeController(
        enabled=True,
        sleep_fn=sleeps.append,
        log_fn=logs.append,
        rng=FakeRandom(),
    )

    controller.reorient_on_search_page(FakePage())

    assert mouse_wheels == [(0, 72)]
    assert sleeps == [1.4]
    assert logs == ["safe-mode: settling for 1.4s while reorienting on search page"]


def test_safe_mode_controller_triggers_circuit_breaker_after_repeated_risk_events():
    controller = SafeModeController(enabled=True, sleep_fn=lambda _seconds: None, risk_threshold=2)

    controller.on_risk_event()

    try:
        controller.on_risk_event()
    except RiskControlTriggered as exc:
        assert str(exc) == "risk control threshold reached"
    else:
        raise AssertionError("expected RiskControlTriggered")


def test_classify_high_risk_page_detects_verification_and_login_expiry():
    assert classify_high_risk_page("请完成安全验证后继续访问") == "verification"
    assert classify_high_risk_page("登录后查看更多内容") == "login_required"
    assert classify_high_risk_page("正常的主页内容") is None


def test_safe_mode_controller_logs_circuit_breaker_reason():
    logs = []
    controller = SafeModeController(
        enabled=True,
        sleep_fn=lambda _seconds: None,
        log_fn=logs.append,
        risk_threshold=1,
    )

    try:
        controller.on_risk_event(reason="verification")
    except RiskControlTriggered:
        pass

    assert logs[-1] == "safe-mode: circuit breaker triggered after 1 consecutive risk signals"


def test_playwright_crawler_client_caches_profile_and_search_results(monkeypatch):
    class DummySession:
        def new_page(self):
            raise AssertionError("network should not be used in this test")

    client = PlaywrightCrawlerClient(DummySession(), safe_mode=False)
    calls = {"profile": 0, "search": 0}

    def fake_load_html(url):
        calls["profile"] += 1
        return f"profile:{url}"

    def fake_load_search_result_htmls(url, scroll_rounds=3):
        calls["search"] += 1
        return [f"search:{url}"]

    monkeypatch.setattr(client, "_load_html", fake_load_html)
    monkeypatch.setattr(client, "_load_search_result_htmls_via_ui", lambda query, scroll_rounds=3: None)
    monkeypatch.setattr(client, "_load_search_result_htmls", fake_load_search_result_htmls)

    assert client.fetch_profile_html("https://example.com/u1") == "profile:https://example.com/u1"
    assert client.fetch_profile_html("https://example.com/u1") == "profile:https://example.com/u1"
    assert client.fetch_search_result_htmls("美妆博主") == [
        "search:https://www.xiaohongshu.com/search_result?keyword=%E7%BE%8E%E5%A6%86%E5%8D%9A%E4%B8%BB&source=web_explore_feed"
    ]
    assert client.fetch_search_result_htmls("美妆博主") == [
        "search:https://www.xiaohongshu.com/search_result?keyword=%E7%BE%8E%E5%A6%86%E5%8D%9A%E4%B8%BB&source=web_explore_feed"
    ]
    assert calls == {"profile": 1, "search": 1}


def test_playwright_crawler_client_uses_configured_search_scroll_rounds(monkeypatch):
    class DummySession:
        def new_page(self):
            raise AssertionError("network should not be used in this test")

    client = PlaywrightCrawlerClient(
        DummySession(),
        safe_mode=False,
        search_scroll_rounds=6,
    )
    captured = {}

    def fake_load_search_result_htmls(url, scroll_rounds=3):
        captured["url"] = url
        captured["scroll_rounds"] = scroll_rounds
        return [f"search:{url}"]

    monkeypatch.setattr(client, "_load_search_result_htmls_via_ui", lambda query, scroll_rounds=3: None)
    monkeypatch.setattr(client, "_load_search_result_htmls", fake_load_search_result_htmls)

    assert client.fetch_search_result_htmls("抗痘博主") == [
        "search:https://www.xiaohongshu.com/search_result?keyword=%E6%8A%97%E7%97%98%E5%8D%9A%E4%B8%BB&source=web_explore_feed"
    ]
    assert captured["scroll_rounds"] == 6


def test_playwright_crawler_client_searches_via_site_input_before_fallback():
    class DummyResponse:
        status = 200

    class DummyBodyLocator:
        def __init__(self, page):
            self.page = page

        def inner_text(self):
            return self.page.body_text

    class EmptyLocator:
        def count(self):
            return 0

    class DummySingleLocator:
        def __init__(self, box):
            self.box = box

        def count(self):
            return 1

        def nth(self, _index):
            return self

        def bounding_box(self):
            return self.box

        def scroll_into_view_if_needed(self, timeout):
            return None

    class DummySearchLocator:
        def __init__(self, page):
            self.page = page

        def count(self):
            return len(self.page.search_hrefs)

        def nth(self, index):
            return DummySingleLocator(
                {"x": 80 + index * 40, "y": 220, "width": 120, "height": 90}
            )

    class DummyKeyboard:
        def __init__(self, page):
            self.page = page
            self.presses = []
            self.typed = []

        def press(self, key):
            self.presses.append(key)
            if key == "Enter":
                self.page.body_text = "search page body"
                self.page.submitted_queries.append("".join(self.typed))

        def type(self, text, delay):
            self.page.type_delays.append(delay)
            self.typed.append(text)

    class DummyPage:
        def __init__(self):
            self.goto_calls = []
            self.closed = False
            self.body_text = "home page body"
            self.submitted_queries = []
            self.type_delays = []
            self.search_hrefs = ["/user/profile/user-101?xsec_source=pc_search"]
            self.mouse_clicks = []
            self.mouse = type(
                "Mouse",
                (),
                {
                    "move": lambda _self, x, y, steps: None,
                    "click": lambda _self, x, y, delay=0: self.mouse_clicks.append((x, y, delay)),
                    "wheel": lambda _self, dx, dy: None,
                },
            )()
            self.keyboard = DummyKeyboard(self)

        def goto(self, url, wait_until, timeout):
            self.goto_calls.append(url)
            self.body_text = "home page body"
            return DummyResponse()

        def wait_for_load_state(self, _state, timeout):
            return None

        def locator(self, selector):
            if selector == "body":
                return DummyBodyLocator(self)
            if selector == "input[type='search']" and self.body_text == "home page body":
                return DummySingleLocator({"x": 20, "y": 24, "width": 240, "height": 32})
            if selector == ".card-bottom-wrapper a.author[href*='/user/profile/']" and self.body_text == "search page body":
                return DummySearchLocator(self)
            return EmptyLocator()

        def content(self):
            if self.body_text == "search page body":
                return """
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-101?xsec_source=pc_search">A</a>
                </div>
                """
            return "<html><body>home</body></html>"

        def wait_for_timeout(self, _ms):
            return None

        def is_closed(self):
            return self.closed

    class DummySession:
        def __init__(self):
            self.page = DummyPage()

        def new_page(self):
            return self.page

    client = PlaywrightCrawlerClient(DummySession(), safe_mode=False)

    htmls = client.fetch_search_result_htmls("抗痘博主")

    assert htmls == [
        """
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-101?xsec_source=pc_search">A</a>
                </div>
                """
    ]
    assert client._page.goto_calls == ["https://www.xiaohongshu.com"]
    assert client._page.submitted_queries == ["抗痘博主"]
    assert "Enter" in client._page.keyboard.presses
    assert len(client._page.mouse_clicks) == 1


def test_playwright_crawler_client_reuses_same_page_across_requests():
    class DummyResponse:
        status = 200

    class DummyLocator:
        def inner_text(self):
            return "正常内容"

        def count(self):
            return 1

    class DummyPage:
        def __init__(self):
            self.goto_calls = []
            self.closed = False

        def goto(self, url, wait_until, timeout):
            self.goto_calls.append(url)
            return DummyResponse()

        def wait_for_load_state(self, _state, timeout):
            return None

        def locator(self, _selector):
            return DummyLocator()

        def content(self):
            return "<html></html>"

        def evaluate(self, _script):
            return None

        def wait_for_timeout(self, _ms):
            return None

        def is_closed(self):
            return self.closed

    class DummySession:
        def __init__(self):
            self.created_pages = []

        def new_page(self):
            page = DummyPage()
            self.created_pages.append(page)
            return page

    session = DummySession()
    client = PlaywrightCrawlerClient(
        session,
        safe_mode=True,
        safe_mode_controller=SafeModeController(
            enabled=True,
            sleep_fn=lambda _seconds: None,
            log_fn=lambda _message: None,
        ),
    )

    assert client.fetch_profile_html("https://example.com/u1") == "<html></html>"
    assert client.fetch_profile_html("https://example.com/u2") == "<html></html>"

    assert len(session.created_pages) == 1
    assert session.created_pages[0].goto_calls == [
        "https://example.com/u1",
        "https://example.com/u2",
    ]


def test_playwright_crawler_client_clicks_profiles_from_active_search_page():
    class DummyResponse:
        status = 200

    class DummyBodyLocator:
        def __init__(self, page):
            self.page = page

        def inner_text(self):
            return self.page.body_text

    class EmptyLocator:
        def count(self):
            return 0

    class DummySingleLocator:
        def __init__(self, box):
            self.box = box

        def count(self):
            return 1

        def nth(self, _index):
            return self

        def bounding_box(self):
            return self.box

        def scroll_into_view_if_needed(self, timeout):
            return None

    class DummySearchAnchor:
        def __init__(self, page, href):
            self.page = page
            self.href = href
            self.hover_calls = []

        def get_attribute(self, name):
            assert name == "href"
            return self.href

        def hover(self, timeout):
            self.hover_calls.append(timeout)

        def bounding_box(self):
            return {"x": 10, "y": 20, "width": 120, "height": 90}

    class DummySearchLocator:
        def __init__(self, page):
            self.page = page

        def count(self):
            return len(self.page.search_hrefs)

        def nth(self, index):
            anchor = DummySearchAnchor(self.page, self.page.search_hrefs[index])
            self.page.anchors.append(anchor)
            return anchor

    class DummyPage:
        def __init__(self):
            self.goto_calls = []
            self.go_back_calls = 0
            self.click_calls = []
            self.back_clicks = 0
            self.closed = False
            self.body_text = "home page body"
            self.anchors = []
            self.search_hrefs = [
                "/user/profile/user-101?xsec_source=pc_search",
                "/user/profile/user-102?xsec_source=pc_search",
            ]
            self.mouse_moves = []
            self.mouse_clicks = []
            self.mouse_wheels = []
            self.search_queries = []
            self.mouse = type(
                "Mouse",
                (),
                {
                    "move": lambda _self, x, y, steps: self.mouse_moves.append((x, y, steps)),
                    "click": lambda _self, x, y, delay=0: self._handle_mouse_click(x, y, delay),
                    "wheel": lambda _self, dx, dy: self.mouse_wheels.append((dx, dy)),
                },
            )()
            self.keyboard = type(
                "Keyboard",
                (),
                {
                    "press": lambda _self, key: self._handle_key_press(key),
                    "type": lambda _self, text, delay=0: self._handle_type(text, delay),
                },
            )()

        def goto(self, url, wait_until, timeout):
            self.goto_calls.append(url)
            self.body_text = "home page body"
            return DummyResponse()

        def wait_for_load_state(self, _state, timeout):
            return None

        def locator(self, selector):
            if selector == "body":
                return DummyBodyLocator(self)
            if selector == "input[type='search']" and self.body_text in {"home page body", "search page body"}:
                return DummySingleLocator({"x": 20, "y": 24, "width": 240, "height": 32})
            if selector == ".card-bottom-wrapper a.author[href*='/user/profile/']" and self.body_text == "search page body":
                return DummySearchLocator(self)
            if selector == "button[aria-label='返回']" and self.body_text == "profile page body":
                return DummySingleLocator({"x": 18, "y": 18, "width": 28, "height": 28})
            return EmptyLocator()

        def content(self):
            if self.body_text == "search page body":
                return """
                <div class="note-item">
                  <div class="footer">
                    <div class="card-bottom-wrapper">
                      <a class="author" href="/user/profile/user-101?xsec_source=pc_search">A</a>
                      <a class="author" href="/user/profile/user-102?xsec_source=pc_search">B</a>
                    </div>
                  </div>
                </div>
                """
            return "<html><body>profile page body</body></html>"

        def evaluate(self, _script):
            return None

        def wait_for_timeout(self, _ms):
            return None

        def is_closed(self):
            return self.closed

        def go_back(self, wait_until, timeout):
            self.go_back_calls += 1
            self.body_text = "search page body"
            return DummyResponse()

        def _handle_mouse_click(self, x, y, delay):
            self.mouse_clicks.append((x, y, delay))
            if self.body_text == "home page body":
                return
            if self.body_text == "profile page body":
                self.back_clicks += 1
                self.body_text = "search page body"
                return
            href = self.search_hrefs[len(self.click_calls)]
            self.click_calls.append((href, delay))
            self.body_text = "profile page body"

        def _handle_type(self, text, delay):
            self.search_queries.append((text, delay))

        def _handle_key_press(self, key):
            if key == "Enter":
                self.body_text = "search page body"

    class DummySession:
        def __init__(self):
            self.created_pages = []

        def new_page(self):
            page = DummyPage()
            self.created_pages.append(page)
            return page

    session = DummySession()
    client = PlaywrightCrawlerClient(
        session,
        safe_mode=True,
        safe_mode_controller=SafeModeController(
            enabled=True,
            sleep_fn=lambda _seconds: None,
            log_fn=lambda _message: None,
        ),
    )

    client.fetch_search_result_htmls("抗痘博主")
    client.fetch_profile_html("https://www.xiaohongshu.com/user/profile/user-101?xsec_source=pc_search")
    client.fetch_profile_html("https://www.xiaohongshu.com/user/profile/user-102?xsec_source=pc_search")

    assert len(session.created_pages) == 1
    page = session.created_pages[0]
    assert page.goto_calls == [
        "https://www.xiaohongshu.com"
    ]
    assert [item[0] for item in page.search_queries] == ["抗痘博主"]
    assert [item[0] for item in page.click_calls] == [
        "/user/profile/user-101?xsec_source=pc_search",
        "/user/profile/user-102?xsec_source=pc_search",
    ]
    assert len(page.mouse_clicks) == 4
    assert page.back_clicks == 1
    assert page.go_back_calls == 0
    assert len(page.anchors) >= 2
    assert page.anchors[0].hover_calls == [5000]


def test_playwright_crawler_client_persists_disk_cache(tmp_path, monkeypatch):
    class DummySession:
        def new_page(self):
            raise AssertionError("network should not be used in this test")

    logs = []
    client = PlaywrightCrawlerClient(
        DummySession(),
        safe_mode=False,
        cache_dir=tmp_path,
        safe_mode_controller=SafeModeController(
            enabled=True,
            sleep_fn=lambda _seconds: None,
            log_fn=logs.append,
        ),
    )
    calls = {"profile": 0, "search": 0}

    def fake_load_html(url):
        calls["profile"] += 1
        return f"profile:{url}"

    def fake_load_search_result_htmls(url, scroll_rounds=3):
        calls["search"] += 1
        return [f"search:{url}:1", f"search:{url}:2"]

    monkeypatch.setattr(client, "_load_html", fake_load_html)
    monkeypatch.setattr(client, "_load_search_result_htmls_via_ui", lambda query, scroll_rounds=3: None)
    monkeypatch.setattr(client, "_load_search_result_htmls", fake_load_search_result_htmls)

    profile_url = "https://example.com/u1"
    query = "美妆博主"
    assert client.fetch_profile_html(profile_url) == f"profile:{profile_url}"
    assert client.fetch_search_result_htmls(query) == [
        "search:https://www.xiaohongshu.com/search_result?keyword=%E7%BE%8E%E5%A6%86%E5%8D%9A%E4%B8%BB&source=web_explore_feed:1",
        "search:https://www.xiaohongshu.com/search_result?keyword=%E7%BE%8E%E5%A6%86%E5%8D%9A%E4%B8%BB&source=web_explore_feed:2",
    ]

    cold_client = PlaywrightCrawlerClient(
        DummySession(),
        safe_mode=False,
        cache_dir=tmp_path,
    )

    def fail_load_html(_url):
        raise AssertionError("should have loaded profile from disk cache")

    def fail_load_search_result_htmls(_url, scroll_rounds=3):
        raise AssertionError("should have loaded search results from disk cache")

    monkeypatch.setattr(cold_client, "_load_html", fail_load_html)
    monkeypatch.setattr(cold_client, "_load_search_result_htmls_via_ui", lambda query, scroll_rounds=3: None)
    monkeypatch.setattr(cold_client, "_load_search_result_htmls", fail_load_search_result_htmls)

    assert cold_client.fetch_profile_html(profile_url) == f"profile:{profile_url}"
    assert cold_client.fetch_search_result_htmls(query) == [
        "search:https://www.xiaohongshu.com/search_result?keyword=%E7%BE%8E%E5%A6%86%E5%8D%9A%E4%B8%BB&source=web_explore_feed:1",
        "search:https://www.xiaohongshu.com/search_result?keyword=%E7%BE%8E%E5%A6%86%E5%8D%9A%E4%B8%BB&source=web_explore_feed:2",
    ]
    assert calls == {"profile": 1, "search": 1}
    assert "safe-mode: wrote profile cache to disk" in logs
    assert "safe-mode: wrote search cache to disk" in logs


def test_playwright_crawler_client_expires_disk_cache_after_ttl(tmp_path, monkeypatch):
    class DummySession:
        def new_page(self):
            raise AssertionError("network should not be used in this test")

    profile_url = "https://example.com/u1"
    logs = []
    client = PlaywrightCrawlerClient(
        DummySession(),
        safe_mode=False,
        cache_dir=tmp_path,
        cache_ttl_days=7,
        safe_mode_controller=SafeModeController(
            enabled=True,
            sleep_fn=lambda _seconds: None,
            log_fn=logs.append,
        ),
    )

    def fake_load_html(url):
        return f"profile:{url}"

    monkeypatch.setattr(client, "_load_html", fake_load_html)
    assert client.fetch_profile_html(profile_url) == f"profile:{profile_url}"

    stale_client = PlaywrightCrawlerClient(
        DummySession(),
        safe_mode=False,
        cache_dir=tmp_path,
        cache_ttl_days=7,
        time_fn=lambda: time.time() + 8 * 24 * 60 * 60,
        safe_mode_controller=SafeModeController(
            enabled=True,
            sleep_fn=lambda _seconds: None,
            log_fn=logs.append,
        ),
    )

    calls = {"profile": 0}

    def refreshed_load_html(url):
        calls["profile"] += 1
        return f"fresh:{url}"

    monkeypatch.setattr(stale_client, "_load_html", refreshed_load_html)

    assert stale_client.fetch_profile_html(profile_url) == f"fresh:{profile_url}"
    assert calls == {"profile": 1}
    assert "safe-mode: disk cache expired for profile" in logs
