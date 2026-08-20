"""Record repeatable API and SQL-query baseline metrics for the isolated DOU QA tenant."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

from fastapi.testclient import TestClient
from sqlalchemy import event

BASE = Path(__file__).resolve().parents[1]
os.chdir(BASE)
sys.path.insert(0, str(BASE))

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402


QA_PHONE = "966581112233"
QA_PASSWORD = "QAPerfPass123"
DEFAULT_PATHS = {
    "dashboard_meta": "/fleet/me",
    "dashboard_overview": "/fleet/overview",
    "riders_legacy_full_list": "/fleet/couriers",
    "riders_paginated": "/fleet/couriers/page?page=1&page_size=50",
    "rider_search_paginated": "/fleet/couriers/page?page=1&page_size=50&search=QA%20Rider%2000001",
    "needs_attention": "/fleet/needs-attention",
    "analytics_executive": "/fleet/analytics/executive?page=1&page_size=50",
    "analytics_operations": "/fleet/analytics/operations?page=1&page_size=50",
    "analytics_financial": "/fleet/analytics/financial?page=1&page_size=50",
    "analytics_workforce": "/fleet/analytics/workforce?page=1&page_size=50",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--output", default="artifacts/performance_baseline_qa.json")
    return parser.parse_args()


def percentile(values: list[float], percentage: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentage)))
    return ordered[index]


def main() -> None:
    args = parse_args()
    if args.samples < 3:
        raise SystemExit("Use at least three samples for a baseline")
    sql_counter = {"count": 0}

    def count_sql(*_args: object, **_kwargs: object) -> None:
        sql_counter["count"] += 1

    event.listen(engine, "before_cursor_execute", count_sql)
    try:
        client = TestClient(app)
        login_start = perf_counter()
        login_response = client.post("/auth/login", json={"phone": QA_PHONE, "password": QA_PASSWORD})
        login_ms = (perf_counter() - login_start) * 1000
        if login_response.status_code != 200:
            raise SystemExit(f"QA login failed: {login_response.status_code} {login_response.text}")
        headers = {"Authorization": "Bearer " + login_response.json()["access_token"]}
        report = {
            "environment": "isolated-qa",
            "samples": args.samples,
            "login": {"status": login_response.status_code, "ms": round(login_ms, 2), "bytes": len(login_response.content)},
            "endpoints": {},
        }
        for label, path in DEFAULT_PATHS.items():
            samples = []
            for _ in range(args.samples):
                start_sql = sql_counter["count"]
                start = perf_counter()
                response = client.get(path, headers=headers)
                elapsed = (perf_counter() - start) * 1000
                samples.append({
                    "status": response.status_code,
                    "ms": round(elapsed, 2),
                    "bytes": len(response.content),
                    "sql_queries": sql_counter["count"] - start_sql,
                })
            times = [sample["ms"] for sample in samples]
            report["endpoints"][label] = {
                "path": path,
                "status": sorted({sample["status"] for sample in samples}),
                "median_ms": round(median(times), 2),
                "p95_ms": round(percentile(times, 0.95), 2),
                "max_bytes": max(sample["bytes"] for sample in samples),
                "median_sql_queries": round(median([sample["sql_queries"] for sample in samples]), 2),
                "samples": samples,
            }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        event.remove(engine, "before_cursor_execute", count_sql)


if __name__ == "__main__":
    main()
