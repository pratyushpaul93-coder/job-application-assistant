#!/usr/bin/env python3
"""Ingest the 2024 Fortune 1000 Kaggle dataset.

Raw file lives at workspace/data/external/fortune1000/fortune1000_2024.csv
(re-download with: kaggle datasets download -d jeannicolasduval/2024-fortune-1000-companies --unzip)

Usage:
    python3 -m ingest.fortune1000              # ingest into the live DB
    python3 -m ingest.fortune1000 --dry-run    # report matches/creates without writing
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from typing import Iterator

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

from ingest.common import CompanyRecord, ingest_companies  # noqa: E402

CSV_PATH = "/root/pp-jobapp/workspace/data/external/fortune1000/fortune1000_2024.csv"
SOURCE_TYPE = "fortune_1000"
SOURCE_NAME = "2024"

# raw_metadata fields — columns we want to keep verbatim from the CSV
META_FIELDS = (
    "Sector", "Industry", "Profitable", "Founder_is_CEO", "FemaleCEO",
    "Growth_in_Jobs", "Change_in_Rank", "Gained_in_Rank", "Dropped_in_Rank",
    "Newcomer_to_the_Fortune500", "Global500", "Worlds_Most_Admired_Companies",
    "Best_Companies_to_Work_For", "MarketCap_March28_M", "Revenues_M",
    "RevenuePercentChange", "Profits_M", "ProfitsPercentChange", "Assets_M",
    "CEO", "Country", "Footnote", "MarketCap_Updated_M", "Updated",
)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _int(value: str | None) -> int | None:
    s = _clean(value)
    if s is None:
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def parse(csv_path: str = CSV_PATH) -> Iterator[CompanyRecord]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = _clean(row.get("Company"))
            if not name:
                continue
            meta = {k: row.get(k) for k in META_FIELDS if _clean(row.get(k)) is not None}
            yield CompanyRecord(
                canonical_name=name,
                raw_name=name,
                website_url=_clean(row.get("Website")),
                ticker=_clean(row.get("Ticker")),
                hq_city=_clean(row.get("HeadquartersCity")),
                hq_state=_clean(row.get("HeadquartersState")),
                employee_count=_int(row.get("Number_of_employees")),
                company_type=_clean(row.get("CompanyType")),
                source_rank=_int(row.get("Rank")),
                raw_metadata=meta,
            )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV_PATH)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        sys.exit(f"CSV not found at {args.csv}")

    summary = ingest_companies(
        parse(args.csv),
        source_type=SOURCE_TYPE,
        source_name=SOURCE_NAME,
        one_row_per_company=False,  # Fortune: each company appears once in source
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    print(f"[{'DRY-RUN' if args.dry_run else 'INGEST'}] fortune_1000/2024 — {summary}")


if __name__ == "__main__":
    main()
