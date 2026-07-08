"""test_bot_context.py — Context creation, sync, and state isolation."""
import sys, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, '.')

from bot_context import BotContext, get_ctx, set_ctx
from bot_utils import sync_from_context
import bot_utils


def test_context_creation():
    ctx = BotContext()
    assert ctx.vip_users == {}
    assert ctx.all_users == set()
    assert ctx.invites == {}
    assert ctx.url_counter == 0
    assert ctx.download_sem is not None


def test_context_sync_to_bot_utils():
    ctx = BotContext()
    ctx.vip_users = {111: None, 222: 9999999999.0}
    ctx.all_users = {111, 222, 333}
    ctx.invites = {"ABC123": "111"}
    ctx.admin_ids = {111}
    set_ctx(ctx)
    sync_from_context()

    assert bot_utils.VIP_USERS == {111: None, 222: 9999999999.0}
    assert bot_utils.ALL_USERS == {111, 222, 333}
    assert bot_utils.INVITES == {"ABC123": "111"}


def test_context_isolation():
    """Two contexts should not interfere."""
    ctx1 = BotContext()
    ctx1.vip_users = {1: None}
    ctx2 = BotContext()
    ctx2.vip_users = {2: 9999999999.0}

    assert ctx1.vip_users == {1: None}
    assert ctx2.vip_users == {2: 9999999999.0}
    assert ctx1.vip_users != ctx2.vip_users


if __name__ == "__main__":
    test_context_creation()
    test_context_sync_to_bot_utils()
    test_context_isolation()
    print("OK: bot_context tests passed")
