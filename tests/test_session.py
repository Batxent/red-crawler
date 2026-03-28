from red_crawler.session import (
    classify_high_risk_page,
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
