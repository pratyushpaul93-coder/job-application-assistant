# Definitions

Glossary of pipeline-specific concepts that don't have an obvious home in the
schema, scraper, or contracts docs. Add an entry here when a term needs to be
referenced from code or backlog without re-explaining it each time.

## Logging concepts

### Error taxonomy aggregation

A run-end summary block that buckets every individual fetch / probe / API
failure into a small set of labeled categories, with counts per category, so a
human (or future Claude) can read the run's failure pattern at a glance instead
of grepping through raw exception strings.

Standard buckets used in `tools/phase2_unknown_audit.py` and any future probing
script:

- `dns_nxdomain` — hostname doesn't resolve. Almost always a defunct company or
  a stored-URL data error. Action: candidate for retirement (see Phase 0B).
- `timeout` — DNS resolved but the HTTP request exceeded `HTTP_TIMEOUT`
  (currently 8s). Often a slow international site or a server that refuses to
  serve our user agent. Retry-worthy.
- `http_403` / `http_4xx` — server actively refused. Usually a bot block
  (Cloudflare, Akamai). Action: try a different UA or move the company to a
  manual-review list.
- `http_404` — page doesn't exist. Often means the careers path we guessed is
  wrong. Action: try other paths or scrape the homepage for the real link.
- `http_5xx` — server error. Transient; retry on a future run.
- `decode_error` — body returned but couldn't be parsed as UTF-8.
  Rare; usually a binary blob mis-served as HTML.
- `other` — anything that doesn't match the above. If `other` is non-trivial,
  the taxonomy needs expansion.

The aggregation is *additive to*, not a *replacement for*, the per-line error
log: keep the raw error file for grep-level forensics, and use the aggregation
for shape-of-the-problem reasoning.

### "Missed by discover" flag

A row-level flag set during research / audit probing (e.g., Phase 2) when the
probe finds a known ATS-provider pattern (Greenhouse, Ashby, Lever, Workday,
etc.) on the careers page of a company currently recorded as
`provider='unknown', status='not_found'` in `ats_endpoints`.

This is a separate signal from the standard probe categories because it
identifies a *detector failure*, not a company-side problem: the company has a
detectable ATS, but `discover_phase()` didn't find it. Causes are usually
narrow and fixable:

- **Regex variant not in `_ATS_SIGNATURES`** — e.g., the
  `boards.greenhouse.io/embed/job_board/js?for=...` form, which the current
  regex misses (see backlog Tier 2 #4 / Phase 1 work).
- **Slug-candidate generator gap** — the ATS exists, the regex would match,
  but `discover_phase` never tried the right slug because the company's
  canonical name doesn't normalize to it (e.g., LightForce → slug
  `lightforceorthodontics`).
- **JS-rendered page** — the static HTML the probe fetches doesn't contain the
  ATS pattern, but a deeper fetch (with the right path or referer) does.
- **Body cap truncation** — historical: `_http_get_text` capped page bodies
  at 300KB; large careers pages (Blue Apron, BigCommerce, ServiceTitan)
  hid Workday URLs past the 350K-577K byte mark. Cap raised to 2MB
  on 2026-05-08; this failure mode should no longer occur.

Counting these separately from the broader `static_in_house` / `js_rendered_spa`
buckets gives a clean answer to *"how many companies could be detected with
zero new provider support, just by fixing existing detectors?"* That number
should drop after each detector improvement; if it stays flat, the
improvement didn't address the actual miss pattern.

## Date / freshness conventions

### `posted_date`

Stored on `job_postings.posted_date` as `YYYY-MM-DD` text. Source:

- **Ashby** — `j['publishedAt']` (ISO date)
- **Greenhouse** — `j['updated_at']` then `j['first_published']` (ISO)
- **Lever** — `j['createdAt']` (millisecond Unix timestamp, converted)
- **Workday** — *approximate*, derived from the relative `postedOn` string
  (`"Posted Today"` → today; `"Posted N Days Ago"` → today − N;
  `"Posted N+ Days Ago"` → today − N as a lower-bound). Accurate to ~1
  day for jobs ≤14 days old; less precise for older jobs (which are
  filtered out before scoring anyway).

Convention: **jobs with no parseable date are kept**, not dropped. The
recency filter only excludes jobs we are confident are stale.

### `days_ago`

Always **recompute live** from `posted_date` at read time
(`storage._compute_days_ago`). Never trust the value frozen in
`raw_json` — that snapshot reflects scout-time freshness, which decays
each day.

### `max_job_age_days`

Configured in `scout_config.json` under `scout_settings`. Default 14.
Applied at the fetcher level (before evaluate_role / JD fetch / DeepSeek
scoring) so stale jobs never enter the scoring pipeline. For Workday,
applied in stage 2 (pre-JD-fetch) to also save the per-job detail
fetch.
