# SQLite Schema

`workspace/jobapp.db` is the canonical store for company, ATS, job, score,
dashboard, and resume state. Scout, Matcher, Tailor, and the Dashboard all
read and write here directly; JSON exports are backup-only.

## Tables

### `companies`

One canonical row per company.

- `canonical_name` — display name.
- `normalized_name` — duplicate-prevention key, unique.
- `website_url`, `stage`, `vertical`, `headcount_range` — company metadata.
- `ticker`, `hq_city`, `hq_state`, `employee_count`, `company_type` —
  cross-source attributes populated by external ingests (Fortune 1000,
  Built In, etc.). Nullable. `upsert_company` uses COALESCE — the first
  non-null source wins; later sources do not clobber existing values.
- `active` — whether Scout should scan this company.

### `company_sources`

One row per place a company was discovered. Examples: `ats_scout`,
`name_list`, `getro_vc`, `ats_mapping`, `bulk_add_checkpoint`,
`dashboard_manual`, `fortune_1000`, `builtin_bptw`. Lets a company appear
in many VC lists / award lists without becoming many companies.

Two write patterns coexist:

- **One row per (company, list)** — default. `storage.add_company_source`
  uses `INSERT OR IGNORE` on UNIQUE `(company_id, source_type, source_name,
  raw_name)`. Used by `ats_scout`, `getro_vc`, `fortune_1000` (each company
  appears once per source).
- **One row per company, metadata accumulates** —
  `storage.upsert_company_source_metadata` does `UPDATE … SET raw_metadata_json`
  with list-merge semantics on declared `merge_keys`. Used by `builtin_bptw`
  where a single company can be on 30+ different award lists; each list
  membership goes into the `lists` array of one shared row.

See [Ingestion architecture](#ingestion-architecture) below for how new
external sources plug into this.

### `ats_endpoints`

One row per ATS endpoint.

- `provider` — scannable: `ashby`, `greenhouse`, `lever`, `workday`. Also
  detectable-but-not-scannable: `workable`, `smartrecruiters`, `bamboohr`,
  `personio`, `recruitee`, `jazzhr`, `teamtailor`, `comeet`. Enterprise
  detectable-but-not-scannable (added 2026-05-13 to cover the Fortune long
  tail): `eightfold`, `avature`, `brassring`, `icims`, `phenom`, `taleo`,
  `oraclehcm`. Plus placeholder slots: `broken`, `tavily`, `unknown`.
- `slug` — ATS board slug. For Ashby/Greenhouse/Lever this is the simple
  one-word identifier (e.g. `stripe`). For Workday it's the compound
  form `tenant:dc:site` (e.g. `sailpoint:wd1:SailPoint`) — the dc
  segment isn't derivable, so it's encoded into the slug to keep
  `ats_url(provider, slug)` round-trippable. Other compound-slug
  providers added 2026-05-13: **Brassring** uses `partnerid:siteid`
  (e.g. `26336:5014`), **Oracle HCM** uses `tenant:region:siteNumber`
  (e.g. `eqnt:us2:CX_45001`). For Eightfold/Avature/iCIMS/Phenom/Taleo
  the slug is the subdomain (e.g. `walmart` for `walmart.eightfold.ai`).
- Unique key: `(provider, slug)`.
- `status` — `active`, `failed`, `skipped`, `deleted`, `not_found`.

### `scan_runs`

One row per Scout invocation. Stores `scan_date`, `scan_method`,
`config_version`, `total_companies_scanned`, `total_matches`, and
per-company stats / errors in `raw_metadata_json`. Written by Scout
itself via `storage.add_scan_run`.

### `job_postings`

One canonical row per job posting.

- Unique key: `(source, external_job_id)`.
- `external_job_id` is extracted from ATS URLs when possible, otherwise
  derived from a stable hash.
- Stores normalized title, URLs, location, dates, JD text, and the raw
  ATS payload in `raw_json`.

### `job_url_aliases`

Maps every observed `job_url` / `apply_url` to the canonical `job_id`.
Lets historical URL-keyed dashboard state and future URL variants from
the same ATS resolve to the same posting.

### `job_scores`

One row per `(job_id, scorer)`. Carries:

- `score` (1–5)
- `reason` (free text)
- `flags_json` (matcher-emitted flags)
- `rubric_version` (e.g. `"2.2"`) — used by the matcher's incremental
  cache to decide whether a stored score is still valid against the
  current rubric. Defaults to `"0"` for legacy/imported scores so the
  next matcher run will re-score them under the current rubric.

Scorer values currently in use:

- `current_shortlist` — `ats_matcher.py` writes here. The dashboard
  reads this scorer for its main job view.
- `manual` — user-entered scores from the dashboard's fit-rating UI.

### `job_interactions`

Dashboard / user state for a job, keyed by `job_id`:

- `selected`, `reviewed`, `applied`, `reached_out`, `no_outreach`
- `comment`, `tags_json`
- `manual_score`, `manual_score_comment`
- `updated_at` — row-level timestamp, refreshed on every UPDATE inside
  `storage.update_job_interaction`. Drives the dashboard "To reach out"
  column sort (most-recently-touched first).

`reviewed` and `applied` are treated as **mutually exclusive end states** in
the dashboard UI (added 2026-05-12): the card render hides the inactive
Mark X button once one is set. `reached_out` and `no_outreach` are both
sub-states of `applied` (buttons only surface on applied cards) and are
**mutually exclusive with each other** — setting one clears the other (the
UI click handlers issue the clearing write; the storage layer does not
enforce it). All status columns are plain `INTEGER NOT NULL DEFAULT 0`;
legacy rows with conflicting flags remain valid (the UI resolves precedence:
applied dominates reviewed; reached_out / no_outreach are the terminal
states of the applied track).

Migrations via `_ensure_columns(conn)` (applied on the next
`storage.connect`): `reached_out` added 2026-05-12, `no_outreach` added
2026-05-14.

### `resume_artifacts`

Tailored resume outputs linked to a job and company where possible.
Stores `.txt` and expected `.pdf` filenames plus source job URL.

### `workday_job_jds`

Per-job JD cache for Workday postings. Workday's listing endpoint
returns title-only — full JDs require a per-job detail fetch — so
Scout caches them here so repeated scans don't re-fetch.

- `apply_url` (PK) — the canonical apply URL for a single Workday job.
- `jd_text` — extracted plain-text JD body.
- `fetched_at` — populated on insert/update; entries older than 30 days
  are treated as cache misses and re-fetched on the next scan.

Created lazily via `_ensure_columns(conn)` so existing DBs migrate on
the next `storage.connect`.

### `outreach_drafts`

Generated outreach messages, multi-variant since 2026-05-13.

- `id` (PK), `job_id` (FK → `job_postings.id`).
- `subject`, `body` — current state (may be user-edited).
- `original_body` — frozen snapshot at generation time. Powers the
  patterns view's diff (BACKLOG 2b).
- `reasoning_json` — `{blocks_chosen, why_angle, sources, sources_used, edit_suggestions, usage}` blob from the composer.
- `model` — the Anthropic model ID used to compose this variant.
- `word_count` — body word count at generation.
- `status` — `draft` or `sent`. `sent_at` set when transitioning.
- `edited`, `edit_count` — incremented on each save through `/api/outreach/update`.
- `variant_group_id` — UUID shared by sibling variants from one
  generate-click. Legacy single-draft attempts (pre-2026-05-13) have
  NULL here.
- `slant` — `operator`, `builder`, `analyst`, `tight`, or `warm`. See
  `outreach/kit.yaml` for definitions.
- `is_winner` — 0/1, exclusive within a `variant_group_id` (UPDATE
  clears siblings).
- `outcome` — `response` or `no_response`, set after a winner is marked
  sent. `outcome_at`, `outcome_notes` accompany.
- `cost_usd` — actual cost of this variant's compose call, computed
  from Anthropic `usage` after each call. Sums into the daily budget gate.

Indexed on `job_id`, `variant_group_id`, `outcome`.

### `outreach_research_cache`

Per-company research synthesis, cached 30 days. Web_search is the
dominant cost in the outreach pipeline — caching this means all variants
generated for the same company within 30 days reuse one research call.

- `company_id` (PK, FK → `companies.id`).
- `research_json` — structured `{thesis_one_liner, moat_or_wedge,
  specific_facts[], recent_signals[], what_to_skip[]}` from the Sonnet
  + web_search call.
- `sources_json` — citation list `[{url, title, cited_text}]` auto-extracted
  from the response's `citations` blocks.
- `model` — model ID that produced this entry.
- `cost_usd` — actual research-call cost from `usage`.
- `search_count` — number of web_search calls actually made (Anthropic
  `server_tool_use.web_search_requests`).
- `fetched_at` — TTL boundary. Reads older than 30 days trigger a refresh.

Created lazily via `_ensure_columns(conn)`.

## Validation Rules

`scripts/migrate_to_db.py` validates on every bootstrap run:

- DB company count is at least the hardcoded `COMPANIES` count.
- DB job count is at least `raw_jobs.json` job count.
- Unique normalized company names.
- Unique ATS provider/slug pairs.
- Unique `(source, external_job_id)` job IDs.

Run:

```bash
python3 scripts/migrate_to_db.py --reset
python3 tests/smoke_test.py
```

## New Scrapers

New scrapers should write to SQLite via `scripts/storage.py`. Avoid
creating long-lived JSON registries — backup-only exports are fine,
but the DB must be the canonical writer.

- Company / list scraper results → `companies` and `company_sources`
- ATS detector results → `ats_endpoints`
- Job results → `job_postings` (and `job_url_aliases` automatically via
  `upsert_job_posting`)
- Scoring results → `job_scores`
- Scout-style runs → `scan_runs` via `storage.add_scan_run`

See `docs/scraper-integration.md` for concrete code patterns.

## Ingestion architecture

External company lists (Fortune 1000, Built In Best Places to Work, etc.)
land via a thin convention rather than a framework. ~1-2 sources/week.

**Convention** — one script per source at `scripts/ingest/<source_slug>.py`:

```
acquire() → land raw file in workspace/data/external/<slug>/<YYYY-MM-DD>/
parse()   → yield CompanyRecord stream from the raw file
main()    → calls ingest_companies(parse(), source_type=..., source_name=...)
```

**Shared helper** — `scripts/ingest/common.py` provides:

- `CompanyRecord` dataclass — canonical row shape across sources. Required:
  `canonical_name`. Optional: `website_url`, `ticker`, `hq_city`, `hq_state`,
  `employee_count`, `company_type`, `stage`, `vertical`, `headcount_range`,
  `source_rank`, `raw_name`, `raw_metadata` (dict for source-specific fields).
- `ingest_companies(records, source_type, source_name, merge_keys=(),
  one_row_per_company=False, dry_run=False)` — for each record: match against
  existing companies (by `normalized_name`, falling back to exact-host website
  comparison), `upsert_company`, then either `add_company_source` (default) or
  `upsert_company_source_metadata` (when `one_row_per_company=True`). Returns
  `{created, matched, source_rows_added, source_rows_updated, skipped, errors}`.

**Adding a new source** — write the parser, choose `one_row_per_company` based
on whether a company can appear multiple times in the source (lists, awards,
etc.). Source-specific fields go in `raw_metadata`; only promote to a
companies-master column if the field is genuinely cross-source useful.

Active sources:

- `fortune_1000` / `2024` — Kaggle dataset `jeannicolasduval/2024-fortune-1000-companies`. 1,000 rows.
- `builtin_bptw` / `2025` — 64 lists across 16 geos × 4 size segments; 2,092 unique companies, 5,022 list memberships.
