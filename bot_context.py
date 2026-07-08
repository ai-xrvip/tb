"""bot_context.py — Typed context object replacing module-level global state.

All mutable shared state (VIP_USERS, ALL_USERS, INVITES, url_store, etc.)
lives in a single BotContext dataclass.  Functions receive `ctx` as a
parameter instead of mutating module globals.  This makes the code:
  - testable: inject a context in unit tests
  - inspectable: all state is in one place
  - safe: no module-level side effects

For backward compatibility during migration, a module-level singleton
is provided and populated during startup.  Existing code that accesses
`bot_utils.VIP_USERS` etc. is redirected via property-like module
attributes that delegate to the singleton.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

# ── The context object ──────────────────────────────────────────


@dataclass
class BotContext:
    """All mutable shared state for the bot runtime."""

    # ── Persistent data (loaded from DB at startup) ──
    vip_users: dict[int, float | None] = field(default_factory=dict)
    all_users: set[int] = field(default_factory=set)
    invites: dict[str, str] = field(default_factory=dict)

    # ── Ephemeral runtime state ──
    user_search_state: dict[int, Any] = field(default_factory=dict)
    user_waiting_search: set[int] = field(default_factory=set)
    user_waiting_card: set[int] = field(default_factory=set)
    url_store: dict[str, Any] = field(default_factory=dict)
    admin_setvip_state: dict[int, bool] = field(default_factory=dict)
    url_counter: int = 0
    user_search_times: dict[int, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )

    # ── Locks (created at startup) ──
    url_store_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    url_counter_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    user_search_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    download_sem: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(12))

    # ── Constants ──
    admin_ids: set[int] = field(default_factory=set)


# ── Module-level singleton (populated by bot.py during startup) ─

_ctx: BotContext = BotContext()


def get_ctx() -> BotContext:
    """Return the current runtime context singleton."""
    return _ctx


def set_ctx(ctx: BotContext) -> None:
    """Replace the runtime context (used during startup / testing)."""
    global _ctx
    _ctx = ctx
