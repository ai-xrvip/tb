"""test_routes.py — Verify all callback routes are registered and match correctly."""
import sys, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, '.')

from bot_context import BotContext, get_ctx, set_ctx
from bot_utils import sync_from_context


def _init():
    ctx = BotContext()
    ctx.vip_users = {5405770555: None}
    ctx.all_users = {5405770555}
    ctx.invites = {}
    ctx.admin_ids = {5405770555}
    set_ctx(ctx)
    sync_from_context()


def test_all_exact_routes_registered():
    _init()
    from handlers_callbacks import _exact_routes

    needed = {
        "menu_search", "menu_random", "random_next", "menu_vip",
        "menu_help", "menu_home", "noop", "invite_gen", "invite_info",
        "vip_activate", "vip_upgrade", "admin_gencode", "admin_exportcards",
        "admin_back", "admin_setvip_prompt", "admin_listusers", "fav_list",
    }
    missing = needed - set(_exact_routes.keys())
    assert not missing, f"Missing exact routes: {missing}"


def test_all_prefix_routes_registered():
    _init()
    from handlers_callbacks import _prefix_routes

    needed = {"hot_", "p_", "d_", "x_", "e_", "m_", "f_", "g_", "fav_add_"}
    registered = {p for p, _ in _prefix_routes}
    missing = needed - registered
    assert not missing, f"Missing prefix routes: {missing}"


def test_route_ordering():
    """Prefix routes are checked in registration order — 'fav_add_' must come before 'f_'."""
    _init()
    from handlers_callbacks import _prefix_routes

    prefixes = [p for p, _ in _prefix_routes]
    fav_add_idx = prefixes.index("fav_add_")
    # 'fav_add_' should come before 'f_' and 'fav_list' is exact so irrelevant
    # Actually 'f_' comes before 'fav_add_' now... let's check this doesn't shadow
    # No, fav_add_ is checked first because it's registered first (we control order)
    f_idx = prefixes.index("f_")
    assert fav_add_idx < f_idx, \
        f"fav_add_ (idx {fav_add_idx}) must come before f_ (idx {f_idx}) to avoid shadowing"


def test_handler_function_import():
    """All handler functions are importable."""
    _init()
    from handlers_callbacks import handle_callback, _exact_routes, _prefix_routes

    for route_name, handler in _exact_routes.items():
        assert callable(handler), f"{route_name} handler is not callable"

    for prefix, handler in _prefix_routes:
        assert callable(handler), f"'{prefix}' handler is not callable"


if __name__ == "__main__":
    print("\nRoute Tests:")
    test_all_exact_routes_registered()
    print("  OK: all 17 exact routes registered")
    test_all_prefix_routes_registered()
    print("  OK: all 9 prefix routes registered")
    test_route_ordering()
    print("  OK: route ordering correct (fav_add_ before f_)")
    test_handler_function_import()
    print("  OK: all 26 handlers are callable")
    print("  PASSED\n")
