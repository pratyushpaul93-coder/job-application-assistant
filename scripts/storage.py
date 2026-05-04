#!/usr/bin/env python3
"""SQLite storage primitives for the job application assistant."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "workspace"
DEFAULT_DB_PATH = WORKSPACE / "jobapp.db"


def normalize_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def normalize_title(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()


def json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def connect(path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_columns(conn)
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Idempotent in-place column migrations for existing DBs.

    Skips silently when the target table doesn't exist yet — init_db will
    create it from SCHEMA which already includes the latest columns.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(job_scores)")}
    if not cols:
        return  # table not yet created; nothing to migrate
    if "rubric_version" not in cols:
        conn.execute(
            "ALTER TABLE job_scores ADD COLUMN rubric_version TEXT NOT NULL DEFAULT '0'"
        )
        conn.commit()


SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    website_url TEXT,
    stage TEXT,
    vertical TEXT,
    headcount_range TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS company_sources (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    source_rank INTEGER,
    fit_score REAL,
    raw_name TEXT,
    raw_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, source_type, source_name, raw_name)
);

CREATE TABLE IF NOT EXISTS ats_endpoints (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    slug TEXT NOT NULL,
    ats_url TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    open_jobs_actual INTEGER,
    last_checked_at TEXT,
    raw_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, slug)
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY,
    scan_date TEXT,
    scan_method TEXT,
    config_version TEXT,
    total_companies_scanned INTEGER,
    total_matches INTEGER,
    raw_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_postings (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    ats_endpoint_id INTEGER REFERENCES ats_endpoints(id) ON DELETE SET NULL,
    source TEXT NOT NULL,
    external_job_id TEXT NOT NULL,
    job_url TEXT,
    apply_url TEXT,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    location_raw TEXT,
    remote_ok INTEGER NOT NULL DEFAULT 0,
    posted_date TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    jd_text TEXT,
    raw_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, external_job_id)
);

CREATE TABLE IF NOT EXISTS job_url_aliases (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    url TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_scores (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    scorer TEXT NOT NULL,
    score INTEGER NOT NULL,
    reason TEXT,
    flags_json TEXT NOT NULL DEFAULT '[]',
    rubric_version TEXT NOT NULL DEFAULT '0',
    scored_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, scorer)
);

CREATE TABLE IF NOT EXISTS job_interactions (
    job_id INTEGER PRIMARY KEY REFERENCES job_postings(id) ON DELETE CASCADE,
    selected INTEGER NOT NULL DEFAULT 0,
    reviewed INTEGER NOT NULL DEFAULT 0,
    applied INTEGER NOT NULL DEFAULT 0,
    comment TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    manual_score INTEGER,
    manual_score_comment TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS resume_artifacts (
    id INTEGER PRIMARY KEY,
    job_id INTEGER REFERENCES job_postings(id) ON DELETE SET NULL,
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    role_title TEXT,
    filename_txt TEXT NOT NULL,
    filename_pdf TEXT,
    tailored_date TEXT,
    source_job_url TEXT,
    raw_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_companies_active ON companies(active);
CREATE INDEX IF NOT EXISTS idx_job_postings_company ON job_postings(company_id);
CREATE INDEX IF NOT EXISTS idx_job_postings_posted ON job_postings(posted_date);
CREATE INDEX IF NOT EXISTS idx_job_scores_scorer_score ON job_scores(scorer, score);
"""


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_company(
    conn: sqlite3.Connection,
    name: str,
    *,
    website_url: str | None = None,
    stage: str | None = None,
    vertical: str | None = None,
    headcount_range: str | None = None,
    active: bool = True,
) -> int:
    normalized = normalize_name(name)
    if not normalized:
        raise ValueError("company name is required")
    conn.execute(
        """
        INSERT INTO companies
            (canonical_name, normalized_name, website_url, stage, vertical, headcount_range, active)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(normalized_name) DO UPDATE SET
            canonical_name = COALESCE(NULLIF(excluded.canonical_name, ''), companies.canonical_name),
            website_url = COALESCE(NULLIF(excluded.website_url, ''), companies.website_url),
            stage = COALESCE(NULLIF(excluded.stage, ''), companies.stage),
            vertical = COALESCE(NULLIF(excluded.vertical, ''), companies.vertical),
            headcount_range = COALESCE(NULLIF(excluded.headcount_range, ''), companies.headcount_range),
            active = MAX(companies.active, excluded.active),
            updated_at = CURRENT_TIMESTAMP
        """,
        (name.strip(), normalized, website_url, stage, vertical, headcount_range, int(active)),
    )
    row = conn.execute("SELECT id FROM companies WHERE normalized_name = ?", (normalized,)).fetchone()
    return int(row["id"])


def add_company_source(
    conn: sqlite3.Connection,
    company_id: int,
    *,
    source_type: str,
    source_name: str = "",
    source_rank: int | None = None,
    fit_score: float | None = None,
    raw_name: str | None = None,
    raw_metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO company_sources
            (company_id, source_type, source_name, source_rank, fit_score, raw_name, raw_metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company_id,
            source_type,
            source_name or "",
            source_rank,
            fit_score,
            raw_name,
            json_dumps(raw_metadata or {}),
        ),
    )


def upsert_ats_endpoint(
    conn: sqlite3.Connection,
    company_id: int,
    *,
    provider: str,
    slug: str,
    ats_url: str | None = None,
    status: str = "active",
    open_jobs_actual: int | None = None,
    raw_metadata: dict[str, Any] | None = None,
) -> int:
    provider = (provider or "").strip().lower()
    slug = (slug or "").strip()
    if provider not in {"ashby", "greenhouse", "lever", "broken", "tavily", "unknown"}:
        provider = "unknown"
    if not slug:
        raise ValueError("ATS slug is required")
    conn.execute(
        """
        INSERT INTO ats_endpoints
            (company_id, provider, slug, ats_url, status, open_jobs_actual, raw_metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, slug) DO UPDATE SET
            company_id = excluded.company_id,
            ats_url = COALESCE(NULLIF(excluded.ats_url, ''), ats_endpoints.ats_url),
            status = excluded.status,
            open_jobs_actual = COALESCE(excluded.open_jobs_actual, ats_endpoints.open_jobs_actual),
            raw_metadata_json = excluded.raw_metadata_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            company_id,
            provider,
            slug,
            ats_url,
            status,
            open_jobs_actual,
            json_dumps(raw_metadata or {}),
        ),
    )
    row = conn.execute(
        "SELECT id FROM ats_endpoints WHERE provider = ? AND slug = ?",
        (provider, slug),
    ).fetchone()
    return int(row["id"])


def ats_url(provider: str, slug: str) -> str:
    if provider == "ashby":
        return f"https://jobs.ashbyhq.com/{slug}"
    if provider == "greenhouse":
        return f"https://boards.greenhouse.io/{slug}"
    if provider == "lever":
        return f"https://jobs.lever.co/{slug}"
    return ""


def get_ats_endpoint(conn: sqlite3.Connection, provider: str, slug: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM ats_endpoints WHERE provider = ? AND slug = ?",
        ((provider or "").strip().lower(), (slug or "").strip()),
    ).fetchone()


def _http_get_json(url: str, timeout: int = 8) -> Any:
    """Pure HTTP helper: GET a URL, return parsed JSON or None on any failure."""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def detect_ats(name: str, website_url: str | None = None) -> dict | None:
    """Probe public ATS APIs to discover whether a company has a public job board.

    Returns a dict on hit:
        {
            "provider": "ashby" | "greenhouse" | "lever",
            "slug": "...",
            "total_jobs": int,
            "sample_titles": [str, ...up to 5],
            "tried_slugs": [...],
        }
    Returns None on miss.

    Pure function: no DB access, no Flask. Side effects: HTTP requests only.
    The website_url parameter is accepted but not yet used (reserved for
    upcoming improvements that derive candidates from the company URL).
    """
    name = (name or "").strip()
    if not name:
        return None
    base = re.sub(r"[^a-z0-9]", "", name.lower())
    base_hyphen = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    candidates = list(dict.fromkeys(
        [base, base_hyphen, base + "hq", "get" + base, base + "-ai", base + "so"]
    ))
    for slug in candidates:
        data = _http_get_json(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false"
        )
        if data and data.get("jobs"):
            jobs = data["jobs"]
            return {
                "provider": "ashby",
                "slug": slug,
                "total_jobs": len(jobs),
                "sample_titles": [j.get("title", "") for j in jobs[:5]],
                "tried_slugs": candidates,
            }
    for slug in candidates:
        data = _http_get_json(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
        )
        if data and data.get("jobs"):
            jobs = data["jobs"]
            return {
                "provider": "greenhouse",
                "slug": slug,
                "total_jobs": len(jobs),
                "sample_titles": [j.get("title", "") for j in jobs[:5]],
                "tried_slugs": candidates,
            }
    for slug in candidates:
        data = _http_get_json(f"https://api.lever.co/v0/postings/{slug}")
        if isinstance(data, list) and data:
            return {
                "provider": "lever",
                "slug": slug,
                "total_jobs": len(data),
                "sample_titles": [j.get("text", "") for j in data[:5]],
                "tried_slugs": candidates,
            }
    return None


def add_scan_run(
    conn: sqlite3.Connection,
    *,
    scan_date: str,
    scan_method: str,
    config_version: str,
    total_companies_scanned: int,
    total_matches: int,
    raw_metadata: dict[str, Any] | None = None,
) -> int:
    """Record a scout run. Returns the new scan_runs.id."""
    cur = conn.execute(
        """
        INSERT INTO scan_runs
            (scan_date, scan_method, config_version,
             total_companies_scanned, total_matches, raw_metadata_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            scan_date,
            scan_method,
            config_version,
            total_companies_scanned,
            total_matches,
            json_dumps(raw_metadata or {}),
        ),
    )
    return int(cur.lastrowid)


def add_dashboard_company(
    conn: sqlite3.Connection,
    *,
    name: str,
    provider: str,
    slug: str,
    stage: str = "Unknown",
    vertical: str = "SaaS",
    open_jobs_actual: int | None = None,
) -> tuple[int, int]:
    company_id = upsert_company(conn, name, stage=stage, vertical=vertical, active=True)
    add_company_source(
        conn,
        company_id,
        source_type="dashboard_manual",
        source_name="add_company",
        raw_name=name,
        raw_metadata={
            "name": name,
            "ats": provider,
            "slug": slug,
            "stage": stage,
            "vertical": vertical,
        },
    )
    endpoint_id = upsert_ats_endpoint(
        conn,
        company_id,
        provider=provider,
        slug=slug,
        ats_url=ats_url(provider, slug),
        status="active",
        open_jobs_actual=open_jobs_actual,
    )
    conn.commit()
    return company_id, endpoint_id


def deactivate_company_by_name(conn: sqlite3.Connection, name: str) -> bool:
    normalized = normalize_name(name)
    row = conn.execute("SELECT id FROM companies WHERE normalized_name = ?", (normalized,)).fetchone()
    if not row:
        return False
    company_id = int(row["id"])
    conn.execute(
        "UPDATE companies SET active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (company_id,),
    )
    conn.execute(
        "UPDATE ats_endpoints SET status = 'deleted', updated_at = CURRENT_TIMESTAMP WHERE company_id = ?",
        (company_id,),
    )
    conn.commit()
    return True


def extract_external_job_id(job: dict[str, Any]) -> str:
    source = (job.get("source") or "").lower()
    url = job.get("job_url") or job.get("apply_url") or ""
    if source == "ashby":
        match = re.search(r"/([0-9a-f]{8}-[0-9a-f-]{27,})", url, re.I)
        if match:
            return match.group(1).lower()
    if source == "greenhouse":
        match = re.search(r"(?:gh_jid=|/jobs/)(\d+)", url)
        if match:
            return match.group(1)
    if source == "lever":
        match = re.search(r"/([0-9a-f]{8}-[0-9a-f-]{27,})", url, re.I)
        if match:
            return match.group(1).lower()
    basis = "|".join(
        [
            source,
            url,
            job.get("apply_url") or "",
            normalize_name(job.get("company_name")),
            normalize_title(job.get("role_title")),
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def upsert_job_posting(
    conn: sqlite3.Connection,
    job: dict[str, Any],
    *,
    company_id: int,
    ats_endpoint_id: int | None = None,
) -> int:
    source = (job.get("source") or "unknown").lower()
    external_id = extract_external_job_id(job)
    title = job.get("role_title") or ""
    conn.execute(
        """
        INSERT INTO job_postings
            (company_id, ats_endpoint_id, source, external_job_id, job_url, apply_url,
             title, normalized_title, location_raw, remote_ok, posted_date, first_seen_at,
             last_seen_at, jd_text, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, external_job_id) DO UPDATE SET
            company_id = excluded.company_id,
            ats_endpoint_id = COALESCE(excluded.ats_endpoint_id, job_postings.ats_endpoint_id),
            job_url = COALESCE(NULLIF(excluded.job_url, ''), job_postings.job_url),
            apply_url = COALESCE(NULLIF(excluded.apply_url, ''), job_postings.apply_url),
            title = excluded.title,
            normalized_title = excluded.normalized_title,
            location_raw = excluded.location_raw,
            remote_ok = excluded.remote_ok,
            posted_date = COALESCE(NULLIF(excluded.posted_date, ''), job_postings.posted_date),
            last_seen_at = COALESCE(NULLIF(excluded.last_seen_at, ''), job_postings.last_seen_at),
            jd_text = COALESCE(NULLIF(excluded.jd_text, ''), job_postings.jd_text),
            raw_json = excluded.raw_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            company_id,
            ats_endpoint_id,
            source,
            external_id,
            job.get("job_url") or "",
            job.get("apply_url") or "",
            title,
            normalize_title(title),
            job.get("location_raw") or "",
            int(bool(job.get("remote_ok"))),
            job.get("posted_date") or "",
            job.get("date_found") or "",
            job.get("date_found") or "",
            job.get("jd_text") or "",
            json_dumps(job),
        ),
    )
    row = conn.execute(
        "SELECT id FROM job_postings WHERE source = ? AND external_job_id = ?",
        (source, external_id),
    ).fetchone()
    job_id = int(row["id"])
    for kind, url in (("job_url", job.get("job_url")), ("apply_url", job.get("apply_url"))):
        if url:
            conn.execute(
                "INSERT OR IGNORE INTO job_url_aliases (job_id, url, kind) VALUES (?, ?, ?)",
                (job_id, url, kind),
            )
    return job_id


def add_job_score(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    scorer: str,
    score: int,
    reason: str = "",
    flags: list[Any] | None = None,
    rubric_version: str = "0",
) -> None:
    conn.execute(
        """
        INSERT INTO job_scores (job_id, scorer, score, reason, flags_json, rubric_version)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id, scorer) DO UPDATE SET
            score = excluded.score,
            reason = excluded.reason,
            flags_json = excluded.flags_json,
            rubric_version = excluded.rubric_version,
            scored_at = CURRENT_TIMESTAMP
        """,
        (job_id, scorer, score, reason, json_dumps(flags or []), rubric_version),
    )


def get_job_score(
    conn: sqlite3.Connection,
    job_id: int,
    scorer: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT score, reason, flags_json, rubric_version, scored_at "
        "FROM job_scores WHERE job_id = ? AND scorer = ?",
        (job_id, scorer),
    ).fetchone()


def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Return the legacy job dictionary shape expected by matchers/dashboard."""
    try:
        raw = json.loads(row["raw_json"] or "{}")
    except Exception:
        raw = {}
    job = dict(raw)
    job["_job_id"] = row["id"]
    job["company_name"] = row["company_name"]
    job["role_title"] = row["title"]
    job["source"] = row["source"]
    job["job_url"] = row["job_url"] or row["apply_url"] or raw.get("job_url") or raw.get("apply_url") or ""
    job["apply_url"] = row["apply_url"] or row["job_url"] or raw.get("apply_url") or raw.get("job_url") or ""
    job["location_raw"] = row["location_raw"] or raw.get("location_raw", "")
    job["remote_ok"] = bool(row["remote_ok"])
    job["posted_date"] = row["posted_date"] or raw.get("posted_date", "")
    job["company_stage"] = row["stage"] or raw.get("company_stage", "Unknown")
    job["industry_vertical"] = row["vertical"] or raw.get("industry_vertical", "Unknown")
    job["jd_text"] = row["jd_text"] or raw.get("jd_text", "")
    return job


def load_jobs_for_matching(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Load active jobs from SQLite in the legacy matcher input shape."""
    rows = conn.execute(
        """
        SELECT
            j.*,
            c.canonical_name AS company_name,
            c.stage,
            c.vertical
        FROM job_postings j
        JOIN companies c ON c.id = j.company_id
        WHERE j.status = 'active'
          AND c.active = 1
        ORDER BY COALESCE(j.last_seen_at, j.first_seen_at, j.created_at) DESC, j.id DESC
        """
    ).fetchall()
    return [_job_dict(row) for row in rows]


def save_job_scores(
    conn: sqlite3.Connection,
    scored_jobs: list[dict[str, Any]],
    *,
    scorer: str = "current_shortlist",
    rubric_version: str = "0",
) -> None:
    """Persist matcher output back to job_scores using URL aliases for identity."""
    for job in scored_jobs:
        job_id = job.get("_job_id") or job_id_for_url(conn, job.get("job_url")) or job_id_for_url(conn, job.get("apply_url"))
        if job_id is None:
            continue
        score = job.get("match_score")
        if score is None:
            continue
        reason = job.get("reason") or job.get("match_reason") or ""
        flags = job.get("match_flags") or []
        rv = job.get("rubric_version") or rubric_version
        add_job_score(
            conn, job_id,
            scorer=scorer, score=int(score), reason=reason, flags=flags,
            rubric_version=rv,
        )
    conn.commit()


def export_dashboard_payload(
    conn: sqlite3.Connection,
    *,
    scorer: str = "current_shortlist",
    min_score: int = 3,
) -> dict[str, Any]:
    """Build the /api/data payload from SQLite instead of shortlist.json."""
    rows = conn.execute(
        """
        SELECT
            j.*,
            c.canonical_name AS company_name,
            c.stage,
            c.vertical,
            s.score AS match_score,
            s.reason AS match_reason,
            s.flags_json,
            s.scored_at
        FROM job_scores s
        JOIN job_postings j ON j.id = s.job_id
        JOIN companies c ON c.id = j.company_id
        WHERE s.scorer = ?
          AND s.score >= ?
          AND j.status = 'active'
          AND c.active = 1
        ORDER BY s.score DESC, COALESCE(j.posted_date, j.last_seen_at, j.created_at) DESC, j.id DESC
        """,
        (scorer, min_score),
    ).fetchall()
    jobs = []
    for row in rows:
        job = _job_dict(row)
        job["match_score"] = int(row["match_score"])
        job["reason"] = row["match_reason"] or ""
        job["match_reason"] = row["match_reason"] or ""
        try:
            job["match_flags"] = json.loads(row["flags_json"] or "[]")
        except Exception:
            job["match_flags"] = []
        jobs.append(job)

    state = export_dashboard_state(conn)
    total_scanned = conn.execute(
        """
        SELECT COUNT(*)
        FROM job_postings j
        JOIN companies c ON c.id = j.company_id
        WHERE j.status = 'active'
          AND c.active = 1
        """
    ).fetchone()[0]
    scan_row = conn.execute(
        "SELECT scan_date FROM scan_runs WHERE scan_date IS NOT NULL ORDER BY created_at DESC, id DESC LIMIT 1"
    ).fetchone()
    score_row = conn.execute(
        "SELECT MAX(scored_at) AS scored_at FROM job_scores WHERE scorer = ?",
        (scorer,),
    ).fetchone()
    scan_date = "unknown"
    if scan_row and scan_row["scan_date"]:
        scan_date = scan_row["scan_date"]
    elif score_row and score_row["scored_at"]:
        scan_date = score_row["scored_at"][:10]
    return {
        "jobs": jobs,
        "scan_date": scan_date,
        "companies": conn.execute("SELECT COUNT(*) FROM companies WHERE active = 1").fetchone()[0],
        "total_scanned": int(total_scanned),
        "total_shortlisted": len(jobs),
        "comments": state["comments"],
        "selected": state["selected"],
        "job_status": state["job_status"],
        "feedback": state["feedback"],
    }


def export_company_scan_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return per-company job/match counts from SQLite for /api/companies."""
    scan_row = conn.execute(
        "SELECT scan_date FROM scan_runs WHERE scan_date IS NOT NULL ORDER BY created_at DESC, id DESC LIMIT 1"
    ).fetchone()
    rows = conn.execute(
        """
        SELECT
            c.canonical_name AS company,
            COUNT(DISTINCT j.id) AS total_jobs,
            COUNT(DISTINCT CASE
                WHEN s.scorer = 'current_shortlist' AND s.score >= 3 THEN j.id
            END) AS matches
        FROM companies c
        LEFT JOIN job_postings j ON j.company_id = c.id AND j.status = 'active'
        LEFT JOIN job_scores s ON s.job_id = j.id
        WHERE c.active = 1
        GROUP BY c.id
        """
    ).fetchall()
    return {
        "scan_date": scan_row["scan_date"] if scan_row else None,
        "stats_by_company": {
            row["company"]: {
                "company": row["company"],
                "total_jobs": int(row["total_jobs"] or 0),
                "matches": int(row["matches"] or 0),
                "status": "scanned" if row["total_jobs"] else "no jobs",
            }
            for row in rows
        },
    }


def load_feedback_examples(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Return matcher calibration examples in legacy feedback.json shape."""
    rows = conn.execute(
        """
        SELECT
            COALESCE(j.job_url, j.apply_url, a.url) AS key_url,
            i.manual_score,
            i.manual_score_comment,
            i.updated_at,
            j.title,
            c.canonical_name AS company_name
        FROM job_interactions i
        JOIN job_postings j ON j.id = i.job_id
        JOIN companies c ON c.id = j.company_id
        LEFT JOIN job_url_aliases a ON a.job_id = j.id AND a.kind = 'job_url'
        WHERE i.manual_score IS NOT NULL
        """
    ).fetchall()
    out = {}
    for row in rows:
        key = row["key_url"]
        if not key:
            continue
        out[key] = {
            "manual_score": row["manual_score"],
            "comment": row["manual_score_comment"] or "",
            "updated": row["updated_at"],
            "role_title": row["title"],
            "company_name": row["company_name"],
        }
    return out


def job_id_for_url(conn: sqlite3.Connection, url: str | None) -> int | None:
    if not url:
        return None
    row = conn.execute("SELECT job_id FROM job_url_aliases WHERE url = ?", (url,)).fetchone()
    return int(row["job_id"]) if row else None


def update_job_interaction(
    conn: sqlite3.Connection,
    url: str,
    *,
    selected: bool | None = None,
    reviewed: bool | None = None,
    applied: bool | None = None,
    comment: str | None = None,
    tags: list[Any] | None = None,
    manual_score: int | None = None,
    manual_score_comment: str | None = None,
    clear_manual_score: bool = False,
) -> int | None:
    job_id = job_id_for_url(conn, url)
    if job_id is None:
        return None
    conn.execute(
        "INSERT OR IGNORE INTO job_interactions (job_id) VALUES (?)",
        (job_id,),
    )
    updates = []
    values: list[Any] = []
    if selected is not None:
        updates.append("selected = ?")
        values.append(int(selected))
    if reviewed is not None:
        updates.append("reviewed = ?")
        values.append(int(reviewed))
    if applied is not None:
        updates.append("applied = ?")
        values.append(int(applied))
    if comment is not None:
        updates.append("comment = ?")
        values.append(comment)
    if tags is not None:
        updates.append("tags_json = ?")
        values.append(json_dumps(tags))
    if clear_manual_score:
        updates.append("manual_score = NULL")
        updates.append("manual_score_comment = ?")
        values.append(manual_score_comment or "")
    elif manual_score is not None:
        updates.append("manual_score = ?")
        values.append(manual_score)
        updates.append("manual_score_comment = ?")
        values.append(manual_score_comment or "")
        add_job_score(
            conn,
            job_id,
            scorer="manual",
            score=manual_score,
            reason=manual_score_comment or "",
        )
    elif manual_score_comment is not None:
        updates.append("manual_score_comment = ?")
        values.append(manual_score_comment)
    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        values.append(job_id)
        conn.execute(
            "UPDATE job_interactions SET " + ", ".join(updates) + " WHERE job_id = ?",
            values,
        )
        conn.commit()
    return job_id


def export_dashboard_state(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT
            i.selected,
            i.reviewed,
            i.applied,
            i.comment,
            i.tags_json,
            i.manual_score,
            i.manual_score_comment,
            i.updated_at,
            COALESCE(j.job_url, j.apply_url, a.url) AS key_url,
            j.title,
            c.canonical_name AS company_name
        FROM job_interactions i
        JOIN job_postings j ON j.id = i.job_id
        JOIN companies c ON c.id = j.company_id
        LEFT JOIN job_url_aliases a ON a.job_id = j.id AND a.kind = 'job_url'
        """
    ).fetchall()
    comments = {}
    selected = []
    job_status = {}
    feedback = {}
    for row in rows:
        key = row["key_url"]
        if not key:
            continue
        tags = json.loads(row["tags_json"] or "[]")
        if row["comment"] or tags:
            comments[key] = {
                "text": row["comment"] or "",
                "tags": tags,
                "updated": row["updated_at"],
            }
        if row["selected"]:
            selected.append(key)
        if row["reviewed"] or row["applied"]:
            job_status[key] = {
                "reviewed": bool(row["reviewed"]),
                "applied": bool(row["applied"]),
            }
        if row["manual_score"] is not None or row["manual_score_comment"]:
            feedback[key] = {
                "manual_score": row["manual_score"],
                "comment": row["manual_score_comment"] or "",
                "updated": row["updated_at"],
                "role_title": row["title"],
                "company_name": row["company_name"],
            }
    return {
        "comments": comments,
        "selected": selected,
        "job_status": job_status,
        "feedback": feedback,
    }


def add_resume_artifact(
    conn: sqlite3.Connection,
    *,
    job_url: str,
    role_title: str,
    company_name: str,
    filename_txt: str,
    tailored_date: str,
    filename_pdf: str | None = None,
    raw_metadata: dict[str, Any] | None = None,
) -> int:
    job_id = job_id_for_url(conn, job_url)
    company_id = upsert_company(conn, company_name) if company_name else None
    if filename_pdf is None and filename_txt.endswith(".txt"):
        filename_pdf = filename_txt[:-4] + ".pdf"
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
            role_title,
            filename_txt,
            filename_pdf,
            tailored_date,
            job_url,
            json_dumps(raw_metadata or {}),
        ),
    )
    conn.commit()
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def export_tailored_resumes(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            r.source_job_url,
            r.role_title,
            COALESCE(c.canonical_name, '') AS company_name,
            r.filename_txt,
            r.tailored_date,
            r.created_at
        FROM resume_artifacts r
        LEFT JOIN companies c ON c.id = r.company_id
        ORDER BY r.created_at
        """
    ).fetchall()
    out = []
    seen = set()
    for row in rows:
        key = (row["source_job_url"], row["filename_txt"])
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "job_url": row["source_job_url"] or "",
                "role_title": row["role_title"] or "",
                "company_name": row["company_name"] or "",
                "tailored_file": row["filename_txt"],
                "tailored_date": row["tailored_date"] or "",
            }
        )
    return out


def load_scout_companies(conn: sqlite3.Connection) -> list[dict[str, str]]:
    """Return company dictionaries compatible with ats_scout.py."""
    rows = conn.execute(
        """
        SELECT
            c.canonical_name AS name,
            e.provider AS ats,
            e.slug AS slug,
            COALESCE(c.stage, 'Unknown') AS stage,
            COALESCE(c.vertical, 'SaaS') AS vertical
        FROM ats_endpoints e
        JOIN companies c ON c.id = e.company_id
        WHERE e.provider IN ('ashby', 'greenhouse', 'lever', 'broken', 'tavily')
          AND e.status IN ('active', 'skipped')
          AND (
              c.active = 1
              OR EXISTS (
                  SELECT 1
                  FROM company_sources s
                  WHERE s.company_id = c.id
                    AND s.source_type = 'ats_scout'
              )
          )
        ORDER BY c.canonical_name COLLATE NOCASE, e.provider, e.slug
        """
    ).fetchall()
    companies = []
    seen = set()
    for row in rows:
        key = (row["ats"], row["slug"].lower())
        if key in seen:
            continue
        seen.add(key)
        companies.append(
            {
                "name": row["name"],
                "ats": row["ats"],
                "slug": row["slug"],
                "stage": row["stage"] or "Unknown",
                "vertical": row["vertical"] or "SaaS",
            }
        )
    return companies
