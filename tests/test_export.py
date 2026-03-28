import csv
import json

from red_crawler.export.csv_writer import export_run
from red_crawler.models import AccountRecord, ContactLead, CrawlResult, RunReport


def test_export_run_writes_csv_and_report(tmp_path):
    account = AccountRecord(
        account_id="user-001",
        profile_url="https://www.xiaohongshu.com/user/profile/user-001",
        nickname="Mia穿搭手记",
        bio_text="商务合作 vx：Mia_Studio88",
        visible_metadata={"location": "上海", "followers": "12.8万"},
        source_type="seed",
        source_from=None,
        crawl_status="success",
        crawl_error=None,
    )
    lead = ContactLead(
        account_id="user-001",
        lead_type="wechat",
        normalized_value="mia_studio88",
        raw_snippet="vx：Mia_Studio88",
        confidence=0.98,
        extractor_name="wechat_regex",
        source_field="bio",
        dedupe_key="wechat:mia_studio88",
    )
    result = CrawlResult(
        accounts=[account],
        contact_leads=[lead],
        run_report=RunReport(
            seed_url=account.profile_url,
            attempted_accounts=1,
            succeeded_accounts=1,
            failed_accounts=0,
            lead_counts={"wechat": 1},
            errors=[],
        ),
    )

    export_run(result, tmp_path)

    with (tmp_path / "accounts.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    with (tmp_path / "contact_leads.csv").open(newline="", encoding="utf-8") as fh:
        lead_rows = list(csv.DictReader(fh))
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))

    assert rows == [
        {
            "account_id": "user-001",
            "profile_url": "https://www.xiaohongshu.com/user/profile/user-001",
            "nickname": "Mia穿搭手记",
            "bio_text": "商务合作 vx：Mia_Studio88",
            "visible_metadata": '{"followers": "12.8万", "location": "上海"}',
            "source_type": "seed",
            "source_from": "",
            "crawl_status": "success",
            "crawl_error": "",
        }
    ]
    assert lead_rows[0]["normalized_value"] == "mia_studio88"
    assert report["lead_counts"] == {"wechat": 1}
