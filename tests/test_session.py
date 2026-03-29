import time

from red_crawler.session import (
    BrowserSession,
    classify_high_risk_page,
    PlaywrightCrawlerClient,
    RiskControlTriggered,
    SafeModeController,
    extract_note_detail_urls,
)


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


def test_safe_mode_controller_adds_jitter_and_backoff():
    sleeps = []
    logs = []

    class FakeRandom:
        def __init__(self):
            self.values = iter([1.8, 2.1, 1.7, 10.0, 25.0])

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

    assert sleeps == [1.8, 2.1, 1.7, 10.0, 25.0]
    assert logs == [
        "safe-mode: sleeping 1.8s before request #1",
        "safe-mode: sleeping 2.1s before request #2",
        "safe-mode: sleeping 1.7s before request #3",
        "safe-mode: taking a longer 10.0s pause after 3 requests",
        "safe-mode: backing off for 25.0s after risk signal #1",
    ]


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
