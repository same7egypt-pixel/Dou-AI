#!/usr/bin/env python3
"""Database backup, verification, and restore.

Run from cron for the nightly backup:

    0 2 * * * cd /opt/dou-fleet && python scripts/backup.py backup >> /var/log/dou-backup.log 2>&1

A backup nobody has restored is not a backup, so ``restore`` is part of this
script rather than a runbook paragraph, and ``backup`` verifies the dump it
just wrote before reporting success.

Commands:
    backup            take a dump, verify it, upload it, prune old copies
    list              show local and remote backups
    restore <file>    restore a dump into DATABASE_URL (asks for confirmation)
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dou.db")
S3_BUCKET = os.getenv("BACKUP_S3_BUCKET", "").strip()
S3_PREFIX = os.getenv("BACKUP_S3_PREFIX", "postgres").strip("/")
RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "./backups"))


def _fail(message: str) -> None:
    print(f"FAILED: {message}", file=sys.stderr)
    sys.exit(1)


def _pg_parts():
    parsed = urllib.parse.urlparse(DATABASE_URL)
    env = os.environ.copy()
    env["PGPASSWORD"] = parsed.password or ""
    base = [
        "-h", parsed.hostname or "localhost",
        "-p", str(parsed.port or 5432),
        "-U", parsed.username or "postgres",
        "-d", parsed.path.lstrip("/"),
    ]
    return base, env


def _verify(path: Path) -> None:
    """Confirm the dump is readable and non-trivial before calling it a backup."""
    if not path.exists() or path.stat().st_size < 1024:
        _fail(f"{path} is missing or too small to be a real dump")
    if path.suffix == ".dump":
        result = subprocess.run(
            ["pg_restore", "--list", str(path)], capture_output=True, text=True
        )
        if result.returncode != 0:
            _fail(f"pg_restore could not read {path}: {result.stderr.strip()}")
        if "TABLE DATA" not in result.stdout:
            _fail(f"{path} contains no table data")
    print(f"verified {path} ({path.stat().st_size / 1_048_576:.1f} MB)")


def _s3():
    if not S3_BUCKET:
        return None
    try:
        import boto3
    except ImportError:
        _fail("BACKUP_S3_BUCKET is set but boto3 is not installed")
    return boto3.client("s3", region_name=os.getenv("AWS_REGION", "me-central-1"))


def _upload(path: Path) -> None:
    client = _s3()
    if client is None:
        print("BACKUP_S3_BUCKET is not set; keeping the backup on this host only")
        return
    key = f"{S3_PREFIX}/{path.name}"
    client.upload_file(
        str(path), S3_BUCKET, key, ExtraArgs={"ServerSideEncryption": "AES256"}
    )
    print(f"uploaded s3://{S3_BUCKET}/{key}")


def _prune() -> None:
    """Drop local dumps past the retention window. Remote copies keep their own
    lifecycle policy on the bucket."""
    cutoff = datetime.now(timezone.utc).timestamp() - RETENTION_DAYS * 86400
    for old in sorted(BACKUP_DIR.glob("dou_*")):
        if old.stat().st_mtime < cutoff:
            old.unlink()
            print(f"pruned {old.name}")


def backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if DATABASE_URL.startswith("sqlite"):
        import shutil

        source = Path(DATABASE_URL.replace("sqlite:///", "").replace("sqlite://", ""))
        if not source.exists():
            _fail(f"SQLite database {source} not found")
        target = BACKUP_DIR / f"dou_sqlite_{stamp}.db"
        shutil.copy2(source, target)
    elif DATABASE_URL.startswith(("postgresql", "postgres")):
        target = BACKUP_DIR / f"dou_postgres_{stamp}.dump"
        base, env = _pg_parts()
        result = subprocess.run(
            ["pg_dump", *base, "-F", "c", "-f", str(target)],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _fail(f"pg_dump failed: {result.stderr.strip()}")
    else:
        _fail(f"unsupported DATABASE_URL scheme: {DATABASE_URL.split(':')[0]}")

    _verify(target)
    _upload(target)
    _prune()
    print(f"OK {target}")
    return target


def list_backups() -> None:
    local = sorted(BACKUP_DIR.glob("dou_*")) if BACKUP_DIR.exists() else []
    print(f"local ({len(local)}):")
    for path in local:
        size = path.stat().st_size / 1_048_576
        when = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        print(f"  {path.name}  {size:7.1f} MB  {when:%Y-%m-%d %H:%M} UTC")

    client = _s3()
    if client is None:
        print("remote: BACKUP_S3_BUCKET not set")
        return
    response = client.list_objects_v2(Bucket=S3_BUCKET, Prefix=f"{S3_PREFIX}/")
    objects = response.get("Contents", [])
    print(f"remote ({len(objects)}):")
    for obj in sorted(objects, key=lambda o: o["LastModified"])[-10:]:
        print(
            f"  {obj['Key']}  {obj['Size'] / 1_048_576:7.1f} MB  "
            f"{obj['LastModified']:%Y-%m-%d %H:%M} UTC"
        )


def restore(path_str: str) -> None:
    path = Path(path_str)
    if not path.exists():
        _fail(f"{path} not found")
    _verify(path)

    if DATABASE_URL.startswith("sqlite"):
        destination = DATABASE_URL.replace("sqlite:///", "").replace("sqlite://", "")
        where = destination
        token = Path(destination).name
    else:
        parsed = urllib.parse.urlparse(DATABASE_URL)
        token = parsed.path.lstrip("/")
        where = f"{parsed.hostname}/{token}"

    print(f"\nThis OVERWRITES the database at {where}.")
    if input(f"Type '{token}' to confirm: ").strip() != token:
        print("aborted")
        sys.exit(1)

    if DATABASE_URL.startswith(("postgresql", "postgres")):
        base, env = _pg_parts()
        result = subprocess.run(
            ["pg_restore", *base, "--clean", "--if-exists", "--no-owner", str(path)],
            env=env,
            capture_output=True,
            text=True,
        )
        # pg_restore reports non-zero for benign "does not exist" notices under
        # --clean, so only a missing-data failure is treated as fatal.
        if result.returncode != 0 and "error" in result.stderr.lower():
            print(result.stderr, file=sys.stderr)
            _fail("pg_restore reported errors; the database may be partial")
    elif DATABASE_URL.startswith("sqlite"):
        import shutil

        shutil.copy2(path, DATABASE_URL.replace("sqlite:///", ""))
    else:
        _fail(f"unsupported DATABASE_URL scheme: {DATABASE_URL.split(':')[0]}")
    print(f"restored {path} into {where}")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "backup"
    if command == "backup":
        backup()
    elif command == "list":
        list_backups()
    elif command == "restore":
        if len(sys.argv) < 3:
            _fail("usage: backup.py restore <file>")
        restore(sys.argv[2])
    else:
        _fail(f"unknown command {command!r}; use backup, list, or restore")
