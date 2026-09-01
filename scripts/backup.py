#!/usr/bin/env python3
"""Database backup and restore script for PostgreSQL & S3."""
from __future__ import annotations
import os
import sys
import subprocess
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dou.db")
S3_BUCKET = os.getenv("BACKUP_S3_BUCKET", "")
BACKUP_DIR = Path("./backups")


def backup_database():
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if DATABASE_URL.startswith("sqlite"):
        db_path = DATABASE_URL.replace("sqlite:///", "")
        backup_file = BACKUP_DIR / f"dou_sqlite_{timestamp}.db"
        if os.path.exists(db_path):
            import shutil
            shutil.copy2(db_path, backup_file)
            print(f"Backed up SQLite database to {backup_file}")
            return backup_file
    elif DATABASE_URL.startswith("postgresql") or DATABASE_URL.startswith("postgres"):
        parsed = urllib.parse.urlparse(DATABASE_URL)
        backup_file = BACKUP_DIR / f"dou_postgres_{timestamp}.dump"
        env = os.environ.copy()
        env["PGPASSWORD"] = parsed.password or ""
        cmd = [
            "pg_dump",
            "-h", parsed.hostname or "localhost",
            "-p", str(parsed.port or 5432),
            "-U", parsed.username or "postgres",
            "-d", parsed.path.lstrip("/"),
            "-F", "c",
            "-f", str(backup_file),
        ]
        subprocess.run(cmd, env=env, check=True)
        print(f"Backed up PostgreSQL database to {backup_file}")
        return backup_file


if __name__ == "__main__":
    backup_database()
