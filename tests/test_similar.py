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


def test_extract_search_result_profiles_extracts_authors_from_search_cards():
    html = """
    <html>
      <body>
        <div class="note-item">
          <div class="footer">
            <div class="card-bottom-wrapper">
              <a class="author" href="/user/profile/user-010?xsec_source=pc_search">美妆博主A</a>
            </div>
          </div>
        </div>
        <div class="note-item">
          <div class="footer">
            <div class="card-bottom-wrapper">
              <a class="author" href="/user/profile/user-011?xsec_source=pc_search">美妆博主B</a>
            </div>
          </div>
        </div>
      </body>
    </html>
    """

    from red_crawler.crawl.similar import extract_search_result_profiles

    profiles = extract_search_result_profiles(
        html=html,
        max_results=5,
    )

    assert profiles == [
        {
            "account_id": "user-010",
            "profile_url": "https://www.xiaohongshu.com/user/profile/user-010?xsec_source=pc_search",
            "nickname": "美妆博主A",
        },
        {
            "account_id": "user-011",
            "profile_url": "https://www.xiaohongshu.com/user/profile/user-011?xsec_source=pc_search",
            "nickname": "美妆博主B",
        },
    ]


def test_is_relevant_creator_candidate_accepts_same_domain_synonyms():
    from red_crawler.crawl.similar import build_search_queries, is_relevant_creator_candidate

    seed_account = {
        "bio_text": "北京美妆内容分享",
        "visible_metadata": {"tags": ["北京朝阳", "美妆博主"], "ip_location": "北京"},
    }
    candidate_account = {
        "bio_text": "成分党护肤干货分享",
        "visible_metadata": {
            "tags": ["时尚博主", "护肤博主"],
            "followers": "5.2万",
            "ip_location": "福建",
        },
    }

    assert build_search_queries(seed_account) == ["美妆博主"]
    assert is_relevant_creator_candidate(seed_account, candidate_account) is True
