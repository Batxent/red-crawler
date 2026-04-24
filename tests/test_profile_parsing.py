from pathlib import Path

import pytest

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


def test_parse_profile_html_rejects_shell_error_page():
    html = """
    <html>
      <body>
        <div>未连接到服务器，刷新一下试试</div>
        <button>点击刷新</button>
      </body>
    </html>
    """

    with pytest.raises(ValueError, match="profile page did not load"):
        parse_profile_html(
            html=html,
            profile_url="https://www.xiaohongshu.com/user/profile/LL16141319",
            source_type="seed",
            source_from=None,
        )


def test_parse_profile_html_extracts_real_xiaohongshu_profile_markup():
    html = """
    <div class="info-part">
      <div class="info">
        <div class="basic-info">
          <div class="user-basic">
            <div class="user-nickname">
              <div class="user-name">LL</div>
            </div>
            <div class="user-content">
              <span class="user-redId">小红书号：LL16141319</span>
              <span class="user-IP">IP属地：北京</span>
            </div>
          </div>
        </div>
        <div class="user-desc">来了就是姐妹👭
痘龄12年（一直在长痘抗痘路上！）
日常在@蕾大哥爱火锅
2635381804@qq.com</div>
        <div class="user-tags">
          <div class="tag-item"><div>北京朝阳</div></div>
          <div class="tag-item"><div>美妆博主</div></div>
        </div>
        <div class="data-info">
          <div class="user-interactions">
            <div><span class="count">212</span><span class="shows">关注</span></div>
            <div><span class="count">35.1万</span><span class="shows">粉丝</span></div>
            <div><span class="count">276.5万</span><span class="shows">获赞与收藏</span></div>
          </div>
        </div>
      </div>
    </div>
    """

    profile = parse_profile_html(
        html=html,
        profile_url="https://www.xiaohongshu.com/user/profile/5e605c910000000001008ecd",
        source_type="seed",
        source_from=None,
    )

    assert profile.nickname == "LL"
    assert profile.bio_text == (
        "来了就是姐妹👭 痘龄12年（一直在长痘抗痘路上！） 日常在@蕾大哥爱火锅 2635381804@qq.com"
    )
    assert profile.visible_metadata == {
        "red_id": "LL16141319",
        "ip_location": "北京",
        "tags": ["北京朝阳", "美妆博主"],
        "following": "212",
        "followers": "35.1万",
        "likes_and_collects": "276.5万",
    }


def test_parse_profile_html_uses_user_id_when_profile_url_contains_note_id():
    html = """
    <section class="profile">
      <h1 class="user-name">Mia</h1>
      <div class="user-bio">护肤博主</div>
    </section>
    """

    profile = parse_profile_html(
        html=html,
        profile_url=(
            "https://www.xiaohongshu.com/user/profile/"
            "user-001/63184102000000001103a3e7?xsec_token=abc&xsec_source=pc_user"
        ),
        source_type="seed",
        source_from=None,
    )

    assert profile.account_id == "user-001"
