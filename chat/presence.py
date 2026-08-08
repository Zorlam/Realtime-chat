"""
Tracks how many active WebSocket connections each user currently has,
using a Redis counter rather than a simple boolean. This matters because
a user can have the app open in multiple tabs (or a DM room open on two
devices) — going offline should only happen when their *last* connection
closes, not their first. Using INCR/DECR on a shared counter (rather than
per-consumer local state) also means this works correctly across multiple
server processes, which matters once Phase 5's horizontal scaling comes in.
"""

import os

import redis.asyncio as redis

_redis_client = None


def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=os.environ.get("REDIS_HOST", "127.0.0.1"),
            port=int(os.environ.get("REDIS_PORT", 6379)),
            socket_timeout=30,
            socket_connect_timeout=30,
            retry_on_timeout=True,
            decode_responses=True,
        )
    return _redis_client


async def mark_connected(user_id: int) -> bool:
    """Increments the connection counter. Returns True if this was the
    user's first active connection (i.e. they just went online)."""
    r = get_redis()
    count = await r.incr(f"presence:user:{user_id}")
    return count == 1


async def mark_disconnected(user_id: int) -> bool:
    """Decrements the connection counter. Returns True if the user has no
    remaining connections (i.e. they just went offline)."""
    r = get_redis()
    count = await r.decr(f"presence:user:{user_id}")
    if count <= 0:
        await r.delete(f"presence:user:{user_id}")
        return True
    return False


async def is_online(user_id: int) -> bool:
    r = get_redis()
    count = await r.get(f"presence:user:{user_id}")
    return count is not None and int(count) > 0