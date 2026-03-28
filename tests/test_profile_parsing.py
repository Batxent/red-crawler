from pathlib import Path

from red_crawler.crawl.profile import parse_profile_html


def test_parse_profile_html_extracts_core_fields():
    html = Path("tests/fixtures/profile.html").read_text(encoding="utf-8")

    profile = parse_profile_html(
        html=html,
        profile_url="https://www.xiaohongshu.com/user/profile/user-001",
        source_type="seed",
        source_from=None,
    )

    assert profile.account_id == "user-001"
    assert profile.nickname == "Mia穿搭手记"
    assert "MIA@EXAMPLE.COM" in profile.bio_text
    assert profile.visible_metadata == {
        "location": "上海",
        "followers": "12.8万",
        "tags": ["通勤穿搭", "微胖女生"],
    }
    assert profile.crawl_status == "success"
