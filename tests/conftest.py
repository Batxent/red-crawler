from pathlib import Path

import pytest

import red_crawler.store.database as database_module


@pytest.fixture(autouse=True)
def prevent_tests_from_using_real_crawl_db(monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    protected_db = (repo_root / "data" / "red_crawler.db").resolve()
    original_init = database_module.CrawlerStore.__init__

    def guarded_init(self, db_path):
        resolved_path = Path(db_path)
        if not resolved_path.is_absolute():
            resolved_path = (Path.cwd() / resolved_path).resolve()
        else:
            resolved_path = resolved_path.resolve()
        if resolved_path == protected_db:
            raise AssertionError(
                "tests must use a temporary SQLite database, not data/red_crawler.db"
            )
        original_init(self, db_path)

    monkeypatch.setattr(database_module.CrawlerStore, "__init__", guarded_init)
