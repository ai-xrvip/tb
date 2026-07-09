"""test_favorites.py — Favorites DB operations: add, list, delete, clear."""
import sys, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, '.')

import asyncio
from bot_context import BotContext, get_ctx, set_ctx
from bot_utils import sync_from_context

DB_PATH = '/tmp/test_favorites_tests.db'


def _setup_context():
    ctx = BotContext()
    ctx.vip_users = {5405770555: None}
    ctx.all_users = {5405770555, 123456}
    ctx.admin_ids = {5405770555}
    set_ctx(ctx)
    sync_from_context()
    return ctx


async def _setup_db():
    import config
    config.config.DB_PATH = DB_PATH
    try:
        for ext in ['', '-wal', '-shm']:
            os.remove(DB_PATH + ext)
    except Exception:
        pass
    from database import start_database
    await start_database()


async def test_all():
    await _setup_db()
    from database import db_add_favorite, db_get_favorites, db_delete_favorite, db_clear_favorites

    user_id = 123456

    # ── Test 1: Add favorites ──
    added1 = await db_add_favorite(user_id, "Cosplay Set A", "https://4khd.com/gallery/1", "4khd")
    assert added1 is True
    added2 = await db_add_favorite(user_id, "Cosplay Set B", "https://xchina.co/photo/id-abc", "xchina")
    assert added2 is True
    added3 = await db_add_favorite(user_id, "Cosplay Set C", "https://e-hentai.org/g/123/abc", "ehentai")
    assert added3 is True
    print("  OK: add 3 favorites")

    # ── Test 2: Duplicate prevention ──
    dup = await db_add_favorite(user_id, "Cosplay Set A", "https://4khd.com/gallery/1", "4khd")
    assert dup is False
    print("  OK: duplicate rejected")

    # ── Test 3: List favorites ──
    favs = await db_get_favorites(user_id)
    assert len(favs) == 3
    assert favs[0]["title"] == "Cosplay Set C"  # most recent first
    print("  OK: list favorites (3 items, newest first)")

    # ── Test 4: Delete single favorite ──
    deleted = await db_delete_favorite(user_id, "https://xchina.co/photo/id-abc")
    assert deleted is True
    favs = await db_get_favorites(user_id)
    assert len(favs) == 2
    assert all(f["url"] != "https://xchina.co/photo/id-abc" for f in favs)
    print("  OK: delete single favorite")

    # ── Test 5: Delete non-existent returns False ──
    deleted = await db_delete_favorite(user_id, "https://does-not-exist.com/x")
    assert deleted is False
    print("  OK: delete non-existent returns False")

    # ── Test 6: Clear all favorites ──
    cleared = await db_clear_favorites(user_id)
    assert cleared == 2
    favs = await db_get_favorites(user_id)
    assert len(favs) == 0
    print("  OK: clear all favorites")

    print("  PASSED\n")


if __name__ == "__main__":
    print("\nFavorites Tests:")
    asyncio.run(test_all())
