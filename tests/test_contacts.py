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


def test_extract_contact_leads_keeps_redirected_account_hints():
    bio = "日常在@蕾大哥爱火锅，小号在@LuckyMiaDaily，工作联系见主页"

    leads = extract_contact_leads(account_id="user-007", bio_text=bio)
    hints = [lead for lead in leads if lead.lead_type == "other_hint"]

    assert sorted(lead.normalized_value for lead in hints) == sorted([
        "日常在@蕾大哥爱火锅",
        "小号在@LuckyMiaDaily",
    ])


def test_extract_contact_leads_supports_more_wechat_alias_variants():
    bio = "合作请加卫星号：Lucky_mia88，或者 wx：Lucky_mia88，w x: Lucky_mia88"

    leads = extract_contact_leads(account_id="user-008", bio_text=bio)
    wechats = [lead.normalized_value for lead in leads if lead.lead_type == "wechat"]

    assert wechats == ["lucky_mia88"]


def test_extract_contact_leads_keeps_soft_wechat_hints():
    bio = "加V看置顶，微❤️：置顶自取，合作前先看简介"

    leads = extract_contact_leads(account_id="user-009", bio_text=bio)
    hints = [lead.normalized_value for lead in leads if lead.lead_type == "other_hint"]

    assert "加V看置顶" in hints
    assert "微❤️：置顶自取" in hints
