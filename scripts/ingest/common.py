"""Shared helpers for ingesting external company lists into pp-jobapp DB.

Convention:
- One script per source at scripts/ingest/<slug>.py
- Each script yields a stream of CompanyRecord and calls ingest_companies()
- Raw downloads land in workspace/data/external/<slug>/<YYYY-MM-DD>/
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urlparse

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)
import storage  # noqa: E402


@dataclass
class CompanyRecord:
    """One company row from an external source.

    Only canonical_name is required. raw_metadata holds source-specific fields
    that aren't promoted to companies-master columns.
    """
    canonical_name: str
    website_url: str | None = None
    ticker: str | None = None
    hq_city: str | None = None
    hq_state: str | None = None
    employee_count: int | None = None
    company_type: str | None = None
    stage: str | None = None
    vertical: str | None = None
    headcount_range: str | None = None
    source_rank: int | None = None
    raw_name: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestSummary:
    created: int = 0
    matched: int = 0
    source_rows_added: int = 0
    source_rows_updated: int = 0
    skipped: int = 0
    errors: int = 0

    def __str__(self) -> str:
        return (
            f"created={self.created} matched={self.matched} "
            f"source_rows_added={self.source_rows_added} "
            f"source_rows_updated={self.source_rows_updated} "
            f"skipped={self.skipped} errors={self.errors}"
        )


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url if "://" in url else "http://" + url).netloc.lower()
    except ValueError:
        return None
    return host.removeprefix("www.") or None


def _find_existing_id(conn, record: CompanyRecord) -> int | None:
    """Match by normalized_name first, then website domain (exact host) as a fallback."""
    norm = storage.normalize_name(record.canonical_name)
    if norm:
        row = conn.execute("SELECT id FROM companies WHERE normalized_name = ?", (norm,)).fetchone()
        if row:
            return int(row["id"])
    dom = _domain(record.website_url)
    if not dom:
        return None
    # Pull candidates with the domain substring, then verify exact host match in Python.
    # Avoids 'att.com' matching 'exowatt.com' but stays index-friendly.
    rows = conn.execute(
        "SELECT id, website_url FROM companies WHERE LOWER(website_url) LIKE ?",
        (f"%{dom}%",),
    ).fetchall()
    for r in rows:
        if _domain(r["website_url"]) == dom:
            return int(r["id"])
    return None


def ingest_companies(
    records: Iterable[CompanyRecord],
    *,
    source_type: str,
    source_name: str = "",
    merge_keys: tuple[str, ...] = (),
    one_row_per_company: bool = False,
    db_path: str | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> IngestSummary:
    """Ingest a stream of CompanyRecord into companies + company_sources.

    Args:
        source_type: bucket label, e.g. "fortune_1000", "builtin_bptw"
        source_name: specific list within bucket, e.g. "2024", "2025"
        merge_keys: JSON keys whose lists should be merged across re-runs
            (only meaningful when one_row_per_company=True)
        one_row_per_company: if True, use upsert_company_source_metadata so a
            company's metadata accumulates across runs (Built In pattern).
            If False, use add_company_source — INSERT OR IGNORE keyed on
            (company_id, source_type, source_name, raw_name) (Fortune pattern).
    """
    summary = IngestSummary()
    conn = storage.connect(db_path or storage.DEFAULT_DB_PATH)
    try:
        for rec in records:
            if not rec.canonical_name or not rec.canonical_name.strip():
                summary.skipped += 1
                continue
            try:
                existing_id = _find_existing_id(conn, rec)
                if dry_run:
                    if existing_id:
                        summary.matched += 1
                    else:
                        summary.created += 1
                    summary.source_rows_added += 1
                    continue

                company_id = storage.upsert_company(
                    conn, rec.canonical_name,
                    website_url=rec.website_url,
                    stage=rec.stage,
                    vertical=rec.vertical,
                    headcount_range=rec.headcount_range,
                    ticker=rec.ticker,
                    hq_city=rec.hq_city,
                    hq_state=rec.hq_state,
                    employee_count=rec.employee_count,
                    company_type=rec.company_type,
                )
                if existing_id:
                    summary.matched += 1
                else:
                    summary.created += 1

                if one_row_per_company:
                    pre = conn.execute(
                        "SELECT id FROM company_sources WHERE company_id=? AND source_type=? AND source_name=?",
                        (company_id, source_type, source_name),
                    ).fetchone()
                    storage.upsert_company_source_metadata(
                        conn, company_id,
                        source_type=source_type, source_name=source_name,
                        raw_name=rec.raw_name, source_rank=rec.source_rank,
                        raw_metadata=rec.raw_metadata, merge_keys=merge_keys,
                    )
                    if pre:
                        summary.source_rows_updated += 1
                    else:
                        summary.source_rows_added += 1
                else:
                    before = conn.execute("SELECT COUNT(*) FROM company_sources").fetchone()[0]
                    storage.add_company_source(
                        conn, company_id,
                        source_type=source_type, source_name=source_name,
                        source_rank=rec.source_rank, raw_name=rec.raw_name,
                        raw_metadata=rec.raw_metadata,
                    )
                    after = conn.execute("SELECT COUNT(*) FROM company_sources").fetchone()[0]
                    if after > before:
                        summary.source_rows_added += 1
                    else:
                        summary.source_rows_updated += 1  # INSERT OR IGNORE was a no-op
            except Exception as e:
                summary.errors += 1
                if verbose:
                    print(f"  ERROR on {rec.canonical_name!r}: {e}", file=sys.stderr)

        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return summary
