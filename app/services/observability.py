"""Observability, Sentry integration, and structured logging."""
from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import contextmanager
from typing import Optional

SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
APP_ENV = os.getenv("APP_ENV", "development").strip()


def init_sentry():
    """Initialize Sentry error tracking if DSN configured."""
    if SENTRY_DSN:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
            sentry_sdk.init(
                dsn=SENTRY_DSN,
                environment=APP_ENV,
                integrations=[
                    FastApiIntegration(),
                    SqlalchemyIntegration(),
                ],
                traces_sample_rate=0.1 if APP_ENV == "production" else 1.0,
            )
        except Exception as e:
            logging.warning(f"Failed to initialize Sentry: {e}")


def get_request_id() -> str:
    """Generate unique request ID."""
    return str(uuid.uuid4())[:12]


@contextmanager
def timer(metric_name: str, tags: Optional[dict] = None):
    """Context manager for timing operations."""
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logging.info(f"metric={metric_name} duration_ms={duration_ms:.2f} tags={tags}")
