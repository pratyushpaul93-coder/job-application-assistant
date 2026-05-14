# Data Contracts

`workspace/jobapp.db` is the single source of truth for the job-application
pipeline. Scout, Matcher, Tailor, and the Dashboard all read and write to it
directly. JSON exports still exist on disk as backup/debug artifacts, but
nothing in the live pipeline reads from them.

## Sources of Truth

### Companies and ATS endpoints

- `companies` — one canonical row per company.
  Unique key: `normalized_name`.
- `company_sources` — provenance rows (where each company was first seen).
  Lets a company appear in many VC lists without becoming many companies.
- `ats_endpoints` — one row per scannable ATS board.
  Unique key: `(provider, slug)`.

Seed inputs that bootstrap these tables (one-shot, via
`scripts/migrate_to_db.py`):

- `scripts/companies_master.txt`, `scripts/a16z_companies.txt` — name lists.
- `workspace/all_vc_companies.csv` — Getro VC scrape output.
- `workspace/ats_mapping_779.csv` — ranked Getro→ATS mapping.
- `scripts/bulk_add_results.csv` — checkpoint from the dashboard's bulk
  ATS-detection flow.

After bootstrap, mutations come through the dashboard's add/delete endpoints,
which write directly to `companies` / `ats_endpoints`. The hardcoded
`COMPANIES` list in `ats_scout.py` is retained only as a last-resort fallback
when the DB is unreachable; Scout always reads from SQLite under normal operation.

### Jobs

- `job_postings` — one row per job posting.
  Unique key: `(source, external_job_id)`. `external_job_id` is extracted
  from ATS URLs when possible, otherwise derived from a stable hash.
- `job_url_aliases` — maps every observed `job_url` / `apply_url` to the
  canonical `job_id`. Lets historical URL-keyed state (and future URL
  variants from the same ATS) resolve to the same posting.
- `scan_runs` — one row per Scout invocation, with date, config version,
  total companies scanned, total matches, and per-company stats in
  `raw_metadata_json`.

Scout writes directly to `job_postings` and `scan_runs` as it scans.
`workspace/raw_jobs.json` is also written on every run as a
backup/debug artifact (top-level `_note` field marks it as such), but
nothing reads it during normal operation.

### Scores

- `job_scores` — one row per `(job_id, scorer)`. Carries:
  - `score` (1–5)
  - `reason` (free text)
  - `flags_json` (matcher-emitted flags)
  - `rubric_version` — used by the matcher's incremental cache to decide
    whether a stored score is still valid against the current rubric

Scorer values currently in use:

- `current_shortlist` — written by `ats_matcher.py`. Dashboard reads this.
- `manual` — written when the user enters a manual fit score in the
  dashboard.

The matcher also writes `workspace/shortlist.json` on every run as a
backup/debug artifact. Its content is queried fresh from `job_scores`,
so a partial / interrupted run cannot truncate the file.

### Dashboard / user state

- `job_interactions` — keyed by `job_id`. Stores `selected`, `reviewed`,
  `applied`, `reached_out` (added 2026-05-12), `no_outreach` (added
  2026-05-14), `comment`, `tags_json`, `manual_score`, and
  `manual_score_comment`. Row-level `updated_at` refreshes on every write
  via `storage.update_job_interaction`. `reviewed` and `applied` are
  mutually exclusive end states; `reached_out` and `no_outreach` are
  sub-states of `applied` and mutually exclusive with each other.
- `resume_artifacts` — tailored resume metadata, linked to a job and
  company where possible. Stores `.txt` and expected `.pdf` filenames.

#### Dashboard `/api/data` payload — `job_status` shape

```json
"job_status": {
  "<url>": {
    "reviewed":    false,
    "applied":     true,
    "reached_out": false,
    "no_outreach": false,
    "updated_at":  "2026-05-12 02:33:22"
  }
}
```

The map is keyed by the job's canonical `apply_url` / `job_url` (resolved
through `job_url_aliases`). Entries only appear for rows where at least one
of `reviewed`, `applied`, `reached_out`, or `no_outreach` is true.
`updated_at` is the row's last-modified timestamp and is the sort key for
the dashboard's "To reach out" column. The dashboard's `/api/job_status`
POST endpoint accepts `field ∈ {reviewed, applied, reached_out,
no_outreach}` and `value` boolean.

#### Tailored resume snapshot refresh (added 2026-05-12)

`scripts/dashboard.py` keeps two .txt filenames per tailored resume:

- **Canonical** `<YYYY-MM-DD>_<slug>.txt` — what `tailor.py` writes; the
  source of truth. Registered in `resume_artifacts.filename_txt`.
- **Standardized** `PPaul_<YYYYMMDD>_<company>_<role>.txt` — derived
  display/download name, created by `/api/generate_pdf` and refreshed by
  every subsequent `/api/tailor`, `/api/tailor_manual`, or `/api/revise`
  via `_refresh_standardized_snapshot(...)`. The Download button points at
  the standardized .pdf; the helper rebuilds both the .txt copy and the
  .pdf from the canonical .txt on each post-write trigger so the download
  is never stale.

Legacy JSON files (`feedback.json`, `selected.json`, `job_status.json`,
`tailored_resumes.json`) are no longer read or written by the live pipeline.
They have been moved to `workspace/archive/json_legacy/` as a frozen
snapshot of the pre-migration state.

#### Outreach: research / compose split (added 2026-05-14)

Outreach generation is two API steps so the (input-token-heavy) research
call and the compose calls don't collide with Anthropic's per-minute rate
limit:

- `POST /api/outreach/research` — `{job_id, peek?, force_refresh?}`.
  `peek:true` is a side-effect-free cache probe (`peek_research()`);
  default runs/uses `outreach_research_cache` (30-day TTL); `force_refresh`
  bypasses it. Research per company is paid once.
- `POST /api/outreach/draft` — composes variants from cached research
  (still researches if none cached, for backward compat). Compose calls
  run **serially**, not in a thread pool.
- `POST /api/outreach/recompose` — `{draft_id, slant}`. Recomposes a single
  existing draft in place: preserves `id` + `variant_group_id`, resets
  `original_body` / `edited` / `edit_count`. Used by "Regen alt slant" so
  the sibling variant is untouched.

## Identity Rules

### Company identity

`companies.normalized_name` is unique. A company can have many rows in
`company_sources` (one per place it was discovered) and one or more rows
in `ats_endpoints` (typically one, but a company that migrated ATS would
have two).

### Job identity

Primary key for matching is `(source, external_job_id)`. This is stable
across re-scans and across `job_url` ↔ `apply_url` divergence.

For incoming URL-keyed state (historical files, dashboard clicks),
resolution goes through `job_url_aliases`, which carries every observed
URL variant for a given `job_id`.

## Failure modes

The pipeline is SQLite-native. Components fail loudly when the DB is
missing rather than silently falling back to JSON:

- **Dashboard** — `_require_db()` aborts the request with HTTP 500 and a
  clear message pointing at `scripts/migrate_to_db.py --reset`.
- **Matcher** — falls back to `raw_jobs.json` for the input read only if
  `jobapp.db` is missing entirely. Score writes target SQLite first.
- **Scout** — falls back to the hardcoded `COMPANIES` list if the DB is
  unreachable; the JSON write happens regardless.

## Pipeline flow (live)

```
ats_scout.py    → companies/ats_endpoints (read)
                → job_postings, scan_runs (write, direct)
                → raw_jobs.json (backup export)

ats_matcher.py  → job_postings, job_interactions (read)
                → job_scores (write, scorer='current_shortlist',
                              with rubric_version for incremental cache)
                → shortlist.json (backup export)

dashboard.py    → all SQLite reads/writes
                → scan_status.json, tailor_status.json (transient IPC only)

tailor.py       → resume_artifacts (write)
                → resumes/tailored/*.txt + *.pdf

migrate_to_db.py → one-shot bootstrap from seed files / legacy backups.
                  Not part of the run-time flow anymore.
```

## Environment overrides

- `PP_JOBAPP_COMPANY_SOURCE=legacy` — force Scout to read companies from
  the hardcoded list (for debugging when the DB is suspected of having
  bad data).
- `PP_JOBAPP_COMPANY_SOURCE=db` — require Scout to read from the DB; if
  the DB is missing it still falls back, but with a warning.
- `PP_JOBAPP_ENABLE_BASH_API=1` — enable the dashboard's local
  `/api/bash` debugging endpoint (localhost-only, off by default).
