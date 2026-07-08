"""test_card_system.py — Card activation, anti-replay, generation, export."""
import sys, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, '.')

import asyncio, secrets, string
from bot_context import BotContext, get_ctx, set_ctx
from bot_utils import sync_from_context


DB_PATH = '/tmp/test_card_system_tests.db'


def _setup_context():
    ctx = BotContext()
    ctx.vip_users = {5405770555: None}
    ctx.all_users = {5405770555, 123456}
    ctx.invites = {}
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
    except: pass
    from database import start_database
    await start_database()


async def test_all():
    """Run all card system tests in a single event loop."""
    await _setup_db()

    # ── Test 1: Activate + anti-replay ──
    from database import db_save_card, db_activate_card, db_load_cards
    from database import db_card_count_used, db_card_count_total

    code = "Y-" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    await db_save_card(code, "month", 30, 5405770555)

    cards = await db_load_cards()
    assert code in cards
    assert not cards[code]["used"]
    assert cards[code]["type"] == "month"

    user_id = 123456
    await db_activate_card(code, user_id)
    cards = await db_load_cards()
    assert cards[code]["used"]
    assert cards[code]["used_by"] == user_id
    assert await db_card_count_used() == 1
    assert await db_card_count_total() == 1

    # Anti-replay
    await db_activate_card(code, 99999)
    cards = await db_load_cards()
    assert cards[code]["used_by"] == user_id
    assert await db_card_count_used() == 1
    print("  OK: activate + anti-replay")

    # ── Test 2: Seed cards ──
    from seed_cards import SEED_CARDS
    for c, info in list(SEED_CARDS.items())[:10]:
        await db_save_card(c, info["type"], info["days"], 5405770555)
    assert await db_card_count_total() == 11  # 1 from test 1 + 10
    print("  OK: seed 10 cards")

    # ── Test 3: Card types ──
    prefix_map = {"month": "Y", "quarter": "J", "year": "N", "forever": "S"}
    days_map = {"month": 30, "quarter": 90, "year": 360, "forever": 0}
    for tname, days in days_map.items():
        c = prefix_map[tname] + "-" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        await db_save_card(c, tname, days if days > 0 else None, 5405770555)
    types = {info["type"] for info in (await db_load_cards()).values()}
    assert types >= {"month", "quarter", "year", "forever"}
    print("  OK: 4 card types")

    # ── Test 4: Unused cards list ──
    from database import db_list_unused_cards
    c1 = "Y-" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    c2 = "J-" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    c3 = "N-" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    await db_save_card(c1, "month", 30, 5405770555)
    await db_save_card(c2, "quarter", 90, 5405770555)
    await db_save_card(c3, "year", 360, 5405770555)
    await db_activate_card(c2, 12345)
    unused = await db_list_unused_cards()
    unused_codes = {r["code"] for r in unused}
    assert c1 in unused_codes
    assert c2 not in unused_codes
    assert c3 in unused_codes
    print(f"  OK: {len(unused)} cards unused")

    print("  PASSED\n")


if __name__ == "__main__":
    print("\nCard System Tests:")
    asyncio.run(test_all())
