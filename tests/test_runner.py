import red_crawler.runner as runner_module
from red_crawler.runner import (
    CrawlConfig,
    HomefeedCrawlConfig,
    SearchCrawlConfig,
    run_crawl_homefeed,
    run_crawl_homefeed_with_client,
    run_crawl_search_with_client,
    run_crawl_seed_with_client,
)
from red_crawler.session import RiskControlTriggered


class FakeClient:
    def __init__(self, pages, failures=None, note_pages=None, search_pages=None):
        self.pages = pages
        self.failures = failures or set()
        self.note_pages = note_pages or {}
        self.search_pages = search_pages or {}
        self.search_queries = []
        self.homefeed_target_profile_count = None
        self.homefeed_existing_account_ids = ()

    def fetch_profile_html(self, profile_url):
        if profile_url in self.failures:
            raise RuntimeError("profile page unavailable")
        return self.pages[profile_url]

    def fetch_note_recommendation_html(self, profile_url):
        return self.note_pages.get(profile_url, [])

    def fetch_search_result_htmls(self, query):
        self.search_queries.append(query)
        payload = self.search_pages.get(query, [])
        if isinstance(payload, str):
            return [payload]
        return payload

    def fetch_homefeed_result_htmls(
        self,
        source_url,
        *,
        target_profile_count=None,
        existing_account_ids=(),
    ):
        self.homefeed_target_profile_count = target_profile_count
        self.homefeed_existing_account_ids = existing_account_ids
        payload = self.search_pages.get(f"homefeed:{source_url}", [])
        if isinstance(payload, str):
            return [payload]
        return payload


def test_run_crawl_seed_collects_accounts_leads_and_failures():
    pages = {
        "https://www.xiaohongshu.com/user/profile/user-001": """
        <section class="profile">
          <div class="user-id">账号ID: user-001</div>
          <h1 class="user-name">Seed</h1>
          <div class="user-bio">商务合作 vx: seed_studio</div>
        </section>
        <section class="recommend-users">
          <a class="recommended-user" data-user-id="user-002" href="/user/profile/user-002">
            <span class="nickname">U2</span>
          </a>
          <a class="recommended-user" data-user-id="user-003" href="/user/profile/user-003">
            <span class="nickname">U3</span>
          </a>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-002": """
        <section class="profile">
          <div class="user-id">账号ID: user-002</div>
          <h1 class="user-name">U2</h1>
          <div class="user-bio">邮箱：u2@example.com</div>
        </section>
        """,
    }
    client = FakeClient(
        pages=pages,
        failures={"https://www.xiaohongshu.com/user/profile/user-003"},
    )
    config = CrawlConfig(
        seed_url="https://www.xiaohongshu.com/user/profile/user-001",
        storage_state="state.json",
        output_dir="out",
        max_accounts=5,
        max_depth=1,
        include_note_recommendations=False,
    )

    result = run_crawl_seed_with_client(config, client)

    assert [account.account_id for account in result.accounts] == [
        "user-001",
        "user-002",
        "user-003",
    ]
    assert result.accounts[1].source_type == "profile_recommendation"
    assert result.accounts[1].discovery_depth == 1
    assert result.accounts[2].crawl_status == "failed"
    assert result.accounts[0].creator_segment == "general"
    assert result.accounts[0].relevance_score == 1.0
    assert result.run_report.succeeded_accounts == 2
    assert result.run_report.failed_accounts == 1
    assert result.run_report.lead_counts == {"email": 1, "wechat": 1}
    assert result.run_report.errors == [
        {
            "profile_url": "https://www.xiaohongshu.com/user/profile/user-003",
            "error": "profile page unavailable",
        }
    ]


def test_run_crawl_homefeed_collects_profiles_from_author_links():
    homefeed_url = "https://www.xiaohongshu.com/explore?channel_id=homefeed.cosmetics_v3"
    pages = {
        "https://www.xiaohongshu.com/user/profile/user-201?xsec_source=pc_feed": """
        <section class="profile">
          <div class="user-id">账号ID: user-201</div>
          <h1 class="user-name">A</h1>
          <div class="user-bio">彩妆博主 邮箱：a@example.com</div>
        </section>
        """,
    }
    homefeed_html = """
    <div class="note-item">
      <a class="cover" href="/explore/note-001">不要点帖子</a>
      <div class="card-bottom-wrapper">
        <a class="author" href="/user/profile/user-201?xsec_source=pc_feed">A</a>
      </div>
    </div>
    """
    client = FakeClient(
        pages=pages,
        search_pages={f"homefeed:{homefeed_url}": homefeed_html},
    )
    config = HomefeedCrawlConfig(
        output_dir="out",
        homefeed_url=homefeed_url,
        max_accounts=5,
    )

    result = run_crawl_homefeed_with_client(config, client)

    assert [account.account_id for account in result.accounts] == ["user-201"]
    assert result.accounts[0].source_type == "homefeed"
    assert result.contact_leads[0].normalized_value == "a@example.com"
    assert result.run_report.seed_url == f"homefeed:{homefeed_url}"


def test_run_crawl_homefeed_collects_profiles_from_feed_state():
    homefeed_url = "https://www.xiaohongshu.com/explore?channel_id=homefeed.cosmetics_v3"
    profile_url = (
        "https://www.xiaohongshu.com/user/profile/user-301"
        "?xsec_token=token-301&xsec_source=pc_feed"
    )
    pages = {
        profile_url: """
        <section class="profile">
          <div class="user-id">账号ID: user-301</div>
          <h1 class="user-name">B</h1>
          <div class="user-bio">美妆博主 邮箱：b@example.com</div>
        </section>
        """,
    }
    homefeed_html = """
    <script>
      window.__INITIAL_STATE__ = {
        "feeds":[{"noteCard":{"user":{
          "nickname":"B",
          "nickName":"B",
          "userId":"user-301",
          "xsecToken":"token-301"
        }}}]
      }
    </script>
    """
    client = FakeClient(
        pages=pages,
        search_pages={f"homefeed:{homefeed_url}": homefeed_html},
    )
    config = HomefeedCrawlConfig(
        output_dir="out",
        homefeed_url=homefeed_url,
        max_accounts=5,
    )

    result = run_crawl_homefeed_with_client(config, client)

    assert [account.account_id for account in result.accounts] == ["user-301"]
    assert result.contact_leads[0].normalized_value == "b@example.com"


def test_run_crawl_homefeed_skips_existing_accounts_and_backfills():
    homefeed_url = "https://www.xiaohongshu.com/explore?channel_id=homefeed.cosmetics_v3"
    new_profile_url = "https://www.xiaohongshu.com/user/profile/user-new?xsec_source=pc_feed"
    pages = {
        new_profile_url: """
        <section class="profile">
          <div class="user-id">账号ID: user-new</div>
          <h1 class="user-name">New</h1>
          <div class="user-bio">彩妆博主 邮箱：new@example.com</div>
        </section>
        """,
    }
    homefeed_html = """
    <div class="note-item">
      <div class="card-bottom-wrapper">
        <a class="author" href="/user/profile/user-old?xsec_source=pc_feed">Old</a>
      </div>
    </div>
    <div class="note-item">
      <div class="card-bottom-wrapper">
        <a class="author" href="/user/profile/user-new?xsec_source=pc_feed">New</a>
      </div>
    </div>
    """
    client = FakeClient(
        pages=pages,
        search_pages={f"homefeed:{homefeed_url}": homefeed_html},
    )
    config = HomefeedCrawlConfig(
        output_dir="out",
        homefeed_url=homefeed_url,
        max_accounts=1,
        existing_account_ids=("user-old",),
    )

    result = run_crawl_homefeed_with_client(config, client)

    assert client.homefeed_target_profile_count == 1
    assert client.homefeed_existing_account_ids == ("user-old",)
    assert [account.account_id for account in result.accounts] == ["user-new"]
    assert result.contact_leads[0].normalized_value == "new@example.com"


def test_run_crawl_homefeed_rotates_local_proxies_after_403(tmp_path, monkeypatch):
    proxy_list = tmp_path / "proxies.txt"
    proxy_list.write_text(
        "http://proxy-one:8000\nhttp://proxy-two:8000\n",
        encoding="utf-8",
    )
    seen_proxies = []
    outcomes = iter(
        [
            runner_module.CrawlResult(
                accounts=[],
                contact_leads=[],
                run_report=runner_module.RunReport(
                    seed_url="homefeed:test",
                    attempted_accounts=0,
                    succeeded_accounts=0,
                    failed_accounts=0,
                    lead_counts={},
                    aborted=True,
                    abort_reason="http_403",
                    errors=[{"source": "homefeed", "error": "http_403"}],
                ),
            ),
            runner_module.CrawlResult(
                accounts=[],
                contact_leads=[],
                run_report=runner_module.RunReport(
                    seed_url="homefeed:test",
                    attempted_accounts=0,
                    succeeded_accounts=0,
                    failed_accounts=0,
                    lead_counts={},
                    errors=[],
                ),
            ),
        ]
    )

    class FakeBrowserSession:
        def __init__(self, *_args, **kwargs):
            seen_proxies.append(kwargs.get("proxy_url"))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(runner_module, "BrowserSession", FakeBrowserSession)
    monkeypatch.setattr(
        runner_module,
        "_build_playwright_client",
        lambda _config, session: session,
    )
    monkeypatch.setattr(
        runner_module,
        "run_crawl_homefeed_with_client",
        lambda _config, _client: next(outcomes),
    )

    result = run_crawl_homefeed(
        HomefeedCrawlConfig(
            output_dir="out",
            rotation_mode="session",
            rotation_retries=1,
            proxy_list=str(proxy_list),
        )
    )

    assert result.run_report.aborted is False
    assert seen_proxies == ["http://proxy-one:8000", "http://proxy-two:8000"]


def test_run_crawl_homefeed_retries_with_default_state_after_login_required(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state.json").write_text("{}", encoding="utf-8")
    seen_storage_states = []
    outcomes = iter(
        [
            runner_module.CrawlResult(
                accounts=[],
                contact_leads=[],
                run_report=runner_module.RunReport(
                    seed_url="homefeed:test",
                    attempted_accounts=0,
                    succeeded_accounts=0,
                    failed_accounts=0,
                    lead_counts={},
                    aborted=True,
                    abort_reason="login_required",
                    errors=[{"source": "homefeed", "error": "login_required"}],
                ),
            ),
            runner_module.CrawlResult(
                accounts=[],
                contact_leads=[],
                run_report=runner_module.RunReport(
                    seed_url="homefeed:test",
                    attempted_accounts=0,
                    succeeded_accounts=0,
                    failed_accounts=0,
                    lead_counts={},
                    errors=[],
                ),
            ),
        ]
    )

    class FakeBrowserSession:
        def __init__(self, storage_state, **_kwargs):
            seen_storage_states.append(storage_state)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(runner_module, "BrowserSession", FakeBrowserSession)
    monkeypatch.setattr(
        runner_module,
        "_build_playwright_client",
        lambda _config, session: session,
    )
    monkeypatch.setattr(
        runner_module,
        "run_crawl_homefeed_with_client",
        lambda _config, _client: next(outcomes),
    )

    result = run_crawl_homefeed(HomefeedCrawlConfig(output_dir="out"))

    assert result.run_report.aborted is False
    assert seen_storage_states == ["", "state.json"]


def test_run_crawl_seed_filters_successful_accounts_by_gender():
    pages = {
        "https://www.xiaohongshu.com/user/profile/user-001": """
        <section class="profile">
          <div class="user-id">账号ID: user-001</div>
          <h1 class="user-name">Seed</h1>
          <div class="user-bio">女生穿搭分享 vx: seed_studio</div>
        </section>
        <section class="recommend-users">
          <a class="recommended-user" data-user-id="user-002" href="/user/profile/user-002">
            <span class="nickname">U2</span>
          </a>
          <a class="recommended-user" data-user-id="user-003" href="/user/profile/user-003">
            <span class="nickname">U3</span>
          </a>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-002": """
        <section class="profile">
          <div class="user-id">账号ID: user-002</div>
          <h1 class="user-name">U2</h1>
          <div class="user-bio">男生护肤 邮箱：u2@example.com</div>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-003": """
        <section class="profile">
          <div class="user-id">账号ID: user-003</div>
          <h1 class="user-name">U3</h1>
          <div class="user-bio">女生护肤 邮箱：u3@example.com</div>
        </section>
        """,
    }
    client = FakeClient(pages=pages)
    config = CrawlConfig(
        seed_url="https://www.xiaohongshu.com/user/profile/user-001",
        storage_state="state.json",
        output_dir="out",
        max_accounts=5,
        max_depth=1,
        include_note_recommendations=False,
        gender_filter="男",
    )

    result = run_crawl_seed_with_client(config, client)

    assert [account.account_id for account in result.accounts] == ["user-002"]
    assert result.accounts[0].visible_metadata["gender"] == "male"
    assert [lead.account_id for lead in result.contact_leads] == ["user-002"]
    assert result.run_report.succeeded_accounts == 1
    assert result.run_report.lead_counts == {"email": 1}


def test_run_crawl_seed_marks_shell_error_page_as_failed():
    client = FakeClient(
        pages={
            "https://www.xiaohongshu.com/user/profile/LL16141319": """
            <html>
              <body>
                <div>未连接到服务器，刷新一下试试</div>
                <button>点击刷新</button>
              </body>
            </html>
            """
        }
    )
    config = CrawlConfig(
        seed_url="https://www.xiaohongshu.com/user/profile/LL16141319",
        storage_state="state.json",
        output_dir="out",
        max_accounts=5,
        max_depth=1,
        include_note_recommendations=False,
    )

    result = run_crawl_seed_with_client(config, client)

    assert result.run_report.succeeded_accounts == 0
    assert result.run_report.failed_accounts == 1
    assert result.accounts[0].crawl_status == "failed"
    assert "profile page did not load" in result.accounts[0].crawl_error


def test_run_crawl_seed_expands_candidates_from_search_results():
    pages = {
        "https://www.xiaohongshu.com/user/profile/user-001": """
        <section class="profile">
          <div class="user-id">账号ID: user-001</div>
          <h1 class="user-name">Seed</h1>
          <div class="user-bio">商务合作 vx: seed_studio</div>
          <div class="user-tags">
            <span>北京</span>
            <span>美妆博主</span>
          </div>
          <div class="user-followers">粉丝 35.1万</div>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-002?xsec_source=pc_search": """
        <section class="profile">
          <div class="user-id">账号ID: user-002</div>
          <h1 class="user-name">U2</h1>
          <div class="user-bio">北京美妆博主 邮箱：u2@example.com</div>
          <div class="user-tags">
            <span>北京</span>
            <span>美妆博主</span>
          </div>
          <div class="user-followers">粉丝 1296</div>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-003?xsec_source=pc_search": """
        <section class="profile">
          <div class="user-id">账号ID: user-003</div>
          <h1 class="user-name">U3</h1>
          <div class="user-bio">摄影爱好者</div>
          <div class="user-tags">
            <span>摄影</span>
          </div>
          <div class="user-followers">粉丝 87</div>
        </section>
        """,
    }
    search_pages = {
        "美妆博主": [
            """
            <div class="note-item">
              <div class="footer">
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-002?xsec_source=pc_search">U2</a>
                </div>
              </div>
            </div>
            <div class="note-item">
              <div class="footer">
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-003?xsec_source=pc_search">U3</a>
                </div>
              </div>
            </div>
            """
        ]
    }
    client = FakeClient(pages=pages, search_pages=search_pages)
    config = CrawlConfig(
        seed_url="https://www.xiaohongshu.com/user/profile/user-001",
        storage_state="state.json",
        output_dir="out",
        max_accounts=5,
        max_depth=1,
        include_note_recommendations=False,
    )

    result = run_crawl_seed_with_client(config, client)

    assert [account.account_id for account in result.accounts] == ["user-001", "user-002"]
    assert result.accounts[1].source_type == "search_result"
    assert result.accounts[1].discovery_depth == 1
    assert result.accounts[1].creator_segment == "creator"
    assert result.accounts[1].relevance_score >= 0.7
    assert result.run_report.succeeded_accounts == 2
    assert result.run_report.lead_counts == {"email": 1, "wechat": 1}


def test_run_crawl_seed_uses_multiple_search_queries_to_fill_more_candidates():
    pages = {
        "https://www.xiaohongshu.com/user/profile/user-001": """
        <section class="profile">
          <div class="user-id">账号ID: user-001</div>
          <h1 class="user-name">Seed</h1>
          <div class="user-bio">美妆护肤内容分享 抗痘经验 痘肌护理</div>
          <div class="user-tags">
            <span>美妆博主</span>
          </div>
          <div class="user-followers">粉丝 35.1万</div>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-002?xsec_source=pc_search": """
        <section class="profile">
          <div class="user-id">账号ID: user-002</div>
          <h1 class="user-name">U2</h1>
          <div class="user-bio">护肤博主 邮箱：u2@example.com</div>
          <div class="user-tags"><span>护肤博主</span></div>
          <div class="user-followers">粉丝 2.1万</div>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-003?xsec_source=pc_search": """
        <section class="profile">
          <div class="user-id">账号ID: user-003</div>
          <h1 class="user-name">U3</h1>
          <div class="user-bio">彩妆博主 邮箱：u3@example.com</div>
          <div class="user-tags"><span>彩妆博主</span></div>
          <div class="user-followers">粉丝 3.6万</div>
        </section>
        """,
    }
    search_pages = {
        "美妆博主": [
            """
            <div class="note-item">
              <div class="footer">
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-002?xsec_source=pc_search">U2</a>
                </div>
              </div>
            </div>
            """
        ],
        "护肤博主": [""],
        "彩妆博主": [
            """
            <div class="note-item">
              <div class="footer">
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-003?xsec_source=pc_search">U3</a>
                </div>
              </div>
            </div>
            """
        ],
        "化妆博主": [""],
        "抗痘博主": [
            """
            <div class="note-item">
              <div class="footer">
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-003?xsec_source=pc_search">U3</a>
                </div>
              </div>
            </div>
            """
        ],
        "痘肌护肤": [""],
    }
    client = FakeClient(pages=pages, search_pages=search_pages)
    config = CrawlConfig(
        seed_url="https://www.xiaohongshu.com/user/profile/user-001",
        storage_state="state.json",
        output_dir="out",
        max_accounts=10,
        max_depth=1,
        include_note_recommendations=False,
    )

    result = run_crawl_seed_with_client(config, client)

    assert [account.account_id for account in result.accounts] == [
        "user-001",
        "user-002",
        "user-003",
    ]
    assert client.search_queries == [
        "美妆博主",
        "护肤博主",
        "彩妆博主",
        "化妆博主",
        "抗痘博主",
        "痘肌护肤",
    ]


def test_run_crawl_seed_dedupes_same_account_across_profile_url_variants():
    pages = {
        "https://www.xiaohongshu.com/user/profile/user-001": """
        <section class="profile">
          <div class="user-id">账号ID: user-001</div>
          <h1 class="user-name">Seed</h1>
          <div class="user-bio">美妆护肤内容分享</div>
          <div class="user-tags"><span>美妆博主</span></div>
          <div class="user-followers">粉丝 35.1万</div>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-002?xsec_source=pc_search": """
        <section class="profile">
          <div class="user-id">账号ID: user-002</div>
          <h1 class="user-name">U2</h1>
          <div class="user-bio">护肤博主 邮箱：u2@example.com</div>
          <div class="user-tags"><span>护肤博主</span></div>
          <div class="user-followers">粉丝 2.1万</div>
        </section>
        """,
    }
    search_pages = {
        "美妆博主": [
            """
            <div class="note-item">
              <div class="footer">
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-002?xsec_source=pc_search">U2</a>
                </div>
              </div>
            </div>
            """
        ],
        "护肤博主": [
            """
            <div class="note-item">
              <div class="footer">
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-002/63184102000000001103a3e7?xsec_token=abc&xsec_source=pc_user">U2</a>
                </div>
              </div>
            </div>
            """
        ],
        "彩妆博主": [""],
        "化妆博主": [""],
    }
    client = FakeClient(pages=pages, search_pages=search_pages)
    config = CrawlConfig(
        seed_url="https://www.xiaohongshu.com/user/profile/user-001",
        storage_state="state.json",
        output_dir="out",
        max_accounts=10,
        max_depth=1,
        include_note_recommendations=False,
    )

    result = run_crawl_seed_with_client(config, client)

    assert [account.account_id for account in result.accounts] == ["user-001", "user-002"]


def test_run_crawl_seed_allows_second_layer_search_expansion():
    pages = {
        "https://www.xiaohongshu.com/user/profile/user-001": """
        <section class="profile">
          <div class="user-id">账号ID: user-001</div>
          <h1 class="user-name">Seed</h1>
          <div class="user-bio">美妆内容分享</div>
          <div class="user-tags"><span>美妆博主</span></div>
          <div class="user-followers">粉丝 35.1万</div>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-002?xsec_source=pc_search": """
        <section class="profile">
          <div class="user-id">账号ID: user-002</div>
          <h1 class="user-name">U2</h1>
          <div class="user-bio">护肤博主</div>
          <div class="user-tags"><span>护肤博主</span></div>
          <div class="user-followers">粉丝 2.1万</div>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-004?xsec_source=pc_search": """
        <section class="profile">
          <div class="user-id">账号ID: user-004</div>
          <h1 class="user-name">U4</h1>
          <div class="user-bio">彩妆博主 邮箱：u4@example.com</div>
          <div class="user-tags"><span>彩妆博主</span></div>
          <div class="user-followers">粉丝 6.8万</div>
        </section>
        """,
    }
    search_pages = {
        "美妆博主": [
            """
            <div class="note-item">
              <div class="footer">
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-002?xsec_source=pc_search">U2</a>
                </div>
              </div>
            </div>
            """
        ],
        "护肤博主": [""],
        "彩妆博主": [""],
        "化妆博主": [""],
    }
    class SecondLayerClient(FakeClient):
        def fetch_search_result_htmls(self, query):
            count = self.search_queries.count(query)
            self.search_queries.append(query)
            if query == "护肤博主" and count >= 1:
                return [
                    """
                    <div class="note-item">
                      <div class="footer">
                        <div class="card-bottom-wrapper">
                          <a class="author" href="/user/profile/user-004?xsec_source=pc_search">U4</a>
                        </div>
                      </div>
                    </div>
                    """
                ]
            payload = self.search_pages.get(query, [])
            if isinstance(payload, str):
                return [payload]
            return payload

    client = SecondLayerClient(pages=pages, search_pages=search_pages)
    config = CrawlConfig(
        seed_url="https://www.xiaohongshu.com/user/profile/user-001",
        storage_state="state.json",
        output_dir="out",
        max_accounts=10,
        max_depth=2,
        include_note_recommendations=False,
    )

    result = run_crawl_seed_with_client(config, client)

    assert [account.account_id for account in result.accounts] == [
        "user-001",
        "user-002",
        "user-004",
    ]
    assert result.accounts[1].discovery_depth == 1
    assert result.accounts[2].source_type == "search_result"
    assert result.accounts[2].discovery_depth == 2
    assert client.search_queries.count("护肤博主") >= 2


def test_run_crawl_seed_uses_multiple_search_pages_per_query():
    pages = {
        "https://www.xiaohongshu.com/user/profile/user-001": """
        <section class="profile">
          <div class="user-id">账号ID: user-001</div>
          <h1 class="user-name">Seed</h1>
          <div class="user-bio">美妆内容分享</div>
          <div class="user-tags"><span>美妆博主</span></div>
          <div class="user-followers">粉丝 35.1万</div>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-002?xsec_source=pc_search": """
        <section class="profile">
          <div class="user-id">账号ID: user-002</div>
          <h1 class="user-name">U2</h1>
          <div class="user-bio">美妆博主</div>
          <div class="user-tags"><span>美妆博主</span></div>
          <div class="user-followers">粉丝 2.1万</div>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-003?xsec_source=pc_search": """
        <section class="profile">
          <div class="user-id">账号ID: user-003</div>
          <h1 class="user-name">U3</h1>
          <div class="user-bio">彩妆博主</div>
          <div class="user-tags"><span>彩妆博主</span></div>
          <div class="user-followers">粉丝 3.6万</div>
        </section>
        """,
    }
    search_pages = {
        "美妆博主": [
            """
            <div class="note-item">
              <div class="footer">
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-002?xsec_source=pc_search">U2</a>
                </div>
              </div>
            </div>
            """,
            """
            <div class="note-item">
              <div class="footer">
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-003?xsec_source=pc_search">U3</a>
                </div>
              </div>
            </div>
            """,
        ],
        "护肤博主": [""],
        "彩妆博主": [""],
        "化妆博主": [""],
    }
    client = FakeClient(pages=pages, search_pages=search_pages)
    config = CrawlConfig(
        seed_url="https://www.xiaohongshu.com/user/profile/user-001",
        storage_state="state.json",
        output_dir="out",
        max_accounts=10,
        max_depth=1,
        include_note_recommendations=False,
    )

    result = run_crawl_seed_with_client(config, client)

    assert [account.account_id for account in result.accounts] == [
        "user-001",
        "user-002",
        "user-003",
    ]


def test_run_crawl_seed_aborts_gracefully_when_risk_control_triggers():
    class RiskyClient(FakeClient):
        def fetch_search_result_htmls(self, query):
            raise RiskControlTriggered("risk control threshold reached")

    pages = {
        "https://www.xiaohongshu.com/user/profile/user-001": """
        <section class="profile">
          <div class="user-id">账号ID: user-001</div>
          <h1 class="user-name">Seed</h1>
          <div class="user-bio">美妆内容分享</div>
          <div class="user-tags"><span>美妆博主</span></div>
          <div class="user-followers">粉丝 35.1万</div>
        </section>
        """,
    }
    client = RiskyClient(pages=pages)
    config = CrawlConfig(
        seed_url="https://www.xiaohongshu.com/user/profile/user-001",
        storage_state="state.json",
        output_dir="out",
        max_accounts=10,
        max_depth=1,
        include_note_recommendations=False,
        safe_mode=True,
    )

    result = run_crawl_seed_with_client(config, client)

    assert [account.account_id for account in result.accounts] == ["user-001"]
    assert result.run_report.aborted is True
    assert result.run_report.abort_reason == "risk control threshold reached"
    assert result.run_report.errors[-1]["error"] == "risk control threshold reached"


def test_run_crawl_search_collects_users_for_one_search_term():
    pages = {
        "https://www.xiaohongshu.com/user/profile/user-201?xsec_source=pc_search": """
        <section class="profile">
          <div class="user-id">账号ID: user-201</div>
          <h1 class="user-name">A</h1>
          <div class="user-bio">抗痘护肤博主 邮箱：a@example.com</div>
          <div class="user-tags"><span>护肤博主</span></div>
          <div class="user-followers">粉丝 2.1万</div>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-202?xsec_source=pc_search": """
        <section class="profile">
          <div class="user-id">账号ID: user-202</div>
          <h1 class="user-name">B</h1>
          <div class="user-bio">彩妆博主</div>
          <div class="user-tags"><span>彩妆博主</span></div>
          <div class="user-followers">粉丝 1.5万</div>
        </section>
        """,
    }
    search_pages = {
        "抗痘博主": [
            """
            <div class="note-item">
              <div class="footer">
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-201?xsec_source=pc_search">A</a>
                  <a class="author" href="/user/profile/user-202?xsec_source=pc_search">B</a>
                </div>
              </div>
            </div>
            """
        ]
    }
    client = FakeClient(pages=pages, search_pages=search_pages)
    config = SearchCrawlConfig(
        search_term="抗痘博主",
        storage_state="state.json",
        output_dir="out",
        max_accounts=5,
    )

    result = run_crawl_search_with_client(config, client)

    assert [account.account_id for account in result.accounts] == ["user-201", "user-202"]
    assert result.accounts[0].source_type == "search_result"
    assert result.run_report.seed_url == "search:抗痘博主"
    assert result.run_report.lead_counts == {"email": 1}


def test_run_crawl_search_dedupes_same_user_across_search_url_variants():
    pages = {
        "https://www.xiaohongshu.com/user/profile/user-201?xsec_source=pc_search": """
        <section class="profile">
          <div class="user-id">账号ID: user-201</div>
          <h1 class="user-name">A</h1>
          <div class="user-bio">抗痘护肤博主</div>
          <div class="user-tags"><span>护肤博主</span></div>
          <div class="user-followers">粉丝 2.1万</div>
        </section>
        """,
    }
    search_pages = {
        "抗痘博主": [
            """
            <div class="note-item">
              <div class="footer">
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-201?xsec_source=pc_search">A</a>
                  <a class="author" href="/user/profile/user-201/63184102000000001103a3e7?xsec_token=abc&xsec_source=pc_user">A</a>
                </div>
              </div>
            </div>
            """
        ]
    }
    client = FakeClient(pages=pages, search_pages=search_pages)
    config = SearchCrawlConfig(
        search_term="抗痘博主",
        storage_state="state.json",
        output_dir="out",
        max_accounts=5,
    )

    result = run_crawl_search_with_client(config, client)

    assert [account.account_id for account in result.accounts] == ["user-201"]


def test_run_crawl_search_filters_by_min_followers_and_creator_only():
    pages = {
        "https://www.xiaohongshu.com/user/profile/user-201?xsec_source=pc_search": """
        <section class="profile">
          <div class="user-id">账号ID: user-201</div>
          <h1 class="user-name">A</h1>
          <div class="user-bio">抗痘护肤博主</div>
          <div class="user-tags"><span>护肤博主</span></div>
          <div class="user-followers">粉丝 1.2万</div>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-202?xsec_source=pc_search": """
        <section class="profile">
          <div class="user-id">账号ID: user-202</div>
          <h1 class="user-name">B工作室</h1>
          <div class="user-bio">抗痘护肤工作室</div>
          <div class="user-tags"><span>工作室</span></div>
          <div class="user-followers">粉丝 5.8万</div>
        </section>
        """,
    }
    search_pages = {
        "抗痘博主": [
            """
            <div class="note-item">
              <div class="footer">
                <div class="card-bottom-wrapper">
                  <a class="author" href="/user/profile/user-201?xsec_source=pc_search">A</a>
                  <a class="author" href="/user/profile/user-202?xsec_source=pc_search">B</a>
                </div>
              </div>
            </div>
            """
        ]
    }
    client = FakeClient(pages=pages, search_pages=search_pages)
    config = SearchCrawlConfig(
        search_term="抗痘博主",
        storage_state="state.json",
        output_dir="out",
        max_accounts=5,
        min_followers=10000,
        creator_only=True,
        min_relevance_score=0.7,
    )

    result = run_crawl_search_with_client(config, client)

    assert [account.account_id for account in result.accounts] == ["user-201"]
