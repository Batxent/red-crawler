from red_crawler.extract.contacts import extract_contact_leads


def test_extract_contact_leads_returns_structured_deduped_results():
    bio = (
        "商务合作请联系vx：Mia_Studio88，邮箱：MIA@EXAMPLE.COM，"
        "手机号 13800138000，助理请备注品牌名。经纪人阿青也可对接，"
        "vx: Mia_Studio88"
    )

    leads = extract_contact_leads(account_id="user-001", bio_text=bio)
    by_type = {lead.lead_type: lead for lead in leads}

    assert len(leads) == 5
    assert by_type["wechat"].normalized_value == "mia_studio88"
    assert by_type["email"].normalized_value == "mia@example.com"
    assert by_type["phone"].normalized_value == "13800138000"
    assert by_type["business_note"].raw_snippet == "助理请备注品牌名"
    assert by_type["manager"].raw_snippet == "经纪人阿青也可对接"
    assert by_type["wechat"].confidence > by_type["business_note"].confidence


def test_extract_contact_leads_marks_unstructured_business_hint():
    bio = "可接商务合作，合作前请先私信确认档期。"

    leads = extract_contact_leads(account_id="user-002", bio_text=bio)

    assert len(leads) == 1
    assert leads[0].lead_type == "other_hint"
    assert leads[0].normalized_value == "可接商务合作"
    assert 0.3 <= leads[0].confidence < 0.6


def test_extract_contact_leads_recovers_obfuscated_qq_email():
    bio = "商务合作请发q邮箱：919581887，也可以发 919581887@🐧.com"

    leads = extract_contact_leads(account_id="user-003", bio_text=bio)
    emails = [lead for lead in leads if lead.lead_type == "email"]

    assert len(emails) == 1
    assert emails[0].normalized_value == "919581887@qq.com"
    assert emails[0].dedupe_key == "email:919581887@qq.com"


def test_extract_contact_leads_recovers_circled_digit_penguin_email():
    bio = "生活碎片大放送！@iiikio 9⃝5⃝1⃝4⃝1⃝9⃝6⃝5⃝0⃝ 🐧.📧"

    leads = extract_contact_leads(account_id="user-013", bio_text=bio)
    emails = [lead for lead in leads if lead.lead_type == "email"]

    assert len(emails) == 1
    assert emails[0].normalized_value == "951419650@qq.com"
    assert emails[0].raw_snippet == "951419650@qq.com"


def test_extract_contact_leads_recovers_decorated_email_suffix():
    bio = "🎀 𝒷𝒻𝓌𝒾𝓃𝒹𝟫𝟫@𝟣𝟤𝟨.𝒸💗𝓂"

    leads = extract_contact_leads(account_id="user-014", bio_text=bio)
    emails = [lead for lead in leads if lead.lead_type == "email"]

    assert len(emails) == 1
    assert emails[0].normalized_value == "bfwind99@126.com"
    assert emails[0].raw_snippet == "bfwind99@126.com"


def test_extract_contact_leads_recovers_heavily_decorated_qq_email():
    bio = "💕 𝟝𝟞𝟜𝟙𝟚⓪⑤①⑧ 🌀 🐧🐧·c̆̈🔘m̆̈"

    leads = extract_contact_leads(account_id="user-016", bio_text=bio)
    emails = [lead for lead in leads if lead.lead_type == "email"]

    assert len(emails) == 1
    assert emails[0].normalized_value == "564120518@qq.com"
    assert emails[0].raw_snippet == "564120518@qq.com"


def test_extract_contact_leads_recovers_homoglyph_domain_email():
    bio = "yay@sһᥙgᥱ.ᥴᥒ"

    leads = extract_contact_leads(account_id="user-017", bio_text=bio)
    emails = [lead for lead in leads if lead.lead_type == "email"]

    assert len(emails) == 1
    assert emails[0].normalized_value == "yay@shuge.cn"
    assert emails[0].raw_snippet == "yay@shuge.cn"


def test_extract_contact_leads_backfills_username_from_provider_domain():
    bio = "我是生活的主人🐰 𝘩𝘦𝘯𝘨𝘢𝘰𝘹𝘪𝘯𝘨𝟶𝟸𝟶𝟺🌀𝘧𝘰𝘹𝘮𝘢𝘪𝘭.𝘤𝘰𝘮"

    leads = extract_contact_leads(account_id="user-025", bio_text=bio)
    emails = [lead for lead in leads if lead.lead_type == "email"]

    assert len(emails) == 1
    assert emails[0].normalized_value == "hengaoxing0204@foxmail.com"
    assert emails[0].raw_snippet == "hengaoxing0204foxmail.com"
    assert [lead for lead in leads if lead.lead_type == "wechat"] == []


def test_extract_contact_leads_backfills_spaced_provider_domain_email():
    bio = "画点自己喜欢的妆🎨 kosokuya🌀 𝟙𝟚𝟞.com"

    leads = extract_contact_leads(account_id="user-026", bio_text=bio)
    emails = [lead for lead in leads if lead.lead_type == "email"]

    assert len(emails) == 1
    assert emails[0].normalized_value == "kosokuya@126.com"


def test_extract_contact_leads_normalizes_broad_ascii_homoglyph_email():
    bio = "аƅсԁеғɡһіјκⅼмոорԛгѕтυνԝхуᴢ@ехаmрⅼе.сո"

    leads = extract_contact_leads(account_id="user-018", bio_text=bio)
    emails = [lead for lead in leads if lead.lead_type == "email"]

    assert len(emails) == 1
    assert emails[0].normalized_value == "abcdefghijklmnopqrstuvwxyz@example.cn"
    assert emails[0].raw_snippet == "abcdefghijklmnopqrstuvwxyz@example.cn"


def test_extract_contact_leads_supports_wechat_aliases_and_qq_number():
    bio = "商务V: Lucky_mia88，薇：Lucky_mia88，扣扣：919581887"

    leads = extract_contact_leads(account_id="user-004", bio_text=bio)
    by_type = {lead.lead_type: lead for lead in leads}

    assert by_type["wechat"].normalized_value == "lucky_mia88"
    assert by_type["qq"].normalized_value == "919581887"
    assert by_type["qq"].confidence >= 0.7


def test_extract_contact_leads_supports_single_letter_v_alias():
    bio = "合作请加V: Lucky_mia88"

    leads = extract_contact_leads(account_id="user-005", bio_text=bio)
    by_type = {lead.lead_type: lead for lead in leads}

    assert by_type["wechat"].normalized_value == "lucky_mia88"


def test_extract_contact_leads_recovers_spelled_out_email_domains():
    bio = (
        "工作邮箱：mia艾特gmail点com，备用邮箱：brand_hezuo@163点com，"
        "也可联系：team艾特outlook点com"
    )

    leads = extract_contact_leads(account_id="user-006", bio_text=bio)
    emails = [lead.normalized_value for lead in leads if lead.lead_type == "email"]

    assert "mia@gmail.com" in emails
    assert "brand_hezuo@163.com" in emails
    assert "team@outlook.com" in emails


def test_extract_contact_leads_does_not_mark_email_remark_as_business_note():
    bio = "大家理性种草哦 合作邮箱：1449788295@qq.com（合作请备注）"

    leads = extract_contact_leads(account_id="user-024", bio_text=bio)

    assert [(lead.lead_type, lead.normalized_value) for lead in leads] == [
        ("email", "1449788295@qq.com")
    ]


def test_extract_contact_leads_normalizes_stylized_unicode_email():
    bio = "江西米粉大王的日常 🤍𝐥𝐢𝐭𝐭𝐥𝐞𝐧𝐢𝐧𝐢𝐮@𝐆𝐦𝐚𝐢𝐥.𝐜𝐨𝐦"

    leads = extract_contact_leads(account_id="user-011", bio_text=bio)
    emails = [lead for lead in leads if lead.lead_type == "email"]

    assert len(emails) == 1
    assert emails[0].normalized_value == "littleniniu@gmail.com"
    assert emails[0].raw_snippet == "littleniniu@Gmail.com"


def test_extract_contact_leads_keeps_redirected_account_hints():
    bio = "日常在@蕾大哥爱火锅，小号在@LuckyMiaDaily，工作联系见主页"

    leads = extract_contact_leads(account_id="user-007", bio_text=bio)
    hints = [lead for lead in leads if lead.lead_type == "other_hint"]

    assert sorted(lead.normalized_value for lead in hints) == sorted([
        "日常在@蕾大哥爱火锅",
        "小号在@LuckyMiaDaily",
    ])


def test_extract_contact_leads_extracts_redirect_hint_without_leading_bio_noise():
    bio = "来了就是姐妹👭 痘龄12年 日常在@蕾大哥爱火锅 2635381804@qq.com"

    leads = extract_contact_leads(account_id="user-010", bio_text=bio)
    hints = [lead.normalized_value for lead in leads if lead.lead_type == "other_hint"]

    assert hints == ["日常在@蕾大哥爱火锅"]


def test_extract_contact_leads_supports_more_wechat_alias_variants():
    bio = "合作请加卫星号：Lucky_mia88，或者 wx：Lucky_mia88，w x: Lucky_mia88"

    leads = extract_contact_leads(account_id="user-008", bio_text=bio)
    wechats = [lead.normalized_value for lead in leads if lead.lead_type == "wechat"]

    assert wechats == ["lucky_mia88"]


def test_extract_contact_leads_recovers_remark_contact_id():
    bio = "爱出者爱返 福往者福来 Vlog @麦辣qq (不熟) UUMM1788 (备注📝)"

    leads = extract_contact_leads(account_id="user-012", bio_text=bio)
    by_type = {lead.lead_type: lead for lead in leads}

    assert by_type["wechat"].normalized_value == "uumm1788"
    assert by_type["wechat"].raw_snippet == "UUMM1788 (备注📝)"
    assert by_type["wechat"].confidence < 0.9


def test_extract_contact_leads_recovers_business_emoji_contact_id():
    bio = "🈴keikanata"

    leads = extract_contact_leads(account_id="user-015", bio_text=bio)
    by_type = {lead.lead_type: lead for lead in leads}

    assert by_type["wechat"].normalized_value == "keikanata"
    assert by_type["wechat"].raw_snippet == "🈴keikanata"
    assert by_type["wechat"].confidence < 0.9


def test_extract_contact_leads_recovers_contact_emoji_id():
    bio = "⋆˚𝜗𝜚˚⋆ 💌𝐩𝐮𝐫𝐫𝐩1𝐞𝐫𝐚𝐢𝐧"

    leads = extract_contact_leads(account_id="user-019", bio_text=bio)
    by_type = {lead.lead_type: lead for lead in leads}

    assert by_type["wechat"].normalized_value == "purrp1erain"
    assert by_type["wechat"].raw_snippet == "💌purrp1erain"
    assert by_type["wechat"].confidence < 0.9


def test_extract_contact_leads_recovers_annotated_self_contact_id():
    bio = "🎮banana980421（本人）"

    leads = extract_contact_leads(account_id="user-020", bio_text=bio)
    by_type = {lead.lead_type: lead for lead in leads}

    assert by_type["wechat"].normalized_value == "banana980421"
    assert by_type["wechat"].raw_snippet == "banana980421(本人)"
    assert by_type["wechat"].confidence < 0.9


def test_extract_contact_leads_recovers_directional_contact_id():
    bio = (
        "🔸抽象概念线条纹身风格 🔹禁止盗图禁止商用禁止自拿 "
        "✨ TLIANGGGG ⬅️ 纹身作品：@十雨TATTOO-亮亮 摄影作品：@二号玩家"
    )

    leads = extract_contact_leads(account_id="user-021", bio_text=bio)
    by_type = {lead.lead_type: lead for lead in leads}

    assert by_type["wechat"].normalized_value == "tliangggg"
    assert by_type["wechat"].raw_snippet == "✨ TLIANGGGG ⬅"
    assert by_type["wechat"].confidence < 0.9


def test_extract_contact_leads_recovers_generic_ascii_contact_id():
    leads = extract_contact_leads(account_id="user-022", bio_text="日常碎片 tliangggg")
    by_type = {lead.lead_type: lead for lead in leads}

    assert by_type["wechat"].normalized_value == "tliangggg"
    assert by_type["wechat"].raw_snippet == "tliangggg"
    assert by_type["wechat"].confidence < 0.7


def test_extract_contact_leads_does_not_extract_embedded_mention_ascii_word():
    bio = "纹身作品：@十雨TATTOO-亮亮 摄影作品：@二号玩家"

    leads = extract_contact_leads(account_id="user-023", bio_text=bio)

    assert [lead for lead in leads if lead.lead_type == "wechat"] == []


def test_extract_contact_leads_keeps_soft_wechat_hints():
    bio = "加V看置顶，微❤️：置顶自取，合作前先看简介"

    leads = extract_contact_leads(account_id="user-009", bio_text=bio)
    hints = [lead.normalized_value for lead in leads if lead.lead_type == "other_hint"]

    assert "加V看置顶" in hints
    assert "微❤️：置顶自取" in hints
