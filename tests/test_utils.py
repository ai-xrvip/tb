"""test_utils.py — Utility functions: dedup, quality score, title parsing, date parsing."""
import sys, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, '.')

from bot_context import BotContext, get_ctx, set_ctx
from bot_utils import sync_from_context
from bot_utils import (
    dedup_results, quality_score, clean_title,
    parse_count_from_title, parse_date_for_sort,
)


def _init():
    ctx = BotContext()
    ctx.vip_users = {1: None}
    ctx.all_users = {1}
    ctx.invites = {}
    ctx.admin_ids = {1}
    set_ctx(ctx)
    sync_from_context()


def test_clean_title():
    _init()
    assert clean_title("[30P] Beautiful Cosplay") == "Beautiful Cosplay"
    assert clean_title("Title  [1GB] [50 photos]") == "Title"
    assert clean_title("  Normal · Title  ") == "Normal Title"
    assert clean_title("Test f:photo") == "Test"


def test_parse_count_from_title():
    _init()
    assert parse_count_from_title("[30P] Title") == 30
    assert parse_count_from_title("Beautiful 50 photos collection") == 50
    assert parse_count_from_title("[100张] 精品") == 100
    assert parse_count_from_title("Just a title") == 0


def test_parse_date():
    _init()
    assert parse_date_for_sort("2026年07月08日") == "2026-07-08"
    assert parse_date_for_sort("2026.07.08") == "2026-07-08"
    assert parse_date_for_sort("2026/07/08") == "2026-07-08"
    assert parse_date_for_sort("") == ""
    assert parse_date_for_sort("not a date") == ""


def test_dedup_results():
    _init()
    results = [
        {"title": "Beautiful Cosplay Set", "url": "a", "publish_date": "2026-07-01"},
        {"title": "Beautiful Cosplay Set  [50P]", "url": "b", "publish_date": "2026-07-02"},
        {"title": "Completely Different", "url": "c", "publish_date": "2026-07-03"},
        {"title": "Beautifull Cosplay Sett", "url": "d", "publish_date": "2026-06-01"},
    ]
    deduped = dedup_results(results)
    # Results with similar titles should be reduced
    # "Beautiful Cosplay Set" and "Beautiful Cosplay Set [50P]" are >80% similar
    # "Beautifull Cosplay Sett" is also >80% similar (typos)
    # "Completely Different" is unique
    assert len(deduped) <= 3, f"Expected <= 3 after dedup, got {len(deduped)}"
    # The kept entry should have the better date
    titles = {r["title"] for r in deduped}
    assert "Completely Different" in titles


def test_quality_score():
    _init()
    r = {"title": "Test [30P]", "url": "https://test.com/1", "publish_date": "2026-07-01"}
    score = quality_score(r)
    assert 0 <= score <= 1, f"Score {score} out of range"

    # Unknown date should not crash
    r2 = {"title": "No date", "url": "https://test.com/2", "publish_date": ""}
    score2 = quality_score(r2)
    assert 0 <= score2 <= 1


if __name__ == "__main__":
    print("\nUtility Tests:")
    test_clean_title()
    print("  OK: clean_title")
    test_parse_count_from_title()
    print("  OK: parse_count_from_title")
    test_parse_date()
    print("  OK: parse_date")
    test_dedup_results()
    print("  OK: dedup_results")
    test_quality_score()
    print("  OK: quality_score")
    print("  PASSED\n")
