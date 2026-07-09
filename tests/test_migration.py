"""test_migration.py — JSON-to-SQLite migration: roundtrip from example data."""
import sys, os, json, tempfile
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, '.')

import asyncio
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


async def _setup_db():
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test_migration.db")
    config.config.DB_PATH = db_path
    from database import start_database
    await start_database()
    return tmpdir


async def test_migration_vip_users():
    """Migrate vip_users.json and verify data lands in SQLite."""
    tmpdir = await _setup_db()

    # Write example JSON
    vip_path = os.path.join(tmpdir, "vip_users.json")
    with open(vip_path, "w") as f:
        json.dump({"111111": None, "222222": 1800000000.0}, f)

    from database import db_migrate_from_json, db_load_vip, db_vip_count
    stats = await db_migrate_from_json(tmpdir)
    assert stats["vip"] == 2, f"Expected 2 VIPs, got {stats['vip']}"
    assert os.path.exists(vip_path + ".migrated"), "File should be renamed to .migrated"

    vips = await db_load_vip()
    assert 111111 in vips
    assert vips[111111] is None  # permanent
    assert vips[222222] == 1800000000.0
    assert await db_vip_count() == 2
    print("  OK: migrate vip_users.json")


async def test_migration_users():
    """Migrate users.json."""
    tmpdir = await _setup_db()
    users_path = os.path.join(tmpdir, "users.json")
    with open(users_path, "w") as f:
        json.dump([111, 222, 333], f)

    from database import db_migrate_from_json, db_load_users, db_user_count
    stats = await db_migrate_from_json(tmpdir)
    assert stats["users"] == 3
    users = await db_load_users()
    assert 111 in users and 333 in users
    assert await db_user_count() == 3
    print("  OK: migrate users.json")


async def test_migration_invites():
    """Migrate invites.json."""
    tmpdir = await _setup_db()
    inv_path = os.path.join(tmpdir, "invites.json")
    with open(inv_path, "w") as f:
        json.dump({"abc123": "111111", "xyz789": "222222"}, f)

    from database import db_migrate_from_json, db_load_invites, db_invite_count
    stats = await db_migrate_from_json(tmpdir)
    assert stats["invites"] == 2
    invites = await db_load_invites()
    assert invites["abc123"] == "111111"
    assert await db_invite_count() == 2
    print("  OK: migrate invites.json")


async def test_migration_idempotent():
    """Second migration call should not duplicate data."""
    tmpdir = await _setup_db()
    vip_path = os.path.join(tmpdir, "vip_users.json")
    with open(vip_path, "w") as f:
        json.dump({"111111": None}, f)

    from database import db_migrate_from_json, db_vip_count
    stats1 = await db_migrate_from_json(tmpdir)
    assert stats1["vip"] == 1

    # File is now .migrated, second call should skip
    stats2 = await db_migrate_from_json(tmpdir)
    assert stats2["vip"] == 0
    assert await db_vip_count() == 1
    print("  OK: migration idempotent (skips .migrated files)")


if __name__ == "__main__":
    print("\nMigration Tests:")
    asyncio.run(test_migration_vip_users())
    asyncio.run(test_migration_users())
    asyncio.run(test_migration_invites())
    asyncio.run(test_migration_idempotent())
    print("  PASSED\n")
