"""test_pre_cache.py — Pre-cache pool: fetch, pop, skip tracking."""
import sys, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, '.')

import config
from bot_context import BotContext, get_ctx, set_ctx
from bot_utils import sync_from_context


def _setup_context():
    ctx = BotContext()
    ctx.vip_users = {5405770555: None}
    ctx.all_users = {5405770555}
    ctx.admin_ids = {5405770555}
    set_ctx(ctx)
    sync_from_context()
    return ctx


def test_pre_cache_empty():
    """Pop from empty pool returns None."""
    from pre_cache import pop_pre_cached
    import asyncio
    result = asyncio.run(pop_pre_cached())
    assert result is None, f"Expected None, got {result}"
    print("  OK: empty pop returns None")


def test_skip_count_tracking():
    """Skip count bookkeeping doesn't crash."""
    from pre_cache import track_pre_served, track_pre_clicked, track_pre_skipped
    import asyncio
    async def _run():
        await track_pre_served(1, "http://test.com/gallery/1")
        await track_pre_clicked(1)
        # Multiple skips should not crash even if gallery not in pool
        await track_pre_skipped(2)
        await track_pre_skipped(3)
        print("  OK: skip tracking (no crash)")
    asyncio.run(_run())


def test_is_recent():
    """Date-based recency check."""
    from pre_cache import _is_recent
    from datetime import datetime, timezone, timedelta

    # Today should be recent
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert _is_recent({"publish_date": today}) is True
    # Chinese format
    assert _is_recent({"publish_date": "2026年07月08日"}) is True
    # Empty string
    assert _is_recent({"publish_date": ""}) is False
    # No publish_date
    assert _is_recent({}) is False
    print("  OK: _is_recent date validation")


if __name__ == "__main__":
    print("\nPre-cache Tests:")
    test_pre_cache_empty()
    test_skip_count_tracking()
    test_is_recent()
    print("  PASSED\n")
