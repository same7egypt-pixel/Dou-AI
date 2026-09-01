"""Redis caching service with graceful fallback."""
from __future__ import annotations
import json
import hashlib
from functools import wraps
from typing import Optional, Callable, Any
import os

_redis = None
_redis_initialized = False

def get_redis():
    global _redis, _redis_initialized
    if not _redis_initialized:
        redis_url = os.getenv("REDIS_URL", "").strip()
        if redis_url:
            try:
                import redis
                _redis = redis.from_url(redis_url, decode_responses=True)
                _redis.ping()
            except Exception:
                _redis = None
        _redis_initialized = True
    return _redis


def cache_result(prefix: str, ttl: int = 300, key_fn: Optional[Callable] = None):
    """Cache function results in Redis if available."""
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            r = get_redis()
            if not r:
                return fn(*args, **kwargs)

            try:
                if key_fn:
                    cache_key = f"{prefix}:{key_fn(*args, **kwargs)}"
                else:
                    raw = f"{args}:{sorted(kwargs.items())}"
                    cache_key = f"{prefix}:{hashlib.md5(raw.encode()).hexdigest()}"

                cached = r.get(cache_key)
                if cached:
                    return json.loads(cached)

                result = fn(*args, **kwargs)
                r.setex(cache_key, ttl, json.dumps(result, default=str))
                return result
            except Exception:
                # If cache fails, always fallback to direct execution
                return fn(*args, **kwargs)
        return wrapper
    return decorator


def invalidate_cache(prefix: str, key_pattern: str = "*"):
    """Invalidate cache entries matching a pattern."""
    r = get_redis()
    if r:
        try:
            for k in r.scan_iter(f"{prefix}:{key_pattern}"):
                r.delete(k)
        except Exception:
            pass
