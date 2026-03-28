from __future__ import annotations

import csv
import json
from pathlib import Path

from red_crawler.models import CrawlResult


def export_run(result: CrawlResult, output_dir: str | Path) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with (output_path / "accounts.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "account_id",
                "profile_url",
                "nickname",
                "bio_text",
                "visible_metadata",
                "creator_segment",
                "relevance_score",
                "source_type",
                "source_from",
                "crawl_status",
                "crawl_error",
            ],
        )
        writer.writeheader()
        writer.writerows(account.to_row() for account in result.accounts)

    with (output_path / "contact_leads.csv").open(
        "w", newline="", encoding="utf-8"
    ) as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "account_id",
                "lead_type",
                "normalized_value",
                "raw_snippet",
                "confidence",
                "extractor_name",
                "source_field",
                "dedupe_key",
            ],
        )
        writer.writeheader()
        writer.writerows(lead.to_row() for lead in result.contact_leads)

    (output_path / "run_report.json").write_text(
        json.dumps(result.run_report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
