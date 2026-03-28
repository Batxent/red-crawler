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
