from red_crawler.runner import CrawlConfig, run_crawl_seed_with_client


class FakeClient:
    def __init__(self, pages, failures=None):
        self.pages = pages
        self.failures = failures or set()

    def fetch_profile_html(self, profile_url):
        if profile_url in self.failures:
            raise RuntimeError("profile page unavailable")
        return self.pages[profile_url]

    def fetch_note_recommendation_html(self, profile_url):
        return []


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
