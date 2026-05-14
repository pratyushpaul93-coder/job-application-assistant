# Phase 2 — Unknown bucket audit (2026-05-07)

## Question

What's blocking ATS detection for the 1,378 companies in the
`unknown/not_found` bucket, and where should we invest to close the gap toward
the 2,000-matched-jobs goal?

Going in we knew:

- 1,887 of 3,169 active companies (60%) had no ATS endpoint.
- 1,378 of those had been probed and returned `provider=unknown,
  status=not_found` — i.e., the discover pipeline ran but no provider matched.
- Backlog assumed long-tail providers (Workday, iCIMS, etc.) were the main gap,
  with Workday yield estimated at "200+ endpoints".
- We had no data on the relative size of JS-rendered, in-house, or
  detector-bug buckets.

## Method

- Built `tools/phase2_unknown_audit.py` — pure HTTP + regex, no LLM, $0 to
  run.
- For each sampled company: fetch homepage + 8 careers paths (`/careers`,
  `/jobs`, `/career`, `/work-with-us`, `/join`, `/join-us`, `/about/careers`).
- Categorize via regex match against ~25 ATS provider patterns + SPA-marker /
  mailto / static-text heuristics.
- Two-pass approach:
  1. **n=100 sense-check** (2026-05-06). Found 50% of the initial
     "missed by discover" hits were stale links to dead boards (e.g.,
     Divvy Homes' careers page references `boards.greenhouse.io/divvyhomes`
     but Greenhouse itself returns 404 for that slug). Refined the script to
     verify slugs against the provider's own API, downgrading dead ones to a
     `stale_provider_link:<provider>` category. Removed the comeet pattern
     after it produced false positives via no-capture-group regex.
  2. **n=1,378 full audit** (2026-05-07) with refined logic.
- Wall time: ~30 min at workers=16. ~12K HTTP requests + ~150 slug-verify
  calls. No LLM, no `web_search` tool.

## Findings

### Category distribution

| Category | Count | % |
|---|---:|---:|
| `static_in_house` | 672 | 49% |
| `empty_or_tiny` | 271 | 20% |
| `js_rendered_spa` | 190 | 14% |
| `unreachable` | 109 | 8% |
| `has_provider:*` (live, supported) | 64 | 4.6% |
| `has_provider:*` (live, unsupported) | 56 | 4.1% |
| `stale_provider_link:*` | 10 | 0.7% |
| `mailto_only` | 6 | 0.4% |

### 64 missed-by-discover, by failure mode

These are companies where the existing detector should have worked. Each mode
has a clear remediation in `scripts/storage.py`.

| Failure mode | Count | Examples |
|---|---:|---|
| Greenhouse `/embed/job_board/js?for=` regex variant not in `_ATS_SIGNATURES` | 8 | Housecall Pro, LightForce, Relativity Space, Vectra, Density, Noom |
| Workable not in slug-candidate probing (`_try_slug_candidates`) | 15 | Marqo, Carry1st, dltHub, Bettermode, YouTrip, Portainer |
| Ashby with URL-encoded multi-word slugs | 14 | Citizen Health, Tools for Humanity, Nautilus Biotechnology, Genesis Therapeutics |
| bamboohr direct-slug not probed | 8 | Prezi, Anaqua, Kandou, Shortcut, ZAGENO, Graphiant |
| teamtailor direct-slug not probed | 5 | PredictHQ, Nym, Tractive, Factorial |
| Other (lever / jazzhr / smartrecruiters / etc.) slug variants | 14 | Tackle.io, IFTTT, HVMN, Science Exchange |

Full list of 64 names: `workspace/phase2_probe_results_20260507.csv`
(filter `missed_by_discover=True`).

### Strategy correction: Workday is real

The n=100 sample under-counted Workday by 32×.

| Provider | n=100 sample | n=1,378 full | Clears ≥5 threshold? |
|---|---:|---:|:---:|
| **workday** | 1 (1%) | **32** (2.3%) | ✓ |
| iCIMS | 0 | 6 | ✓ |
| eightfold | 1 | 5 | ✓ |
| breezy | 0 | 4 | ✗ |
| successfactors | 1 | 3 | ✗ |
| phenom | 0 | 2 | ✗ |
| jobscore | 1 | 2 | ✗ |
| cornerstone | 0 | 1 | ✗ |
| recruiterflow | 0 | 1 | ✗ |

### Path-to-2,000 math

Assumes the full-DB averages: ~30 jobs per active endpoint, ~22% match rate
(score ≥3) at current rubric.

| Action | Endpoints | Postings | Matches | Cumulative |
|---|---:|---:|---:|---:|
| Current state | 1,282 | 2,009 | 435 | 435 |
| Detector bug fixes (4 patches) | +64 | +1,920 | +422 | 857 |
| Add Workday | +32 | +960 | +211 | 1,068 |
| Add iCIMS + Eightfold | +11 | +330 | +73 | 1,141 |
| JS-rendering fallback (Playwright) | +190 | +5,700 | +1,254 | **2,395** |

Detector fixes + Workday + long-tail combined gets to ~1,141. **Only
JS-rendering closes the 2,000 target.**

### Unaddressable buckets (49% + 8% + 0.4% = 57% of the unknown bucket)

- `static_in_house` (672, 49%): careers page renders, sometimes lists roles,
  but no third-party ATS or detectable apply mechanism. Often a contact form.
  Solving requires in-house scraping or LLM-based role parsing — cost far
  exceeds per-company yield.
- `unreachable` (109, 8%): fetch failed entirely. Mostly bot blocks (Cloudflare
  / Akamai). UA rotation might recover some; low priority.
- `mailto_only` (6, 0.4%): recruit by email. Skip.
- `empty_or_tiny` (271, 20%): page body too small to assess. Some overlap with
  `js_rendered_spa` (could move there with better SPA detection).

### Error taxonomy (6,581 total fetch errors)

| Bucket | Count | Note |
|---|---:|---|
| http_404 | 5,531 | Expected — we try 8 careers paths per company |
| http_403 | 312 | Bot blocks |
| timeout | 223 | |
| http_5xx | 82 | Transient |
| http_4xx | 79 | |
| dns_nxdomain | 3 | Tiny — Phase 0B retired the 28 known dead URLs |
| other | 351 | Mostly miscellaneous URL/socket errors |

Average 4.8 errors/company. Healthy shape; no surprises.

## Implications

1. **New Tier 1 item**: bundle the 4 detector failure modes into one
   `storage.py` patch series. Yield: +64 endpoints, +422 matches.
   Highest yield-per-LoC of any backlog work.
2. **Confirm Tier 2 Workday item**, correct yield estimate from "200+" to
   "~32 (from existing companies)". Still worthwhile.
3. **Long-tail backlog item**: only iCIMS (6) and Eightfold (5) cleared the
   ≥5 threshold. Add those; do not speculatively add the other six providers.
4. **JS-rendering should promote to Tier 2**: confirmed as the single largest
   lever (+1,254 matches) and the only path that closes 2,000.
5. **Do not pursue `static_in_house` bucket**: 49% of unknowns is a wall, not
   an opportunity. Move on.

## Outputs

- `workspace/phase2_probe_results_20260507.csv` — full 1,378-row table with
  category, slug, evidence, `missed_by_discover` flag.
- `workspace/phase2_run_20260507.log` — run log with category distribution and
  the 64-row missed-by-discover list.
- `workspace/phase2_errors_20260507.log` — one line per fetch failure.

Tool: `tools/phase2_unknown_audit.py` (re-runnable for periodic audits).

---

## Addendum 2026-05-08: JS-rendering yield reality check

Before committing to Playwright infrastructure, two empirical scoping passes
were run against the 190 `js_rendered_spa` rows. Both invalidated the
+190-endpoint upper bound this report assumed.

### Pass 1: HTTP-only provider-hostname scan (n=190)

Tool: `tools/scope_spa_provider_hints.py`. For each SPA, re-fetched homepage +
7 careers paths and grepped raw HTML for *any* known provider hostname (no
slug capture required) — the broadest possible "lightweight fallback could
work here" signal.

**Result: 2 of 190 (1%)** mention any provider hostname in static HTML —
Grammarly and ModernLoop, both Greenhouse. The lightweight fallback is dead.

Detail: `workspace/spa_scoping_20260508.csv`.

### Pass 2: Playwright headless render (n=20)

Tool: `tools/render_spike.py`. Random sample of 20 SPAs, rendered with
chromium, waited on `networkidle` (8s) + extra 3s, tried apex + 4 path
variants + `careers.<host>` + `jobs.<host>` subdomains. Looked for both full
slug regex matches and bare hostname mentions.

**Result: 0 of 20 (0%) yielded a slug. 1 of 20 (5%) yielded a hostname-only
mention** — ThoughtSpot, surfacing `myworkdayjobs.com`. Even that hit points
to Workday, which the existing detector cannot consume without first
shipping #3.

### Why the original +190 estimate was wrong

The audit categorized SPAs purely on framework markers (`__NEXT_DATA__`,
`webpackJsonp`, `<div id="root">`). It did not verify that a third-party
provider exists *behind* the JS. Three plausible explanations for the gap
between the framework signal and the recoverable-provider population:

- Many "SPAs" are in-house ATS implementations — the careers content is
  rendered, but the apply mechanism is custom (overlap with the
  `static_in_house` bucket).
- SPAs that *do* embed a third-party board often gate the iframe behind a
  user interaction (click "View Roles") or load it lazily after first
  paint — passive rendering misses both.
- Companies that switched from a marketing SPA to a hosted ATS subdomain
  (`careers.example.com`) without leaving any link on the apex.

### Implications

1. **Demote JS-rendering work** to Tier 3 in BACKLOG.md. Yield revised from
   "+190 endpoints / +1,254 matches" to "indeterminate, likely <15 endpoints
   based on 2026-05-08 spike."
2. **Path-to-2,000 math no longer closes.** With detector bug fixes (#1) +
   Workday (#3) + iCIMS/Eightfold (#6), the cumulative ceiling is ~1,141
   matches, not 2,395. The 2,000 goal now requires either:
   - 5K company expansion (#11) brought forward,
   - Form D scraper integration (#12) brought forward,
   - or a different SPA-recovery technique — paid scraping API, click-driven
     interaction script, or LLM-assisted careers-page parsing.
3. **Workday is now strategically more important** than the original report
   credited. It is the dominant provider observed *behind* SPAs in the spike,
   and any future SPA-recovery effort depends on consuming it.

### Outputs

- `workspace/spa_scoping_20260508.csv` — per-company hostname-mention table
  for the 190 SPAs (HTTP-only pass).
- `tools/scope_spa_provider_hints.py`, `tools/render_spike.py` — re-runnable.
