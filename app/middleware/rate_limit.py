from __future__ import annotations
import time
from collections import defaultdict
from threading import Lock
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 300):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests: dict[str, list[float]] = defaultdict(list)
        self.lock = Lock()

    async def dispatch(self, request: Request, call_next):
        # Exclude static assets and health probes from strict rate limiting
        path = request.url.path
        if path.startswith("/static") or path.startswith("/frontend-v2") or path.startswith("/health"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window = 60.0

        with self.lock:
            self.requests[client_ip] = [
                t for t in self.requests[client_ip] if now - t < window
            ]
            if len(self.requests[client_ip]) >= self.requests_per_minute:
                raise HTTPException(
                    429, "Too many requests. Please slow down and try again."
                )
            self.requests[client_ip].append(now)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, self.requests_per_minute - len(self.requests[client_ip]))
        )
        return response
