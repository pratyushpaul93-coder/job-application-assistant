#!/usr/bin/env python3
"""Import current JSON/CSV state into SQLite without changing live behavior."""

from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

import storage


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
WORKSPACE = ROOT / "workspace"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open() as f:
        return json.load(f)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def parse_companies_literal() -> list[dict[str, Any]]:
    source = (SCRIPTS / "ats_scout.py").read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "COMPANIES" for t in node.targets):
                return ast.literal_eval(node.value)
    return []


def int_or_none(value: Any) -> int | None:
    try:
        if value in ("", None):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def float_or_none(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def ats_url(provider: str, slug: str) -> str:
    if not slug:
        return ""
    if provider == "ashby":
        return f"https://jobs.ashbyhq.com/{slug}"
    if provider == "greenhouse":
        return f"https://boards.greenhouse.io/{slug}"
    if provider == "lever":
        return f"https://jobs.lever.co/{slug}"
    return ""


def import_company_seed(conn: sqlite3.Connection) -> None:
    for row in parse_companies_literal():
        company_id = storage.upsert_company(
            conn,
            row["name"],
            stage=row.get("stage"),
            vertical=row.get("vertical"),
            active=row.get("ats") not in {"broken", "tavily"},
        )
        storage.add_company_source(
            conn,
            company_id,
            source_type="ats_scout",
            source_name="COMPANIES",
            raw_name=row["name"],
            raw_metadata=row,
        )
        if row.get("slug"):
            status = "active" if row.get("ats") in {"ashby", "greenhouse", "lever"} else "skipped"
            storage.upsert_ats_endpoint(
                conn,
                company_id,
                provider=row.get("ats", "unknown"),
                slug=row["slug"],
                ats_url=ats_url(row.get("ats", ""), row["slug"]),
                status=status,
                raw_metadata=row,
            )


def import_name_lists(conn: sqlite3.Connection) -> None:
    for path, source_name in (
        (SCRIPTS / "companies_master.txt", "companies_master"),
        (SCRIPTS / "a16z_companies.txt", "a16z"),
    ):
        for name in read_lines(path):
            company_id = storage.upsert_company(conn, name, active=False)
            storage.add_company_source(
                conn,
                company_id,
                source_type="name_list",
                source_name=source_name,
                raw_name=name,
            )


def import_vc_companies(conn: sqlite3.Connection) -> None:
    for row in read_csv(WORKSPACE / "all_vc_companies.csv"):
        name = row.get("company_name") or row.get("company") or ""
        if not name:
            continue
        company_id = storage.upsert_company(
            conn,
            name,
            website_url=row.get("company_url"),
            stage=row.get("funding_stage"),
            headcount_range=row.get("headcount_range"),
            active=False,
        )
        storage.add_company_source(
            conn,
            company_id,
            source_type="getro_vc",
            source_name=row.get("vc", ""),
            raw_name=name,
            raw_metadata=row,
        )


def import_ats_mapping(conn: sqlite3.Connection) -> None:
    for row in read_csv(WORKSPACE / "ats_mapping_779.csv"):
        name = row.get("company_name") or ""
        if not name:
            continue
        company_id = storage.upsert_company(
            conn,
            name,
            stage=row.get("funding_stage"),
            vertical=row.get("vertical_assigned"),
            headcount_range=row.get("headcount_range"),
            active=row.get("ats_provider") in {"ashby", "greenhouse", "lever"},
        )
        storage.add_company_source(
            conn,
            company_id,
            source_type="ats_mapping",
            source_name="getro_ranked_779",
            source_rank=int_or_none(row.get("rank")),
            fit_score=float_or_none(row.get("fit_score")),
            raw_name=name,
            raw_metadata=row,
        )
        if row.get("ats_provider") in {"ashby", "greenhouse", "lever"} and row.get("ats_slug"):
            prior_status = row.get("prior_status") or ""
            status = "active" if not prior_status.startswith("previously_failed") else "failed"
            storage.upsert_ats_endpoint(
                conn,
                company_id,
                provider=row["ats_provider"],
                slug=row["ats_slug"],
                ats_url=row.get("ats_url") or ats_url(row["ats_provider"], row["ats_slug"]),
                status=status,
                open_jobs_actual=int_or_none(row.get("open_jobs_actual")),
                raw_metadata=row,
            )


def import_bulk_results(conn: sqlite3.Connection) -> None:
    for row in read_csv(SCRIPTS / "bulk_add_results.csv"):
        name = row.get("company") or ""
        if not name:
            continue
        company_id = storage.upsert_company(
            conn,
            name,
            active=row.get("status") in {"added", "duplicate"},
        )
        storage.add_company_source(
            conn,
            company_id,
            source_type="bulk_add_checkpoint",
            source_name=row.get("status", ""),
            raw_name=name,
            raw_metadata=row,
        )
        if row.get("ats") in {"ashby", "greenhouse", "lever"} and row.get("slug"):
            status = "active" if row.get("status") in {"added", "duplicate"} else "failed"
            storage.upsert_ats_endpoint(
                conn,
                company_id,
                provider=row["ats"],
                slug=row["slug"],
                ats_url=ats_url(row["ats"], row["slug"]),
                status=status,
                open_jobs_actual=int_or_none(row.get("total_jobs")),
                raw_metadata=row,
            )


def endpoint_for_job(conn: sqlite3.Connection, company_id: int, job: dict[str, Any]) -> int | None:
    source = (job.get("source") or "").lower()
    if not source:
        return None
    rows = conn.execute(
        "SELECT id, slug FROM ats_endpoints WHERE company_id = ? AND provider = ?",
        (company_id, source),
    ).fetchall()
    if not rows:
        return None
    if len(rows) == 1:
        return int(rows[0]["id"])
    url = (job.get("job_url") or job.get("apply_url") or "").lower()
    for row in rows:
        if row["slug"].lower() in url:
            return int(row["id"])
    return int(rows[0]["id"])


def import_scan_runs_and_jobs(conn: sqlite3.Connection) -> None:
    raw = read_json(WORKSPACE / "raw_jobs.json", {})
    if raw:
        raw_meta = storage.json_dumps({k: v for k, v in raw.items() if k != "jobs"})
        exists = conn.execute(
            """
            SELECT 1
            FROM scan_runs
            WHERE scan_date IS ?
              AND scan_method IS ?
              AND config_version IS ?
              AND raw_metadata_json = ?
            """,
            (raw.get("scan_date"), raw.get("scan_method"), raw.get("config_version"), raw_meta),
        ).fetchone()
        if not exists:
            conn.execute(
                """
                INSERT INTO scan_runs
                    (scan_date, scan_method, config_version, total_companies_scanned,
                     total_matches, raw_metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    raw.get("scan_date"),
                    raw.get("scan_method"),
                    raw.get("config_version"),
                    raw.get("total_companies_scanned"),
                    raw.get("total_matches"),
                    raw_meta,
                ),
            )
    for job in raw.get("jobs", []):
        company_id = storage.upsert_company(
            conn,
            job.get("company_name") or "Unknown",
            stage=job.get("company_stage"),
            vertical=job.get("industry_vertical"),
        )
        endpoint_id = endpoint_for_job(conn, company_id, job)
        storage.upsert_job_posting(conn, job, company_id=company_id, ats_endpoint_id=endpoint_id)


def job_id_for_url(conn: sqlite3.Connection, url: str | None) -> int | None:
    if not url:
        return None
    row = conn.execute("SELECT job_id FROM job_url_aliases WHERE url = ?", (url,)).fetchone()
    return int(row["job_id"]) if row else None


def import_shortlist_scores(conn: sqlite3.Connection) -> None:
    shortlist = read_json(WORKSPACE / "shortlist.json", {})
    for job in shortlist.get("jobs", []):
        company_id = storage.upsert_company(
            conn,
            job.get("company_name") or "Unknown",
            stage=job.get("company_stage"),
            vertical=job.get("industry_vertical"),
        )
        endpoint_id = endpoint_for_job(conn, company_id, job)
        job_id = storage.upsert_job_posting(conn, job, company_id=company_id, ats_endpoint_id=endpoint_id)
        score = job.get("match_score")
        if isinstance(score, int):
            reason = job.get("match_reason") or job.get("reason") or ""
            flags = job.get("match_flags") or []
            storage.add_job_score(conn, job_id, scorer="current_shortlist", score=score, reason=reason, flags=flags)


def import_interactions(conn: sqlite3.Connection) -> None:
    comments = read_json(WORKSPACE / "comments.json", {})
    feedback = read_json(WORKSPACE / "feedback.json", {})
    statuses = read_json(WORKSPACE / "job_status.json", {})
    selected = set(read_json(WORKSPACE / "selected.json", []))
    urls = set(comments) | set(feedback) | set(statuses) | selected
    for url in urls:
        job_id = job_id_for_url(conn, url)
        if not job_id:
            continue
        comment_entry = comments.get(url) or {}
        feedback_entry = feedback.get(url) or {}
        status_entry = statuses.get(url) or {}
        conn.execute(
            """
            INSERT INTO job_interactions
                (job_id, selected, reviewed, applied, comment, tags_json,
                 manual_score, manual_score_comment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                selected = MAX(job_interactions.selected, excluded.selected),
                reviewed = MAX(job_interactions.reviewed, excluded.reviewed),
                applied = MAX(job_interactions.applied, excluded.applied),
                comment = COALESCE(NULLIF(excluded.comment, ''), job_interactions.comment),
                tags_json = excluded.tags_json,
                manual_score = COALESCE(excluded.manual_score, job_interactions.manual_score),
                manual_score_comment = COALESCE(NULLIF(excluded.manual_score_comment, ''), job_interactions.manual_score_comment),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                job_id,
                int(url in selected),
                int(bool(status_entry.get("reviewed"))),
                int(bool(status_entry.get("applied"))),
                comment_entry.get("text", ""),
                storage.json_dumps(comment_entry.get("tags") or []),
                feedback_entry.get("manual_score"),
                feedback_entry.get("comment", ""),
            ),
        )
        if isinstance(feedback_entry.get("manual_score"), int):
            storage.add_job_score(
                conn,
                job_id,
                scorer="manual",
                score=int(feedback_entry["manual_score"]),
                reason=feedback_entry.get("comment", ""),
            )


def import_resume_artifacts(conn: sqlite3.Connection) -> None:
    rows = read_json(WORKSPACE / "tailored_resumes.json", [])
    for row in rows:
        job_id = job_id_for_url(conn, row.get("job_url"))
        company_id = None
        if row.get("company_name"):
            company_id = storage.upsert_company(conn, row["company_name"])
        filename = row.get("tailored_file") or ""
        filename_pdf = re.sub(r"\.txt$", ".pdf", filename) if filename.endswith(".txt") else ""
        exists = conn.execute(
            "SELECT 1 FROM resume_artifacts WHERE source_job_url = ? AND filename_txt = ?",
            (row.get("job_url"), filename),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """
            INSERT INTO resume_artifacts
                (job_id, company_id, role_title, filename_txt, filename_pdf,
                 tailored_date, source_job_url, raw_metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                company_id,
                row.get("role_title"),
                filename,
                filename_pdf,
                row.get("tailored_date"),
                row.get("job_url"),
                storage.json_dumps(row),
            ),
        )


def validate(conn: sqlite3.Connection) -> dict[str, int]:
    counts = {}
    for table in (
        "companies",
        "company_sources",
        "ats_endpoints",
        "scan_runs",
        "job_postings",
        "job_url_aliases",
        "job_scores",
        "job_interactions",
        "resume_artifacts",
    ):
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        counts[table] = int(row["n"])

    raw_jobs = len(read_json(WORKSPACE / "raw_jobs.json", {}).get("jobs", []))
    shortlist_jobs = len(read_json(WORKSPACE / "shortlist.json", {}).get("jobs", []))
    companies_seed = len(parse_companies_literal())
    counts["raw_jobs_json"] = raw_jobs
    counts["shortlist_json"] = shortlist_jobs
    counts["companies_seed"] = companies_seed

    if counts["job_postings"] < raw_jobs:
        raise RuntimeError(f"DB job_postings below raw_jobs.json count: {counts['job_postings']} < {raw_jobs}")
    if counts["companies"] < companies_seed:
        raise RuntimeError(f"DB companies below COMPANIES count: {counts['companies']} < {companies_seed}")
    return counts


def run(db_path: Path, reset: bool = False) -> dict[str, int]:
    if reset and db_path.exists():
        db_path.unlink()
    conn = storage.connect(db_path)
    try:
        storage.init_db(conn)
        import_company_seed(conn)
        import_name_lists(conn)
        import_vc_companies(conn)
        import_ats_mapping(conn)
        import_bulk_results(conn)
        import_scan_runs_and_jobs(conn)
        import_shortlist_scores(conn)
        import_interactions(conn)
        import_resume_artifacts(conn)
        conn.commit()
        return validate(conn)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(storage.DEFAULT_DB_PATH), help="SQLite DB path")
    parser.add_argument("--reset", action="store_true", help="Delete existing DB before importing")
    args = parser.parse_args()

    db_path = Path(args.db)
    counts = run(db_path, reset=args.reset)
    print(f"Imported current state into {db_path}")
    for key in sorted(counts):
        print(f"{key:20s} {counts[key]}")


if __name__ == "__main__":
    main()
