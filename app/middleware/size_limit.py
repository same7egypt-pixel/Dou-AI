from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_size_bytes: int = 15 * 1024 * 1024):  # 15MB
        super().__init__(app)
        self.max_size_bytes = max_size_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_size_bytes:
            raise HTTPException(413, "Request payload too large (maximum 15MB allowed)")
        return await call_next(request)
