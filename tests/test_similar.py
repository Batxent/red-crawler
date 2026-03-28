from pathlib import Path

from red_crawler.crawl.similar import extract_similar_profiles, expand_recommendation_graph


def test_extract_similar_profiles_dedupes_and_limits_results():
    html = Path("tests/fixtures/profile.html").read_text(encoding="utf-8")

    profiles = extract_similar_profiles(
        html=html,
        base_profile_url="https://www.xiaohongshu.com/user/profile/user-001",
        max_results=2,
    )

    assert profiles == [
        {
            "account_id": "user-002",
            "profile_url": "https://www.xiaohongshu.com/user/profile/user-002",
            "nickname": "Luna穿搭志",
        },
        {
            "account_id": "user-003",
            "profile_url": "https://www.xiaohongshu.com/user/profile/user-003",
            "nickname": "Aki日常搭配",
        },
    ]


def test_expand_recommendation_graph_obeys_depth_and_account_limit():
    graph = {
        "seed": ["u2", "u3"],
        "u2": ["u4", "u5"],
        "u3": ["u6"],
        "u4": ["u7"],
    }

    expanded = expand_recommendation_graph(
        seed_account_id="seed",
        graph=graph,
        max_accounts=4,
        max_depth=1,
    )

    assert expanded == ["seed", "u2", "u3"]


def test_extract_similar_profiles_ignores_non_recommendation_profile_links():
    html = """
    <html>
      <body>
        <nav>
          <a href="/user/profile/616b9a13000000000201b634">tomi</a>
        </nav>
      </body>
    </html>
    """

    profiles = extract_similar_profiles(
        html=html,
        base_profile_url="https://www.xiaohongshu.com/user/profile/LL16141319",
        max_results=5,
    )

    assert profiles == []
