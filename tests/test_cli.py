import csv
import json

from red_crawler.cli import main
from red_crawler.models import AccountRecord, ContactLead, CrawlResult, RunReport


def test_cli_crawl_seed_exports_expected_files(tmp_path, monkeypatch):
    def fake_run_crawl_seed(config):
        assert config.seed_url == "https://www.xiaohongshu.com/user/profile/user-001"
        assert config.max_depth == 2
        assert config.safe_mode is True
        return CrawlResult(
            accounts=[
                AccountRecord(
                    account_id="user-001",
                    profile_url=config.seed_url,
                    nickname="Mia穿搭手记",
                    bio_text="商务合作 vx：Mia_Studio88",
                    visible_metadata={"location": "上海"},
                    source_type="seed",
                    source_from=None,
                    crawl_status="success",
                    crawl_error=None,
                )
            ],
            contact_leads=[
                ContactLead(
                    account_id="user-001",
                    lead_type="wechat",
                    normalized_value="mia_studio88",
                    raw_snippet="vx：Mia_Studio88",
                    confidence=0.98,
                    extractor_name="wechat_regex",
                    source_field="bio",
                    dedupe_key="wechat:mia_studio88",
                )
            ],
            run_report=RunReport(
                seed_url=config.seed_url,
                attempted_accounts=1,
                succeeded_accounts=1,
                failed_accounts=0,
                lead_counts={"wechat": 1},
                errors=[],
            ),
        )

    monkeypatch.setattr("red_crawler.cli.run_crawl_seed", fake_run_crawl_seed)

    exit_code = main(
        [
            "crawl-seed",
            "--seed-url",
            "https://www.xiaohongshu.com/user/profile/user-001",
            "--storage-state",
            "state.json",
            "--safe-mode",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "accounts.csv").exists()
    assert (tmp_path / "contact_leads.csv").exists()
    assert (tmp_path / "run_report.json").exists()

    with (tmp_path / "accounts.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))

    assert rows[0]["nickname"] == "Mia穿搭手记"
    assert report["succeeded_accounts"] == 1


def test_cli_login_saves_storage_state(tmp_path, monkeypatch):
    captured = {}

    def fake_save_login_storage_state(output_path, login_url):
        captured["output_path"] = output_path
        captured["login_url"] = login_url

    monkeypatch.setattr(
        "red_crawler.cli.save_login_storage_state", fake_save_login_storage_state
    )

    exit_code = main(
        [
            "login",
            "--save-state",
            str(tmp_path / "state.json"),
        ]
    )

    assert exit_code == 0
    assert captured == {
        "output_path": tmp_path / "state.json",
        "login_url": "https://www.xiaohongshu.com",
    }


def test_cli_open_uses_existing_storage_state(monkeypatch):
    captured = {}

    def fake_open_xiaohongshu(storage_state, open_url):
        captured["storage_state"] = storage_state
        captured["open_url"] = open_url

    monkeypatch.setattr("red_crawler.cli.open_xiaohongshu", fake_open_xiaohongshu)

    exit_code = main(
        [
            "open",
            "--storage-state",
            "./state.json",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "storage_state": "./state.json",
        "open_url": "https://www.xiaohongshu.com",
    }
