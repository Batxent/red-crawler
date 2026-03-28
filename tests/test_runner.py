from red_crawler.runner import CrawlConfig, run_crawl_seed_with_client


class FakeClient:
    def __init__(self, pages, failures=None, note_pages=None, search_pages=None):
        self.pages = pages
        self.failures = failures or set()
        self.note_pages = note_pages or {}
        self.search_pages = search_pages or {}
        self.search_queries = []

    def fetch_profile_html(self, profile_url):
        if profile_url in self.failures:
            raise RuntimeError("profile page unavailable")
        return self.pages[profile_url]

    def fetch_note_recommendation_html(self, profile_url):
        return self.note_pages.get(profile_url, [])

    def fetch_search_result_html(self, query):
        self.search_queries.append(query)
        return self.search_pages.get(query, "")


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
        "美妆博主": """
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
          <div class="user-bio">美妆护肤内容分享</div>
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
        "美妆博主": """
        <div class="note-item">
          <div class="footer">
            <div class="card-bottom-wrapper">
              <a class="author" href="/user/profile/user-002?xsec_source=pc_search">U2</a>
            </div>
          </div>
        </div>
        """,
        "护肤博主": "",
        "彩妆博主": """
        <div class="note-item">
          <div class="footer">
            <div class="card-bottom-wrapper">
              <a class="author" href="/user/profile/user-003?xsec_source=pc_search">U3</a>
            </div>
          </div>
        </div>
        """,
        "化妆博主": "",
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
    assert client.search_queries == ["美妆博主", "护肤博主", "彩妆博主", "化妆博主"]


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
        "美妆博主": """
        <div class="note-item">
          <div class="footer">
            <div class="card-bottom-wrapper">
              <a class="author" href="/user/profile/user-002?xsec_source=pc_search">U2</a>
            </div>
          </div>
        </div>
        """,
        "护肤博主": "",
        "彩妆博主": "",
        "化妆博主": "",
    }
    client = FakeClient(pages=pages, search_pages=search_pages)
    client.search_pages["护肤博主"] = """
    <div class="note-item">
      <div class="footer">
        <div class="card-bottom-wrapper">
          <a class="author" href="/user/profile/user-004?xsec_source=pc_search">U4</a>
        </div>
      </div>
    </div>
    """
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
    assert client.search_queries.count("护肤博主") >= 2
