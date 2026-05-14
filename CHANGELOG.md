# Changelog

Curated record of meaningful system changes. For mechanical commit history,
see `git log`.

An entry belongs here if a future contributor (human or AI agent) would
benefit from knowing about it weeks or months later — refactors, migrations,
data operations, architectural decisions. Bug fixes and small features stay
in git log only.

Reverse-chronological. Most recent first.

---

## 2026-05-14 — Outreach refinements, `no_outreach` status, matcher reason-preservation

A session of dashboard-workflow polish on top of the 2026-05-13 outreach
rebuild, plus one matcher correctness fix.

### Outreach: split research / compose into two clicks

The old `/api/outreach/draft` did research-then-compose in one call. Problem:
a fresh research call burns ~40-50K input tokens (web_search `tool_result`
blocks inflate input across rounds), which alone exceeds the org's 30K
input-tokens/min rate limit — so the compose calls immediately after it
got 429'd ("research succeeded, spent $0.19, no variants generated").

Fix — research is now its own step:
- New `POST /api/outreach/research` — `{peek:true}` does a cache-only probe
  (no API call, returns metadata or `{cached:false}`); default runs
  `get_or_research_company`; `{force_refresh:true}` bypasses cache.
- New `peek_research(company_id)` helper in `drafter.py` — side-effect-free
  cache read with age-in-days.
- Modal toolbar split into **Research company** + **Generate variants**
  (the latter disabled until research exists in cache). A status line shows
  cached / fresh / never-run state. On a fresh research run the UI warns to
  wait ~60s before composing so the per-minute window clears.
- Net effect: the user-driven pause between the two clicks lets the rate
  limit reset; and on a cache hit, compose carries no research-input weight
  at all.

### Outreach: compose serialized (was parallel)

`generate_variants` previously composed its 2 variants in a
`ThreadPoolExecutor`. Two ~15K-input-token calls firing concurrently
collided with the same 30K/min cap. Now serial — `ThreadPoolExecutor`
import removed, plain `for slant in slants` loop. ~15-25s slower per
2-variant generate, but each call gets the full per-minute headroom.
Research is still done once and shared into both composes (unchanged).

### Outreach: single-variant recompose

"Regen alt slant" used to regenerate **both** variants (it called
`runGenerate([keepSlant, pick])`, spawning a whole new variant group).
Now it recomposes only the clicked card:
- New `recompose_variant(draft_id, slant, model)` in `drafter.py` — loads
  the existing row, pulls research from cache, composes once, `UPDATE`s the
  row in place (preserves `id` + `variant_group_id`; resets `original_body`,
  `edited`, `edit_count`).
- New `POST /api/outreach/recompose`.
- Frontend merges the response into the existing variant object; the
  sibling card is never touched.

### Outreach: word-count hard cap + em-dash ban

- Compose system prompt (`drafter.py`) now states a numeric **145-word hard
  cap** for the body with "count your words; if at 140, stop and trim" —
  the prior "hard ceiling word_target + 10" guidance was too soft and
  drafts were landing >150 words.
- `kit.yaml` voice rule changed from "em-dashes sparingly, 2/draft ceiling"
  to "ASCII punctuation ONLY — never em-dash/en-dash" (mirrors the
  `tailor.py` rule added 2026-05-12).
- Removed the per-variant "Copy body" / "Copy subject" buttons from the
  modal — redundant with the editable fields.

### `no_outreach` — third end-state on applied jobs

New `job_interactions.no_outreach` column (migrated via `_ensure_columns`).
"Mark no outreach" button on applied cards, for jobs you applied to but
won't pursue outreach on. `no_outreach` and `reached_out` are mutually
exclusive — the click handlers clear the other (client + DB write).
`/api/job_status` field whitelist now `{reviewed, applied, reached_out,
no_outreach}`. The `job_status` payload entry gained `no_outreach: bool`.

### Jobs tab — "To reach out" section reworked

`reached_out` cards are no longer hidden from the workflow. The right
column's per-section filter is now `Applied │ Reached out · No outreach ·
Reviewed` (a visual divider + small "end state" label separate the active
queue from the three terminal states). Every acted-on card is reachable
through exactly one pill, so the old "All" pill was dropped. The "To reach
out" header count always shows the **Applied bucket** size (`applied &&
!reached_out && !no_outreach`), independent of the active pill.

A "Reached out" counter was added to the stats bar (5th tile). An earlier
iteration of this work added a clickable modal listing reached-out jobs;
it was removed once `reached_out` cards became visible via the filter pill
(the modal was redundant) — the tile is now a plain counter.

### Matcher Stage 0 — preserve match reason on manual override

`ats_matcher.py` Stage 0 (manual override) used to overwrite
`current_shortlist.reason` with `[Manual] <comment>`, so the dashboard card
stopped showing *why* the job matched once you set a manual fit score. Now
Stage 0 keeps the manual **score** winning but preserves the original
DeepSeek/prefilter **reason** from the prior score row (falls back to
`[Manual]` only when the job was never matcher-scored before). The manual
score still surfaces separately as the "Mine: N/5" badge.

Caveat: jobs whose reason was *already* clobbered to `[Manual]` in a prior
scan can't be auto-recovered — Stage 0 still short-circuits before DeepSeek
for manually-scored jobs. Recovery path is manual: clear the fit score →
Run Scan → re-add the score.

---

## 2026-05-13 — Outreach drafter: 2-variant generation, slants, research cache, budget gate

Outreach feature went from a single-shot ~250-word generator to a multi-variant
A/B-testable system in one session. Three structural changes drove it:

1. **Split the pipeline** into `research(company)` and `compose(slant, …)`
   — research is expensive (web_search-dominant), compose is cheap. Cache
   research per company for 30 days.
2. **Named slants** — five voice/structure presets (Operator, Builder,
   Analyst, Tight, Warm) the orchestrator picks 2 of, based on role+company
   signals. User picks a winner; UI captures response/no-response outcome.
3. **Edit + outcome capture** as feedback infrastructure — `original_body` is
   frozen at gen time so diffs are computable; `outreach_priors.txt` (written
   later by the patterns view) flows back into the system prompt as
   Bayesian-style guidance.

### Schema (`storage.py`)

`outreach_drafts` gained columns (idempotent migration in `_ensure_columns`):
`variant_group_id`, `slant`, `is_winner`, `outcome` (`response`/`no_response`),
`outcome_at`, `outcome_notes`, `original_body`, `edit_count`, `cost_usd`.

New table `outreach_research_cache` keyed by `company_id` — `research_json`
(structured: thesis/moat/specific_facts/recent_signals/what_to_skip),
`sources_json` (citations), `cost_usd`, `search_count`, `fetched_at`.
TTL enforced at read time (30 days).

### Budget gate (`outreach/budget.py`)

After the 2026-05-04 $13 web-search incident ([[feedback-llm-search-cost]]),
every outreach API call passes through `budget.check(estimated_usd)` which
sums today's drafts + cache spend and refuses calls past `OUTREACH_DAILY_CAP_USD`
(default $5). `compute_actual_cost()` reads back from Anthropic's `usage`
object after each call for ground-truth cost tracking.

### Drafter (`outreach/drafter.py`)

`generate_variants(job_id, slants=auto)`:
- Calls `get_or_research_company` (hits cache or runs Sonnet+web_search,
  4 searches max, returns structured JSON the composer can ground claims in).
- Composes 2 variants in parallel `ThreadPoolExecutor` — independent Sonnet
  calls, no web_search. Saves each to `outreach_drafts` sharing a
  `variant_group_id` UUID.
- Auto-slant selection heuristic: AI-vertical hints → Builder; marketplace/
  partnership hints → Operator; strategy hints → Analyst; Tight always
  available as the foil. Default pair: Builder + Tight.
- Reads `workspace/outreach_priors.txt` if present and injects into system
  prompt verbatim (feedback hook for future patterns generator).

### Kit (`outreach/kit.yaml`)

Reworked from "use exact block phrasing" to "blocks are guideposts, paraphrase
to hit word count." Five named slants encode lead_identity + blocks_preferred
+ why_structure + word_target. New voice rules: Biz Ops abbreviation in body+
subject (preserves "Senior Business Operations Manager" verbatim in role
references); one genuine exclamation allowed outside P.S. (e.g. "(congrats
on the Series D!)"); 220-260 word target replaced with per-slant targets
(105-125 words).

### Routes (`dashboard.py`)

Eight outreach endpoints:
`POST /api/outreach/draft` (now returns `{variant_group_id, slants,
research_from_cache, drafts: [...], research_cost_usd, compose_cost_usd}`);
`GET /api/outreach/{drafts,counts,slants}`; `POST /api/outreach/{update,
pick_winner,outcome,delete}`. `BudgetExceeded` returns HTTP 429 with
`kind: budget_exceeded` so the UI can surface the cap-hit clearly.

### Modal UI (`dashboard_ui.html`)

Two stacked variant cards per generation. Each card: slant badge, editable
subject+body, dirty-state tracking (yellow border + Save button), per-card
Copy/Save/Pick winner/Regen-alt slant/Delete. Top-bar Generate variants
(uses model dropdown — Sonnet default, Opus override), Mark winner sent.
Outcome banner appears once a winner is sent: "Got a response" / "No response"
two-button capture.

All inline `onclick` handlers replaced with `data-or="…"` event delegation
on `#or-modal`, per project convention. "Past attempts" history groups by
`variant_group_id`; legacy single-draft attempts are folded in as
`legacy-<id>` pseudo-groups.

### Honest status surfacing

Initial implementation said "Done in 2 variants" regardless of actual
outcome. Fixed: orchestrator returns `{slant, error}` for failures;
frontend counts successes vs failures and shows toast with per-slant
error reasons. Server-side `logging.error` captures stack traces in
journald for the next failure (compose failures had been silent — research
spent ~$0.23 then no drafts saved on the first Socure StratOps generate).

### Costs (Sonnet 4.6)

- Research (cache miss, ~4 searches): ~$0.17-0.23 depending on search result
  size — higher than my initial $0.06 estimate because tool_result blocks
  inflate input tokens across rounds.
- Compose per variant (cache hit, no search): ~$0.02-0.03.
- Typical full first-draft for a new company: ~$0.20-0.30.
- Subsequent drafts (cache hit, 2 variants): ~$0.05.

Daily cap $5 covers 15-20 first-drafts before triggering.

## 2026-05-12 — Dashboard visual overhaul + reached_out state + tailor snapshot refresh

Three independent changes, all in the user-facing dashboard layer. The visual
work is the largest — `dashboard_ui.html` now reads as a polished SaaS tool
(Linear/Vercel-leaning) rather than the ad-hoc Tailwind-ish look it carried
through the first eight sessions. The reached_out and snapshot changes are
small but unblock downstream workflows (outreach tracking, accurate downloads).

### Visual overhaul — design tokens + funnel chart + 2-col jobs list

The redesign was specified mockup-first in a new `designs/` folder, then
landed in `dashboard_ui.html` as two additive passes (PR1: tokens + re-skin;
PR2: SVG-style funnel + sparkbars). No class renames; only rule bodies and
markup additions, to stay merge-safe against concurrent Codex edits.

- **Design tokens** (prepended to `dashboard_ui.html` `<style>`): neutrals
  (Vercel-style grayscale), single indigo accent `#5b5bd6` (replaces the
  competing green/blue), semantic + soft variants, Inter via `rsms.me/inter`
  with system fallback, type ramp (`--fs-xs` 11 → `--fs-2xl` 28), 4px
  spacing grid, three-tier shadow (`--sh-1/2/3`), focus ring (`--sh-focus`
  0 0 0 3px rgba(91,91,214,.24)), motion (`--t-fast` 120ms / `--t-base`
  180ms).
- **Re-skinned components** in place: `.btn` (+ `.btn[disabled]` and
  `.btn.is-loading` with CSS-only spinner), `.pill`, `.sort-btn`, `.card`
  (selection now uses `box-shadow:inset 0 0 0 2px var(--c-accent)` to avoid
  the old 1px layout shift), `.co-table`, header (translucent + backdrop
  blur), tabs, modal, fit-row, status pills. Score badges re-tiered:
  5 → accent, 4 → info, 3 → neutral.
- **Pipeline funnel** — replaced the 6-row table render in `loadPipeline()`
  with a CSS-only horizontal-bar chart. Two scales (company stages rows 1-3,
  job stages rows 4-6) with a `Companies → Jobs` divider between them.
  Bars use `transform: scaleX(0→1)` keyframe animation. Delta annotations
  color-coded by drop severity (success / warn / danger). The bar list sits
  inside a sub-card frame (`border + 18px H padding`) so rows don't crash
  into the outer card edge.
- **Pipeline 2-col below the funnel** — gap + provider tables stacked
  LEFT, top-15 companies on the RIGHT (collapses to single col under
  820px). Top-companies rows render an inline `.pl-spark` sparkbar
  proportional to count.
- **Jobs tab — partitioned into two side-by-side sections**
  (collapses to one col under 1024px):
  - **"To apply"** (LEFT) — jobs where `!reviewed && !applied`.
    Per-section filter pills: All / Untailored / Tailored. Sorted by score
    desc, then `days_ago` asc (existing behavior).
  - **"To reach out"** (RIGHT) — jobs where `reviewed || applied`.
    Per-section pills: Applied (default) / Reviewed only / All. **Sorted by
    `job_interactions.updated_at` desc** so the most-recently-touched card
    surfaces first.
- **Compact cards** — padding 14×16 → 10×14, title 14 → 13, meta 12 → 11,
  checkbox 20 → 18px, action buttons 11px.
- **Job title is now a hyperlink** to the JD URL (existing apply_url).
  Standalone "Apply" + "View JD" buttons removed — they pointed at the same
  URL, so the title-link consolidates them. New `.title-link` style inherits
  text color until hover (then turns indigo with underline).
- **Outreach button visibility** — `Draft outreach` only appears on cards
  where `reviewed || applied`. Untouched cards in the To-apply column
  surface just `Tailor`.
- **New `designs/` folder** at the repo root with `tokens.css` plus 7
  standalone HTML mockups (token preview, pipeline, jobs card states, jobs
  list, companies, manual tailor, add-company modal) + `index.html` TOC.
  Served read-only via a new `/designs/<path>` Flask route on the dashboard
  for in-browser review. The folder doubles as a portfolio dossier and as
  the spec when implementing later phases.

### Reached_out state — third terminal status on applied jobs

Reviewed and Applied are now treated as **mutually exclusive end states** in
the dashboard. Reached-out is a sub-state of applied (one cannot reach out
to a job not yet applied). New button + state, new schema column.

- **Schema** — `job_interactions.reached_out INTEGER NOT NULL DEFAULT 0`,
  migrated via `_ensure_columns(conn)` on next `storage.connect()`. SCHEMA
  string updated so new DBs include it from the start.
- **Storage** — `update_job_interaction(reached_out=...)` kwarg added;
  `export_dashboard_state` selects `reached_out` and includes it in each
  `job_status` entry alongside the new `updated_at` field (used by the
  dashboard for the right-column sort).
- **Route** — `/api/job_status` field whitelist extended to
  `("reviewed", "applied", "reached_out")`.
- **UI conditional render** — `dashboard_ui.html` card now branches on
  state:
  - Untouched (`!reviewed && !applied`) → Mark Reviewed + Mark Applied.
  - Reviewed-only → only `✓ Reviewed` (toggle off → back to untouched).
  - Applied → `✓ Applied` + `Mark reached out` (or `✓ Reached out`).
  Visual: the new reached-out pill uses `--c-vc-soft` / `--c-vc-text`
  (purple) to read distinct from the green Reviewed and blue Applied pills.
- **Dashboard payload shape change** — `data.job_status[key]` now carries:
  ```json
  {"reviewed": bool, "applied": bool, "reached_out": bool, "updated_at": "<iso ts>"}
  ```
  Previously only `reviewed` + `applied`. Existing consumers that destructure
  the first two keys still work.

### Tailor download snapshot — refresh-on-write fix

Bug: tailoring a resume, then revising or re-tailoring, then clicking
**Download** on the dashboard surfaced the **previous** PDF content. Root
cause: `tailor.py` always writes to a canonical `<date>_<slug>.txt`, but the
dashboard's `/api/generate_pdf` copies that file to a standardized
`PPaul_<date>_<company>_<role>.txt` snapshot which the Download link points
at. Subsequent `/api/tailor` and `/api/revise` calls overwrote the canonical
.txt but didn't propagate to the standardized snapshot.

Fix: new helper `_refresh_standardized_snapshot(txt_filename, company,
role)` in `scripts/dashboard.py` that copies the canonical .txt to the
standardized .txt and rebuilds the .pdf. Wired into the post-success path
of `/api/tailor`, `/api/tailor_manual`, and `/api/revise`. The canonical
filename is reconstructed via a new `_canonical_tailor_filename()` helper
that mirrors `tailor.py`'s `<YYYY-MM-DD>_<slug>[_<version>].txt`
construction.

Companion ergonomics fix in `scripts/tailor.py`: prompt rule added that
forbids em-dash (`—`) / en-dash (`–`) in any tailored output (must be ASCII
hyphen), and the obsolete `[SQL NOTE: required/preferred]` annotation rule
was removed.

### Known follow-ups (not blocking)

- Section filter pills on the Jobs tab use inline `onclick=` —
  violates the "event delegation only" convention noted in CLAUDE.md.
  Re-wire through the existing `[data-action]` delegator.
- Funnel legend sits in the moat between the outer card border and the
  inner sub-card frame. Visually minor.
- Right-column sort uses row-level `updated_at`, which also moves on
  comment edits or fit-score saves. Acceptable proxy for "most recently
  touched"; would need a dedicated status-only timestamp column for
  strict "last reviewed/applied only" semantics.

---

## 2026-05-13 — 7 enterprise ATS detectors + slug-candidate hardening

Added detection for the 7 enterprise ATSes that dominate Fortune 1000's
"no signature" failure bucket, audited 2026-05-12: Eightfold, Avature,
Brassring (Kenexa), Phenom People, iCIMS, Taleo, Oracle HCM Cloud. Plus
two adjacent reliability fixes the integration uncovered.

### New providers (`scripts/storage.py`)

All 7 added to `ATS_PROVIDERS_DETECTABLE`. Detection only (no scan
integration yet — these tenants have less standardized job-list APIs
than Workday/Greenhouse/etc., and we can ship scanning as a follow-up
once the endpoint counts are real).

| Provider | Slug shape | Signature regex | Validation |
|---|---|---|---|
| eightfold | `<co>` | `([a-z0-9-]+)\.eightfold\.ai` | HEAD `https://<co>.eightfold.ai/careers` (the public job API returns 403 — Cloudflare-protected — so we settle for tenant existence) |
| avature | `<co>` | `([a-z0-9-]+)\.avature\.net` | HEAD `https://<co>.avature.net/` |
| brassring | `<partnerid>:<siteid>` | `sjobs\.brassring\.com[^"'<>]*?partnerid=(\d+)[^"'<>]*?siteid=(\d+)` | HEAD search URL (compound slug like Workday's `tenant:dc:site`) |
| icims | `[careers-]<co>` | `(?:careers-)?([a-z0-9-]+)\.icims\.com` | HEAD against both `careers-<co>` and `<co>` prefixes |
| phenom | `<co>` | `([a-z0-9-]+)\.phenompeople\.com` | HEAD `https://<co>.phenompeople.com/` |
| taleo | `<co>` | `([a-z0-9-]+)\.taleo\.net` | HEAD `https://<co>.taleo.net/` |
| oraclehcm | `<tenant>:<region>:<siteNumber>` | `([a-z0-9-]+)\.fa\.[a-z0-9]+\.oraclecloud\.com[^"'<>]*siteNumber=(CX_\d+)` | HEAD probes us2/us6/us1/ca2/em2 regions until one returns 200 |

`probe_website_for_ats` extended with special handling for the 2-group
brassring + oraclehcm regexes, mirroring the existing 3-group workday case.
`ats_url()` extended with reconstruction logic for all 7 providers — slugs
round-trip to landing-page URLs.

### Slug-candidate path improvements

`_try_slug_candidates` extended in two ways:

1. **Now filters false-positive slugs** before the API call. Walgreens
   (URL: `https://jobs.walgreens.com`) was matching `ashby/jobs` because
   `_candidate_slugs` extracts the `jobs.` subdomain as a candidate
   and Ashby has a real-but-generic board called "jobs" that returns
   a valid (1-job) response. Now filtered via `_is_false_positive_slug`.
2. **Now also tries Eightfold + Avature** after the Ashby/Greenhouse/Lever
   trio, on the top 2 candidates only. Catches Fortune cos with JS-rendered
   careers pages where the eightfold/avature URL never appears in static
   HTML — verified against Walmart (`careers.walmart.com`) and Morgan Stanley
   (`/careers/career-opportunities-search`), both of which the website-probe
   path can't reach.

### `_FALSE_POSITIVE_SLUGS` expansion

Added combinatorial junk slugs produced by `_candidate_slugs` when the website
URL has a generic subdomain (`jobs.<co>.com`, `careers.<co>.com`):
`getjobs`, `joinjobs`, `tryjobs`, etc. plus `careers`/`talent`/`hiring`
variants. Without this, any company with a `jobs.<co>.com` URL risked
false-positive matches against generic placeholder boards on the public
ATSes (Greenhouse has a real `getjobs` board returning 1 fake job).

### Verified test results — 11/11 known Fortune cos detect correctly

```
✓ Starbucks         → eightfold/starbucks       (via website_probe)
✓ Citigroup         → eightfold/citi            (via website_probe)
✓ Northrop Grumman  → eightfold/ngc             (via website_probe)
✓ Morgan Stanley    → eightfold/morganstanley   (via slug_candidates)
✓ Walmart           → eightfold/walmart         (via slug_candidates)
✓ CBRE Group        → avature/cbreglobal        (via website_probe)
✓ Lockheed Martin   → avature/lockheedmartin    (via website_probe)
✓ Delta Air Lines   → avature/delta             (via website_probe)
✓ Walgreens         → brassring/26336:5014      (via website_probe)
✓ Publix            → brassring/26173:5197      (via website_probe)
✓ Dollar General    → icims/login-dollargeneral (via website_probe)
```

Phenom, Taleo, Oracle HCM detectors are wired but un-validated against
known cos at write time. The 2026-05-13 Fortune redetect-v2 run will surface
real cases or none.

### Pre-redetect-v2 baseline (Fortune)

- 269 / 1,000 active ATS (26.9% hit rate)
- 731 cos with URL but no active ATS — the target population for v2

Expected v2 yield from yesterday's audit extrapolation:
- ~66 Phenom, ~66 Oracle HCM, ~37 Eightfold, ~37 Avature, ~15 iCIMS,
  ~15 Brassring, ~7 Taleo → ~240 cos recoverable. Conservative because
  Walmart-style JS-rendered sites where the static HTML carries no
  signature still won't be caught by Phenom/Avature/Brassring/iCIMS
  (their slug-candidate path isn't enabled — only Eightfold + Avature are).

---

## 2026-05-12 — Detector resilience (browser headers) + Tavily-based URL recovery + Regenerate flow

Three independent improvements landed in one session, mostly driven by analyzing
the dropoff funnel from yesterday's Fortune + Built In ingest. Net effect on
scan-eligible companies: TBD until both background runs finish, but on partial
results (150/786 of Fortune redetect done) we've already recovered ~6 large
public Fortune cos contributing **~5,000 net new Workday jobs**.

### Detector resilience — full browser headers in `_http_get_text`

The bare `User-Agent: Mozilla/5.0` previously sent by `storage._http_get_text`
silently failed on enterprise careers pages whose Cloudflare/Akamai WAF requires
realistic browser fingerprints. Symptom: Concentrix (440k employees, 1,759 open
Workday jobs) was probed daily and returned `not_found` for months because every
careers-page fetch was 403'd.

Fix:
- New `_BROWSER_HEADERS` constant in `scripts/storage.py` with full Chrome 120
  header set: `User-Agent` (real Mac Chrome), `Accept`, `Accept-Language`,
  `Sec-Fetch-Dest/Mode/Site/User`, `Upgrade-Insecure-Requests`.
- `_http_get_text` now sends `_BROWSER_HEADERS` instead of bare UA.
- Affects every detector path that probes a careers page (i.e. all non-slug
  detection); also helps any future component using the helper.

Verified recoveries (partial — redetect still running): Concentrix, Caterpillar,
Stanley Black & Decker, LKQ, Prudential, Mastercard — all Workday tenants
already in the regex but unreachable on bare UA.

Companion script: `scripts/ingest/redetect_fortune.py` — targeted re-detection
for the 786 Fortune cos that had `status='not_found'` from yesterday's run, so
we get a clean before/after delta without re-checking 2,800 unrelated cos.

### Built In URL backfill — Tavily search route after WAF block

Yesterday's ingest captured Built In list memberships but deferred per-company
website URLs (URL lives only on the per-company detail page, ~2k extra fetches).
Today's recovery attempt:

1. **Direct scrape** (`scripts/ingest/builtin_url_backfill.py`) — first 50 cos
   succeeded, then **Built In's Cloudflare WAF IP-banned us** for the rest. Even
   single curl with proper headers now returns 403. The script is retained for
   archival; do not re-run from this IP without a 24h+ cooldown.

2. **Tavily web search** (`scripts/ingest/builtin_url_via_tavily.py`) — works
   around the ban by querying a third-party search API. For each missing co,
   sends `"<name> official website <hq_city>"` to Tavily, takes the top-scored
   result, derives the **apex domain** (e.g. `jobs.zs.com` → `zs.com`,
   `portal.afterpay.com` → `afterpay.com`), filters out directories /
   aggregators / staging hostnames. Smoke test: 8/10 correct on first run; the
   2 failures (ZS routed to lensa.com aggregator, Afterpay routed to a staging
   k8s subdomain) prompted (a) expanding `DISALLOWED_APEXES` with job
   aggregators (lensa, ziprecruiter, simplyhired, etc.) and (b) a new
   `_STAGING_LABEL_PATTERNS` regex that rejects any host containing `staging`,
   `stg`, `dev`, `test`, `preview`, `qa`, `sandbox`, `k8s`, or `internal` in
   any subdomain label. Re-runs after the fix produced correct URLs for both.

   On the in-progress full run: ~99% success rate at 1 query/sec (~30 min for
   1,746 cos). Built In's per-page detail fetch wasn't the right shape anyway
   (rate-limited), so Tavily becomes the long-term path for any source where
   we have a name but no URL.

3. **`get_tavily_key()` added to `scripts/keys.py`** reading from
   `/root/.tavily/key` (mode 0600). Mirrors the existing Anthropic / DeepSeek
   loaders. `get_key("tavily")` works through the generic accessor.

### Resume Regenerate flow (Sonnet 4.6 + user comments)

`scripts/dashboard_ui.html` already had an "Apply comments ↻" button inside the
Review panel that ran a Haiku-based inline edit on the existing draft. Useful
for quick fixes, but limited: it can only modify what's already there, not
restructure the whole tailoring decision (e.g. "stop emphasising responsibilities
I haven't done — re-anchor on the JD's 'Who you are' section").

Added a **Regenerate** button next to "Apply comments" with different semantics:

- New `/api/regenerate` route in `scripts/dashboard.py` — same model as the
  initial Tailor flow (`claude-sonnet-4-6`), but injects the user's comments as
  a `USER GUIDANCE (highest priority)` block before the TASK section in the
  prompt.
- `scripts/tailor.py` `run()` extended with optional `comments` kwarg + CLI
  `--comments` flag. Argparse migration also fixes a latent bug where the
  legacy 4th-positional `version` arg sniffed `sys.argv[4]` directly — now
  `sys.argv` is reset before `run()` so the version-tagged-filename behavior
  doesn't accidentally pick up `--comments` as the version.
- Two-button UX inside the Review panel: tooltips clarify model choice (Haiku
  for light edits via Apply comments; Sonnet 4.6 for full re-tailor via
  Regenerate).
- Validated end-to-end on a real job (Stripe "Forward Deployed AI Accelerator,
  Marketing", job_id 833): regenerated summary correctly pivoted from
  responsibilities-language to "Who you are"-language anchored on the AI
  practitioner / pattern recogniser / coach axes.

### Smaller items
- `resumes/master_resume.txt` — Armor Defense end date `Present` → `Dec 2025`.
  Picked up automatically on next tailor / regenerate (script reads master
  fresh per call).
- `scripts/dashboard.py` gained a `/designs/` static-file route for serving
  HTML mockups out of `/root/pp-jobapp/designs/` (concurrent edit, unrelated to
  this session's work).

---

## 2026-05-11 — External company-list ingestion architecture + Fortune 1000 + Built In BPTW

Introduced a thin convention for pulling external company lists into the master
`companies` table. Loaded two sources in one pass: Fortune 1000 (2024, Kaggle)
and Built In Best Places to Work (2025, 64 award lists across 16 geos × 4 size
segments). Companies table grew from 3,170 → 5,939 (+2,769 net new); 2,293
companies now appear in more than one source bucket. ATS discover phase
(n=2,804) launched immediately after to bring new companies into scan rotation.

### Schema changes (`scripts/storage.py`)

- Five new nullable columns on `companies`: `ticker`, `hq_city`, `hq_state`,
  `employee_count` (INTEGER), `company_type` (Public/Private). Cross-source
  useful — promoted out of `raw_metadata_json` because Fortune + Built In both
  populate them and downstream queries want them filterable.
- `upsert_company` extended with the 5 new kwargs; COALESCE semantics preserved
  (first non-null source wins; later sources never clobber).
- New `upsert_company_source_metadata(conn, company_id, ..., merge_keys)` —
  for sources where one company maps to one `company_sources` row whose
  metadata accumulates over re-runs (declared `merge_keys` get list-merged with
  dedup; other keys get replaced). `add_company_source` (the existing
  `INSERT OR IGNORE` path) stays for sources where each (company, list) is a
  separate row.
- Schema migration is idempotent via `_ensure_columns`. Pre-migration DB backup
  at `workspace/jobapp.db.bak-pre-ingest-20260511-183910`.

### Ingest convention (`scripts/ingest/`)

- `common.py` — `CompanyRecord` dataclass + `ingest_companies()` helper.
  Match strategy: primary key is `normalized_name`; fallback is **exact-host**
  website comparison (a dry-run found `LIKE '%domain%'` would have produced 22
  false positives like AT&T→Exowatt; tightened before any writes).
- `fortune1000.py` — reads the Kaggle CSV. 1,000 → 972 new + 28 matched.
- `builtin_bptw.py` — scrapes one list URL at a time, caches raw HTML in
  `workspace/data/external/builtin_bptw/<date>/`, parses 49–100 companies
  per page (server-rendered; no JS execution needed). Drives the 64 URLs in
  one pass via `--all`. 2,092 unique companies; 5,022 total list memberships
  via the JSON-array merge path. NB: Built In's geo slug for New York is
  `new-york-city` (not `nyc` as their index page implies).
- Provenance: raw downloads land at
  `workspace/data/external/<source>/<YYYY-MM-DD>/` for replay.

### Coverage after ingest

- ticker: 959 (Fortune)
- hq_city: 3,008 / hq_state: 2,786 (Fortune + Built In)
- employee_count: 2,998
- company_type: 1,000 (Fortune only)
- 83 companies overlap between Fortune + Built In (Microsoft, JPM, Pfizer,
  Lowe's, Boeing, etc.) — now carry both ticker and award-list presence.

### Gaps left open

- Built In website URLs not captured (live on per-company detail pages, not
  list pages — ~2k extra fetches, deferred).
- Position-in-list captured for Built In but Built In does not publish actual
  rank numbers on these pages; the captured `position` is HTML render order,
  which may or may not correspond to ranking. Don't surface as "rank N" to
  users without verifying.

## 2026-05-08 — Workday provider support

Added Workday as a first-class detectable + scannable ATS provider, taking
total supported providers from 11 to 12 and active endpoints from 1,282 to
1,309. Backfill of the 32 Workday-tagged companies in the unknown bucket
recovered 27 (84%); the 4 unrecoverable companies are anti-bot 403 blocks
on their careers pages (unreachable bucket); 1 (Accolade) hits a
tenant-specific 422 on the Workday cxs API and is left for later.

- Added `workday` to `ATS_PROVIDERS_DETECTABLE` and `ATS_PROVIDERS_SCANNABLE`
  in `scripts/storage.py`.
- New `_workday_check(tenant, dc, site)` validates against the Workday
  cxs jobs API (POST `/wday/cxs/{tenant}/{site}/jobs` with JSON body).
- New `_http_post_json(url, body)` helper alongside existing GET helpers.
- Workday signature added to `_ATS_SIGNATURES` with three capture groups
  (tenant, dc, site), skipping optional `{lang}/` or `{lang}-{REGION}/`
  locale segments.
- `probe_website_for_ats` regex loop refactored to dispatch slug
  extraction by provider — Workday's 3-group case wires through
  `_workday_check`; all other providers go through the existing
  1-group `_validate_captured_slug` path.
- Slug format for Workday: `tenant:dc:site` (e.g.,
  `sailpoint:wd1:SailPoint`). `ats_url(provider, slug)` parses the colon
  form and rebuilds the landing URL.
- New fetcher `fetch_workday(company)` in `scripts/ats_scout.py`,
  paginating up to 1,000 jobs (Workday API page size = 20). Wired into
  the scan dispatch loop. Note: Workday's listing endpoint returns
  title + locationsText only — no JD — so match-fit relies on
  title-match alone (`jd_fallback` is inert for Workday rows).
- **Bug fix (incidental):** `_http_get_text` body cap raised from 300KB
  to 2MB. Three of the 8 initial backfill misses (Blue Apron,
  BigCommerce, ServiceTitan) had Workday URLs at byte positions 354K,
  412K, and 577K — silently truncated by the old cap. Affects all
  detector-based detection, not just Workday.
- Targeted backfill script `tools/backfill_workday.py` for the 32
  audit-identified companies; idempotent and re-runnable.

Top recovered boards: Adobe (1,179 jobs, via Frame.io's parent), CrowdStrike
(494), Workday-itself (382), Sunrun (358), RingCentral (269 via Hopin's
acquirer). Total Workday open jobs added to scan rotation: ~5,200.

### Follow-up: dashboard days_ago now live-computed (2026-05-09)

The dashboard's "days posted ago" was being read from `raw_json.days_ago`,
which is the value scout computed at scrape time and froze into the JSON
blob. After re-scout, today's-newly-fetched jobs would show correct
freshness, but anything not re-fetched (incl. older shortlisted jobs and
anything filtered out by the 14-day recency cutoff) kept its stale
scout-time value indefinitely.

Fix: `storage._job_dict` now overrides `days_ago` with a live recompute
from `posted_date` via the new `_compute_days_ago` helper. Verified
against current shortlist — frozen values were 4 days behind reality;
live values match today.

`posted_date` itself was already being kept fresh (overridden from the
`job_postings.posted_date` column on each `_job_dict` call), so no
backfill of stored data is needed — the fix takes effect on the next
`/api/data` request.

### Follow-up (same day): 14-day recency filter

Added a configurable `max_job_age_days` setting (default 14, in
`scripts/scout_config.json` under `scout_settings`) and applied a
recency filter at the fetcher level for all four providers. Jobs
posted more than N days ago are skipped before evaluate_role / JD
fetch / DeepSeek scoring — saving compute and money on stale postings.

- `MAX_JOB_AGE_DAYS` read from config in `ats_scout.py` alongside
  `JD_CAP` / `JD_FALLBACK_ENABLED`.
- `fetch_ashby` / `fetch_greenhouse` / `fetch_lever`: filter check
  moved to the top of the per-job loop (before title/JD work).
- `fetch_workday`: recency filter applied in stage 2 (pre-JD-fetch)
  via a new `_parse_workday_posted_on` heuristic that maps
  `"Posted Today"` → 0, `"Posted N Days Ago"` → N, `"Posted N+ Days Ago"`
  → N (lower bound). Previously Workday rows had no `posted_date` /
  `days_ago`; both are now populated (date is `today - days_ago`,
  approximate by 1 day).
- Convention: jobs with missing or unparseable dates are *kept*, not
  dropped — being permissive on signal-loss matters more than
  filtering hygiene.

**Measured impact on CrowdStrike (Workday):** 13 → 2 matches, 85%
reduction in scoring volume. Same scan duration since the filter
runs before the JD fetch.

### Follow-up (same day): JD parity for Workday

Workday's listing API returns title + locationsText only — no JD. Initial
ship matched on title alone, leaving `jd_fallback` inert and losing all
matches whose fit signal lives in the JD. Closed the gap with a two-stage
flow inside `fetch_workday`:

- New `workday_job_jds` cache table (apply_url PK, jd_text, fetched_at)
  added to the SQLite SCHEMA and bootstrapped via `_ensure_columns` so
  existing DBs migrate on next connect. `get_cached_workday_jd` /
  `set_cached_workday_jd` helpers in `storage.py` (30-day TTL).
- `fetch_workday(company, db_conn=None)` now: (1) fetches the listing,
  (2) drops `rejected_negative` titles via cheap pre-filter, (3) parallel
  JD fetch from the cxs `/job{externalPath}` endpoint for survivors
  (cache-first, 4 workers; SQLite reads/writes in main thread only),
  (4) re-runs `evaluate_role(title, jd)` so `jd_fallback` fires.
  Listing fetch retries once on empty first page (transient
  rate-limiting after large boards otherwise dropped CrowdStrike to 0).
- `_extract_jd` adds a `'workday'` case that honors the resolved
  `j['jd_text']` for callers that re-extract.
- Scan dispatch passes the open `db_conn` into `fetch_workday`.

**Measured uplift across the 5 largest boards (2,501 jobs scanned):**
60 title-match + 19 jd_fallback = 79 matches — JD parity contributed
24% of all Workday matches in the sample, lost-yield without this work.

Reference: `docs/investigations/2026-05-07_phase2_unknown_audit.md`
(Addendum 2026-05-08).

## 2026-05-04 — ATS detection refactor + first backfill

Major detection-logic overhaul plus the first DB-wide backfill of
`ats_endpoints`.

- Extracted `detect_ats()` from dashboard.py to storage.py as a pure,
  importable function. Dashboard route became a thin wrapper.
- Added `discover_phase()` to ats_scout.py — orchestrates discovery
  across the DB, writes hits/misses/dead URLs to `ats_endpoints` with
  `last_checked_at` so runs are resumable. New CLI flags
  `--discover`, `--then-scan`, `--limit`, `--max-age-days`.
- Detection logic improved: ~60 candidate slugs (suffix variants,
  prefixes, suffix-stripping, domain-stem); 15 careers-page paths
  probed; 12 ATS signature patterns; DNS pre-flight detects dead URLs
  early; URL-decoding + case preservation in slug capture; empty-jobs
  response now treated as a hit.
- Bulk scripts (`bulk_add_companies.py`,
  `ats_scout_getro_bulk_add.py`) now call `storage.detect_ats()`
  directly — removed the localhost:5000 HTTP dependency on the
  dashboard process being up.
- Reactivated 2,402 companies that had been bulk-deactivated by the
  old detection's no-ATS failures (verified none were
  `dashboard_manual` deletions before reactivation).
- Launched first backfill of `discover_phase()` across all 2,402
  reactivated companies via `tools/backfill_ats_detection.py`.

Commits: 88aeb7d, eae0863, 0a0db14, 6738d32, 791a97b, fe548d8, 48120cf

## 2026-05-04 — Repo hygiene: tools/ and archive/ structure

- Introduced `tools/` for one-off human-run scripts (with
  `tools/audit/` carrying read-only inspection tools), and `archive/`
  for deprecated code kept for historical reference. Updated
  `.gitignore` for `__pycache__`/scratch files.
- Added `__main__` guard to `ats_scout.py` to prevent the
  import-runs-the-scan footgun that bit us this same session.

Commits: c57cc94, ffe39a0

## 2026-05-04 — SQLite Phase 5: dashboard + matcher DB-native

Dashboard, matcher, and scout flipped from JSON to SQLite-canonical
reads.

- Dashboard `/api/data` and company scan stats now read from SQLite
  (`job_postings` + `job_scores`) instead of `raw_jobs.json`.
- Matchers load jobs from SQLite, write scores to `job_scores` under
  `scorer='current_shortlist'`. `shortlist.json` becomes
  backup/debug only.
- Dashboard scan order: Scout → migrate/import to DB → Matcher, so
  the Matcher sees fresh scanned jobs through SQLite.
- `raw_jobs.json` and `shortlist.json` retained as backup exports,
  not read in normal operation.

Commits (approx): 9459a02, 791d71b, e90dfc8, 86e04d3, 46948c1, e94a66d

## 2026-05-03 — sqlite-phase-5-db-native PR merged

Umbrella PR landing the SQLite migration. Removed JSON fallback paths;
system now fails loudly when DB missing rather than silently falling
back. Untracked OpenClaw agent identity files (`USER.md`, `AGENTS.md`,
etc) — they remain as templates in repo but per-instance state is
gitignored.

Commits: 55dff8e, bda367b

## 2026-05-02 (Session 7) — Getro VC sourcing + bulk-add + Sonnet upgrade

- First production `getro_scraper.py`.
- 779-VC bulk scan via `ats_scout_getro_bulk_add.py` +
  `bulk_add_companies.py`.
- Resume library expanded.
- Tailor model: Sonnet 4 (2025-05-14) → Sonnet 4.6.
- WhatsApp integration removed.
- Project renamed; README simplified.

Commits: 52d7fdd, 17de298, 3cc2396, 2a441c7, ca9dedf, ddc4d9c, ef6d168, ab55750

## 2026-04-09 — Dashboard review-panel hotfixes

Two specific footguns worth recording so they don't get reintroduced:

- onclick truncation from `&` in role titles → fixed via data
  attributes (don't inline-string-concat role titles into onclick
  handlers).
- Education header conflict in tailored docx → fixed; consolidated
  known issues; updated session history.

Commits: 4a9c38c, 7f60303

## 2026-04-08 (Session 4) — Resume library + dashboard review panel

Curated library of 12 prior tailored versions wired into `tailor.py`
as context. Master resume updates, PDF fixes, dashboard review panel.

Commits: c64d91d

## 2026-04-08 (Session 3) — Resume Tailor + PDF generator + posting dates

Tailor (Claude Sonnet) introduced. PDF generator (WeasyPrint Clean
Classic, auto 1-page). Posting dates surfaced in dashboard with
freshness coloring.

Commits: 8aadc80

## 2026-04-07 (Sessions 1-2) — Initial pipeline

ATS Scout (Ashby/Greenhouse/Lever direct JSON APIs). DeepSeek scoring
matcher. Flask dashboard with job cards, comments, quick tags. Skill
files, `docs/` structure. WhatsApp message generation (later removed
in Session 7). `workspace/` excluded from git (managed by OpenClaw
harness).

Commits: 5697ef5, 32c2f52, 5788269, d345353, faa05d7, 686d432

## 2026-04-07 — Architecture: ATS direct API over Playwright

Foundational decision: skip browser automation, hit Ashby /
Greenhouse / Lever JSON APIs directly. Rationale documented in
`CAREER_OPS_LEARNINGS.md`. No browser dependency in the production
pipeline.
