#!/usr/bin/env python3
"""DOU Fleet OS — Production Pre-flight Readiness Checker."""
from __future__ import annotations
import sys
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

def check_preflight():
    print("=" * 60)
    print("🚀 DOU Fleet OS — Production Pre-Flight Checklist")
    print("=" * 60)
    
    passed = True
    
    # 1. Environment & Config
    app_env = os.getenv("APP_ENV", "development").lower()
    secret_key = os.getenv("SECRET_KEY", "")
    admin_key = os.getenv("ADMIN_KEY", "")
    db_url = os.getenv("DATABASE_URL", "sqlite:///./dou.db")
    
    print(f"[*] Environment: {app_env}")
    print(f"[*] Database URL: {db_url.split("@")[-1] if "@" in db_url else db_url}")
    
    if app_env in ("production", "prod"):
        if not secret_key or len(secret_key.encode("utf-8")) < 32 or "change-me" in secret_key:
            print("❌ FAIL: SECRET_KEY must be configured with >= 32 secure random bytes in production.")
            passed = False
        else:
            print("✅ PASS: SECRET_KEY is securely configured (>= 32 bytes).")
            
        if not admin_key or len(admin_key.encode("utf-8")) < 16 or "change-me" in admin_key:
            print("❌ FAIL: ADMIN_KEY must be configured with >= 16 secure bytes in production.")
            passed = False
        else:
            print("✅ PASS: ADMIN_KEY is securely configured.")
    else:
        print("ℹ️  INFO: Running in non-production mode.")
        
    # 2. Test DB Connection
    try:
        from app.database import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ PASS: Database connectivity verified.")
    except Exception as e:
        print(f"❌ FAIL: Database connection failed: {e}")
        passed = False
        
    # 3. Test Redis (optional)
    redis_url = os.getenv("REDIS_URL", "")
    if redis_url:
        try:
            import redis
            r = redis.from_url(redis_url)
            r.ping()
            print("✅ PASS: Redis caching connection verified.")
        except Exception as e:
            print(f"⚠️  WARN: Redis configured but unreachable ({e}). Fallback to direct DB.")
    else:
        print("ℹ️  INFO: Redis not configured. Direct DB caching fallback active.")
        
    print("=" * 60)
    if passed:
        print("🎉 ALL PRE-FLIGHT CHECKS PASSED. Ready for launch!")
        sys.exit(0)
    else:
        print("🚨 PRE-FLIGHT CHECKS FAILED. Correct the above issues before launching.")
        sys.exit(1)

if __name__ == "__main__":
    check_preflight()
