"""Process heartbeat shared by the bot loop and the web health endpoint.

The bot polling loop bumps this every 60s. The Flask /health/ready endpoint
checks its age: if the asyncio loop is wedged (e.g. blocked on a full stdout
pipe), the age grows and health returns 503 so Railway restarts the container.
Keeping this in its own module avoids circular imports between main and web_admin.
"""
import time

_last_bump = time.time()


def bump() -> None:
    global _last_bump
    _last_bump = time.time()


def age() -> float:
    return time.time() - _last_bump
