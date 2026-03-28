from red_crawler.runner import CrawlConfig, run_crawl_seed_with_client


class FakeClient:
    def __init__(self, pages, failures=None, note_pages=None):
        self.pages = pages
        self.failures = failures or set()
        self.note_pages = note_pages or {}

    def fetch_profile_html(self, profile_url):
        if profile_url in self.failures:
            raise RuntimeError("profile page unavailable")
        return self.pages[profile_url]

    def fetch_note_recommendation_html(self, profile_url):
        return self.note_pages.get(profile_url, [])


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


def test_run_crawl_seed_expands_candidates_from_note_comment_authors():
    pages = {
        "https://www.xiaohongshu.com/user/profile/user-001": """
        <section class="profile">
          <div class="user-id">账号ID: user-001</div>
          <h1 class="user-name">Seed</h1>
          <div class="user-bio">商务合作 vx: seed_studio</div>
        </section>
        """,
        "https://www.xiaohongshu.com/user/profile/user-002?xsec_source=pc_comment": """
        <section class="profile">
          <div class="user-id">账号ID: user-002</div>
          <h1 class="user-name">U2</h1>
          <div class="user-bio">邮箱：u2@example.com</div>
        </section>
        """,
    }
    note_pages = {
        "https://www.xiaohongshu.com/user/profile/user-001": [
            """
            <div class="comment-inner-container">
              <div class="author-wrapper">
                <a class="name" href="/user/profile/user-001?xsec_source=pc_comment">Seed</a>
              </div>
            </div>
            <div class="comment-inner-container">
              <div class="author-wrapper">
                <a class="name" href="/user/profile/user-002?xsec_source=pc_comment">U2</a>
              </div>
            </div>
            """
        ]
    }
    client = FakeClient(pages=pages, note_pages=note_pages)
    config = CrawlConfig(
        seed_url="https://www.xiaohongshu.com/user/profile/user-001",
        storage_state="state.json",
        output_dir="out",
        max_accounts=5,
        max_depth=1,
        include_note_recommendations=True,
    )

    result = run_crawl_seed_with_client(config, client)

    assert [account.account_id for account in result.accounts] == ["user-001", "user-002"]
    assert result.run_report.succeeded_accounts == 2
    assert result.run_report.lead_counts == {"email": 1, "wechat": 1}
