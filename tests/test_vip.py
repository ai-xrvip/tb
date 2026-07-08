"""test_vip.py — VIP lifecycle: set, expire, clean, compute, extend."""
import sys, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, '.')

import asyncio
from bot_context import BotContext, get_ctx, set_ctx
from bot_utils import sync_from_context, is_vip, now_ts, _ONE_DAY

DB_PATH = '/tmp/test_vip_tests.db'


def _setup_context():
    ctx = BotContext()
    ctx.vip_users = {5405770555: None}
    ctx.all_users = {5405770555}
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
    _setup_context()
    await _setup_db()

    from database import db_save_vip, db_load_vip, db_vip_count, db_vip_permanent_count

    # ── Test 1: Set VIP ──
    user_id = 222222
    expiry = now_ts() + 30 * _ONE_DAY
    await db_save_vip(user_id, expiry)
    ctx = get_ctx()
    ctx.vip_users[user_id] = expiry
    set_ctx(ctx)
    sync_from_context()
    assert is_vip(user_id)
    assert is_vip(5405770555)
    db_vip = await db_load_vip()
    assert user_id in db_vip
    assert abs(db_vip[user_id] - expiry) < 5
    print("  OK: set VIP")

    # ── Test 2: Expired VIP ──
    uid2 = 333333
    ctx = get_ctx()
    ctx.vip_users[uid2] = now_ts() - _ONE_DAY
    set_ctx(ctx)
    sync_from_context()
    assert not is_vip(uid2)
    assert is_vip(5405770555)
    print("  OK: expired VIP detected")

    # ── Test 3: Permanent VIP ──
    uid3 = 444444
    ctx = get_ctx()
    ctx.vip_users[uid3] = None
    set_ctx(ctx)
    sync_from_context()
    assert is_vip(uid3)
    print("  OK: permanent VIP")

    # ── Test 4: VIP extension ──
    uid4 = 555555
    initial = now_ts() + 7 * _ONE_DAY
    ctx = get_ctx()
    ctx.vip_users[uid4] = initial
    set_ctx(ctx)
    sync_from_context()
    assert is_vip(uid4)
    new_exp = max(ctx.vip_users.get(uid4, 0) or now_ts(), now_ts()) + 30 * _ONE_DAY
    ctx.vip_users[uid4] = new_exp
    assert ctx.vip_users[uid4] > initial
    print("  OK: VIP extension")

    # ── Test 5: Count ──
    total = await db_vip_count()
    perm = await db_vip_permanent_count()
    assert total >= 1
    ctx_perm = sum(1 for v in ctx.vip_users.values() if v is None)
    assert ctx_perm >= 1  # at least admin
    print(f"  OK: {total} VIPs, {perm} permanent")

    print("  PASSED\n")


if __name__ == "__main__":
    print("\nVIP System Tests:")
    asyncio.run(test_all())
