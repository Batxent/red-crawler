from red_crawler.session import extract_note_detail_urls


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
