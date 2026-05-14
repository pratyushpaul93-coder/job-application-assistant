#!/usr/bin/env python3
"""Outreach draft generator — multi-variant edition.

Two-stage pipeline:
  1. research(company)  — Sonnet + web_search, one call per company (cached 30d)
  2. compose(slant, …)  — Sonnet, no web_search, per variant

`generate_variants(job_id)` orchestrates: research once, compose N variants
in parallel slants, return as siblings sharing a `variant_group_id`.

Cost-gated by outreach.budget before every API call (see [[feedback-llm-search-cost]]).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
import uuid
import logging
import traceback
# (parallel compose intentionally removed 2026-05-13 — see generate_variants for why)
from datetime import datetime, timedelta

import yaml

log = logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(HERE)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
from keys import get_anthropic_key  # noqa: E402

from outreach import budget  # noqa: E402

KIT_PATH = os.path.join(HERE, "kit.yaml")
PRIORS_PATH = "/root/pp-jobapp/workspace/outreach_priors.txt"
DB_PATH = "/root/pp-jobapp/workspace/jobapp.db"

DEFAULT_MODEL = "claude-sonnet-4-6"
OPUS_MODEL = "claude-opus-4-7"
RESEARCH_MAX_SEARCHES = 4
RESEARCH_TTL_DAYS = 30
JD_TRUNCATE = 6000


# ── DB helpers ────────────────────────────────────────────────────────

def _load_kit() -> dict:
    with open(KIT_PATH) as f:
        return yaml.safe_load(f)


def _load_priors() -> str:
    """Return Bayesian-prior guidance text (built from past edits + outcomes).

    The patterns view writes this file; if it doesn't exist yet, return ''.
    Drafter injects it into the system prompt verbatim.
    """
    if os.path.exists(PRIORS_PATH):
        try:
            return open(PRIORS_PATH).read().strip()
        except OSError:
            return ""
    return ""


def _fetch_job_context(job_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT j.id, j.title, j.jd_text, j.job_url, j.apply_url,
                   c.id AS company_id, c.canonical_name AS company,
                   c.website_url, c.vertical, c.stage, c.headcount_range
            FROM job_postings j
            JOIN companies c ON c.id = j.company_id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _get_cached_research(company_id: int, ttl_days: int = RESEARCH_TTL_DAYS) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM outreach_research_cache WHERE company_id = ?",
            (company_id,),
        ).fetchone()
        if not row:
            return None
        try:
            fetched = datetime.fromisoformat(row["fetched_at"].replace("Z", "").replace(" ", "T"))
        except (ValueError, AttributeError):
            return None
        if datetime.utcnow() - fetched > timedelta(days=ttl_days):
            return None
        return {
            "company_id": row["company_id"],
            "research": json.loads(row["research_json"]),
            "sources": json.loads(row["sources_json"] or "[]"),
            "model": row["model"],
            "fetched_at": row["fetched_at"],
            "from_cache": True,
        }
    finally:
        conn.close()


def _save_research(company_id: int, research: dict, sources: list, model: str, cost_usd: float, search_count: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO outreach_research_cache
                (company_id, research_json, sources_json, model, cost_usd, search_count, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(company_id) DO UPDATE SET
                research_json = excluded.research_json,
                sources_json = excluded.sources_json,
                model = excluded.model,
                cost_usd = excluded.cost_usd,
                search_count = excluded.search_count,
                fetched_at = CURRENT_TIMESTAMP
            """,
            (company_id, json.dumps(research), json.dumps(sources), model, cost_usd, search_count),
        )
        conn.commit()
    finally:
        conn.close()


# ── Anthropic API plumbing ────────────────────────────────────────────

def _post_messages(payload: dict) -> dict:
    api_key = get_anthropic_key()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic API {e.code}: {body}") from e


def _extract_final_text(api_response: dict) -> tuple[str, list[dict], int]:
    """Walk content blocks; return (final_text, auto_citations, server_tool_searches_made)."""
    text_parts: list[str] = []
    citations: list[dict] = []
    seen_urls: set[str] = set()
    for block in api_response.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
            for c in block.get("citations") or []:
                url = c.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    citations.append({
                        "url": url,
                        "title": c.get("title"),
                        "cited_text": (c.get("cited_text") or "")[:240],
                    })
    usage = api_response.get("usage") or {}
    sru = usage.get("server_tool_use", {}) or {}
    searches = int(sru.get("web_search_requests", 0))
    return "".join(text_parts).strip(), citations, searches


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _parse_json_payload(text: str) -> dict:
    s = _JSON_FENCE_RE.sub("", text).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object found in model output:\n{text[:400]}")
    return json.loads(s[start : end + 1])


# ── Stage 1: research ─────────────────────────────────────────────────

_RESEARCH_SYSTEM = """You are researching a company so a follow-up step can write a sharp McKinsey-style "why I'm interested" paragraph in Pratyush Paul's outreach message.

Use the web_search tool 3-4 times. Surface SPECIFIC facts that a thoughtful operator would care about: recent funding (round, stage, lead), product launches in the last 6 months, named integrations or customer wins, the business mechanic / moat / wedge, competitive positioning, market dynamics. Avoid generic praise ("technically elite", "industry-defining").

Return STRICT JSON only — no markdown fences, no preamble:

{
  "thesis_one_liner": "what's the real bet — 1 sentence naming the business mechanic",
  "moat_or_wedge":    "what makes them defensible — 1 sentence",
  "specific_facts": [
    "fact 1 with a number or named entity",
    "fact 2",
    "fact 3"
  ],
  "recent_signals": [
    "2026-MM: <funding / launch / hire / integration>",
    "..."
  ],
  "what_to_skip": [
    "generic praise points that won't land — list them so the composer avoids these"
  ]
}
"""


def _research_company(job_ctx: dict, *, model: str = DEFAULT_MODEL) -> dict:
    """Run the web-search-grounded research call. Returns dict suitable for caching."""
    # Pre-flight: gate budget. Worst-case 4 searches + ~6K input + ~1K output on Sonnet.
    est = budget.estimate_cost(model, 6000, 1000, RESEARCH_MAX_SEARCHES)
    budget.check(est)

    user_msg = (
        f"Research this company for an outreach message:\n\n"
        f"  Company:           {job_ctx['company']}\n"
        f"  Company website:   {job_ctx.get('website_url') or '(unknown — discover via search)'}\n"
        f"  Vertical:          {job_ctx.get('vertical') or '(unknown)'}\n"
        f"  Stage:             {job_ctx.get('stage') or '(unknown)'}\n"
        f"  Role on offer:     {job_ctx['title']}\n\n"
        f"Return strict JSON per the schema."
    )
    resp = _post_messages({
        "model": model,
        "max_tokens": 2048,
        "system": _RESEARCH_SYSTEM,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": RESEARCH_MAX_SEARCHES}],
        "messages": [{"role": "user", "content": user_msg}],
    })
    text, citations, searches = _extract_final_text(resp)
    research = _parse_json_payload(text)
    cost = budget.compute_actual_cost(model, resp.get("usage", {}), searches)
    return {
        "research": research,
        "sources": citations,
        "model": model,
        "cost_usd": cost,
        "search_count": searches,
        "from_cache": False,
    }


def peek_research(company_id: int) -> dict | None:
    """Return cached research metadata + age in days, or None. No side effects.

    Used by the dashboard to render "research cached / fresh / never run"
    state before the user commits to a paid research call.
    """
    cached = _get_cached_research(company_id)
    if not cached:
        return None
    try:
        fetched = datetime.fromisoformat(cached["fetched_at"].replace("Z", "").replace(" ", "T"))
        age_days = max(0, (datetime.utcnow() - fetched).days)
    except (ValueError, AttributeError):
        age_days = None
    return {
        "from_cache": True,
        "fetched_at": cached["fetched_at"],
        "age_days": age_days,
        "sources_count": len(cached.get("sources", [])),
        "model": cached.get("model"),
        "cost_usd": 0.0,  # reusing cache = free
    }


def get_or_research_company(job_ctx: dict, *, model: str = DEFAULT_MODEL, force_refresh: bool = False) -> dict:
    """Return cached research if fresh, else run a new research call and persist."""
    if not force_refresh:
        cached = _get_cached_research(job_ctx["company_id"])
        if cached:
            return cached
    fresh = _research_company(job_ctx, model=model)
    _save_research(
        job_ctx["company_id"],
        fresh["research"],
        fresh["sources"],
        fresh["model"],
        fresh["cost_usd"],
        fresh["search_count"],
    )
    return fresh


# ── Stage 2: compose per slant ────────────────────────────────────────

def _compose_system_prompt(kit: dict, slant_id: str) -> str:
    slant = kit["slants"][slant_id]
    kit_blob = yaml.safe_dump(
        {k: kit[k] for k in ("name", "openers", "blocks", "bridges", "ctas", "signoffs", "ps_options", "subject", "voice_rules")},
        sort_keys=False, allow_unicode=True, width=200,
    )
    priors = _load_priors()
    priors_block = f"\n## Past-performance priors (auto-generated from outcomes + edits)\n{priors}\n" if priors else ""
    return f"""You are drafting an outreach message in Pratyush Paul's voice for a job he has ALREADY APPLIED to. The recipient is a leader at the company — Pratyush will personalize the greeting himself, so leave "Hey [Name]," as the greeting placeholder.

## Slant for THIS variant: {slant['label']}

- Lead identity:    {slant['lead_identity']}
- Preferred blocks: {', '.join(slant['blocks_preferred'])}
- Why-paragraph:    {slant['why_structure']}
- Word target:      {slant['word_target']} words
- HARD CAP:         145 words for the body (excluding "Hey [Name]," and the "Regards,\\nPratyush Paul" signoff).
                    Count your words. If you reach 140, stop and trim before adding anything else.
                    The `word_count` you return MUST be ≤ 145. Drafts over 145 are unusable.

The composer chooses blocks to honor this slant. Other slants exist; you are NOT producing those.

## Anatomy

1. Opener (1 sentence) — use the `applied_short` opener, substituting the role.
2. About-me paragraph (2-4 sentences) — assembled from the slant's preferred blocks, paraphrased to hit word target. Block IDENTITY matters; exact phrasing is a guidepost, not a script.
3. Why-this-company paragraph (2-4 sentences) — use the COMPANY RESEARCH JSON below (already fetched, do NOT call any tools). Name 1-3 specific facts. Match the why-structure for this slant.
4. CTA (1 sentence) from `ctas`.
5. Signoff + name.

## Voice rules

{chr(10).join('  - ' + r for r in kit.get('voice_rules', []))}
{priors_block}
## Kit (paraphrase freely; honor identity, not script)

```yaml
{kit_blob}
```

## Output

Return STRICT JSON only — no markdown fences, no preamble:

{{
  "subject": "Pratyush Paul | <credential> — <action>",
  "body": "Hey [Name],\\n\\n<opener>\\n\\n<about-me>\\n\\n<why-this-company>\\n\\n<cta>\\n\\nRegards,\\nPratyush Paul",
  "word_count": <int, body excluding the 'Hey [Name],' line and signoff>,
  "blocks_chosen": ["consulting", "llm_builder", ...],
  "why_angle": "one-sentence summary of the why-paragraph angle",
  "sources_used": ["url1", "url2"],
  "edit_suggestions": ["specific suggestion 1", "specific suggestion 2"]
}}
"""


def _compose_variant(job_ctx: dict, research_payload: dict, slant_id: str, kit: dict, *, model: str = DEFAULT_MODEL) -> dict:
    est = budget.estimate_cost(model, 4000, 800, 0)
    budget.check(est)

    jd = (job_ctx.get("jd_text") or "").strip()
    if len(jd) > JD_TRUNCATE:
        jd = jd[:JD_TRUNCATE] + "\n[...JD truncated...]"

    user_msg = (
        f"Compose a variant for slant `{slant_id}`.\n\n"
        f"## Job\n"
        f"  Role:       {job_ctx['title']}\n"
        f"  Company:    {job_ctx['company']}\n"
        f"  Vertical:   {job_ctx.get('vertical') or '(unknown)'}\n"
        f"  Stage:      {job_ctx.get('stage') or '(unknown)'}\n"
        f"  Headcount:  {job_ctx.get('headcount_range') or '(unknown)'}\n\n"
        f"## Company research (use this — do NOT run any tools)\n```json\n{json.dumps(research_payload['research'], indent=2)}\n```\n\n"
        f"## Sources available (cite the urls you actually use)\n{json.dumps(research_payload.get('sources', []), indent=2)}\n\n"
        f"## JD\n---\n{jd or '(no JD on file)'}\n---\n\n"
        f"Return strict JSON per schema. Honor the word target for this slant."
    )
    resp = _post_messages({
        "model": model,
        "max_tokens": 2048,
        "system": _compose_system_prompt(kit, slant_id),
        "messages": [{"role": "user", "content": user_msg}],
    })
    text, _citations, _ = _extract_final_text(resp)
    payload = _parse_json_payload(text)
    payload["model"] = model
    payload["slant"] = slant_id
    payload["cost_usd"] = budget.compute_actual_cost(model, resp.get("usage", {}), 0)
    payload["usage"] = resp.get("usage", {})
    return payload


# ── Slant auto-selection ──────────────────────────────────────────────

_AI_VERTICAL_HINTS = ("ai", "ml", "llm", "foundation", "data", "agent")
_MARKETPLACE_HINTS = ("marketplace", "two-sided", "consumer", "platform", "gig", "supply")
_PARTNERSHIP_HINTS = ("partnership", "alliance", "bd ", "business development")
_STRATEGY_HINTS = ("strategy", "strategic", "corp dev", "corporate development", "finance")


def _auto_select_slants(job_ctx: dict, kit: dict) -> list[str]:
    """Pick 2 slants based on role title + company vertical.

    Heuristic-only; the model itself doesn't see this — it just sees its
    assigned slant. Future: bias by Bayesian priors from past outcomes.
    """
    title = (job_ctx.get("title") or "").lower()
    vert = (job_ctx.get("vertical") or "").lower()
    company = (job_ctx.get("company") or "").lower()
    blob = f"{title} {vert} {company}"

    is_ai = any(h in blob for h in _AI_VERTICAL_HINTS)
    is_marketplace = any(h in blob for h in _MARKETPLACE_HINTS)
    is_partnership = any(h in title for h in _PARTNERSHIP_HINTS)
    is_strategy = any(h in title for h in _STRATEGY_HINTS) and "operations" not in title

    picks: list[str] = []
    if is_ai:
        picks.append("builder")
    if is_marketplace:
        picks.append("operator")
    if is_partnership:
        picks.append("operator")  # marketplace block is the partnerships-credibility lead
    if is_strategy:
        picks.append("analyst")
    # Always include Tight as a foil unless we already have a tight-y pair.
    if "tight" not in picks and len(picks) < 2:
        picks.append("tight")
    # Fallback to kit default
    if len(picks) < 2:
        for s in kit.get("default_slants", ["builder", "tight"]):
            if s not in picks:
                picks.append(s)
            if len(picks) == 2:
                break
    return picks[:2]


# ── Orchestration ─────────────────────────────────────────────────────

def generate_variants(job_id: int, *, slants: list[str] | None = None, model: str = DEFAULT_MODEL) -> dict:
    """Run research (or hit cache) then compose 2 variants. Persist as siblings.

    Returns:
        {variant_group_id, slants, research_from_cache, drafts: [draft_dict, ...], cost_breakdown}
    """
    ctx = _fetch_job_context(job_id)
    if not ctx:
        raise ValueError(f"job_id {job_id} not found")
    kit = _load_kit()

    if not slants:
        slants = _auto_select_slants(ctx, kit)
    # Validate slants
    for s in slants:
        if s not in kit["slants"]:
            raise ValueError(f"unknown slant: {s}")

    research_payload = get_or_research_company(ctx, model=model)

    variant_group_id = str(uuid.uuid4())
    drafts = []
    # Compose variants serially. Each compose call carries ~15K input tokens
    # (system prompt + research blob + kit + job ctx); two in parallel collide
    # with Anthropic's 30K-input-tokens-per-minute rate limit on Sonnet 4.6.
    # Research is done once above and shared into both calls — not re-fetched.
    for slant_id in slants:
        try:
            payload = _compose_variant(ctx, research_payload, slant_id, kit, model=model)
        except Exception as e:
            # Surface stack trace in server log; users of the API only see the short string.
            log.error("compose failed (job_id=%s slant=%s): %s\n%s", job_id, slant_id, e, traceback.format_exc())
            drafts.append({"slant": slant_id, "error": f"{type(e).__name__}: {e}"})
            continue
        try:
            payload["job_id"] = job_id
            payload["variant_group_id"] = variant_group_id
            payload["company"] = ctx["company"]
            payload["role_title"] = ctx["title"]
            payload["draft_id"] = _save_draft(payload, sources=research_payload.get("sources", []))
            drafts.append(payload)
        except Exception as e:
            log.error("save failed (job_id=%s slant=%s): %s\n%s", job_id, slant_id, e, traceback.format_exc())
            drafts.append({"slant": slant_id, "error": f"save: {type(e).__name__}: {e}"})

    return {
        "variant_group_id": variant_group_id,
        "slants": slants,
        "research_from_cache": research_payload.get("from_cache", False),
        "research_cost_usd": 0.0 if research_payload.get("from_cache") else research_payload.get("cost_usd", 0.0),
        "compose_cost_usd": sum((d.get("cost_usd") or 0) for d in drafts if isinstance(d, dict)),
        "drafts": drafts,
    }


def recompose_variant(draft_id: int, *, slant: str, model: str = DEFAULT_MODEL) -> dict:
    """Replace a single existing draft's content with a fresh compose using the
    new slant. Preserves draft_id and variant_group_id so the sibling variant
    in the same group stays untouched on screen. Research is loaded from cache
    if available (typically hot since the company was just researched).

    Returns the updated draft payload (same shape as _compose_variant + db keys).
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT job_id, variant_group_id FROM outreach_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"draft_id {draft_id} not found")
        job_id, variant_group_id = row[0], row[1]
    finally:
        conn.close()

    ctx = _fetch_job_context(job_id)
    if not ctx:
        raise ValueError(f"job_id {job_id} no longer exists for draft {draft_id}")
    kit = _load_kit()
    if slant not in kit["slants"]:
        raise ValueError(f"unknown slant: {slant}")

    research_payload = get_or_research_company(ctx, model=model)
    payload = _compose_variant(ctx, research_payload, slant, kit, model=model)

    reasoning = {
        "blocks_chosen": payload.get("blocks_chosen", []),
        "why_angle": payload.get("why_angle"),
        "sources": research_payload.get("sources", []),
        "sources_used": payload.get("sources_used", []),
        "edit_suggestions": payload.get("edit_suggestions", []),
        "usage": payload.get("usage", {}),
    }
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            UPDATE outreach_drafts SET
                subject = ?, body = ?, original_body = ?, reasoning_json = ?,
                model = ?, word_count = ?, slant = ?, cost_usd = ?,
                edited = 0, edit_count = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                payload.get("subject", ""),
                payload.get("body", ""),
                payload.get("body", ""),  # reset original_body to the new compose
                json.dumps(reasoning),
                payload.get("model", DEFAULT_MODEL),
                payload.get("word_count"),
                slant,
                payload.get("cost_usd"),
                draft_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    payload["draft_id"] = draft_id
    payload["job_id"] = job_id
    payload["variant_group_id"] = variant_group_id
    payload["company"] = ctx["company"]
    payload["role_title"] = ctx["title"]
    payload["slant"] = slant
    payload["research_from_cache"] = research_payload.get("from_cache", False)
    payload["research_cost_usd"] = 0.0 if research_payload.get("from_cache") else research_payload.get("cost_usd", 0.0)
    return payload


def _save_draft(payload: dict, *, sources: list | None = None) -> int:
    reasoning = {
        "blocks_chosen": payload.get("blocks_chosen", []),
        "why_angle": payload.get("why_angle"),
        "sources": sources or [],
        "sources_used": payload.get("sources_used", []),
        "edit_suggestions": payload.get("edit_suggestions", []),
        "usage": payload.get("usage", {}),
    }
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            """
            INSERT INTO outreach_drafts
                (job_id, subject, body, original_body, reasoning_json, model,
                 word_count, status, variant_group_id, slant, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)
            """,
            (
                payload["job_id"],
                payload.get("subject", ""),
                payload.get("body", ""),
                payload.get("body", ""),  # original_body snapshots model output at gen time
                json.dumps(reasoning),
                payload.get("model", DEFAULT_MODEL),
                payload.get("word_count"),
                payload.get("variant_group_id"),
                payload.get("slant"),
                payload.get("cost_usd"),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ── CRUD-ish helpers for the dashboard ────────────────────────────────

def draft_counts_by_job_url() -> dict[str, int]:
    """Number of outreach ATTEMPTS per job — each variant group counts as one, plus each legacy single-draft."""
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT j.job_url,
                   COUNT(DISTINCT COALESCE(d.variant_group_id, 'legacy-' || d.id)) AS n
            FROM outreach_drafts d
            JOIN job_postings j ON j.id = d.job_id
            WHERE j.job_url IS NOT NULL
            GROUP BY j.job_url
            """
        ).fetchall()
        return {url: n for (url, n) in rows}
    finally:
        conn.close()


def list_drafts(job_id: int) -> list[dict]:
    """Return drafts for a job, ordered newest-first. Groups variants together."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM outreach_drafts WHERE job_id = ? ORDER BY created_at DESC, id DESC",
            (job_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["reasoning"] = json.loads(d.pop("reasoning_json", "{}") or "{}")
            except json.JSONDecodeError:
                d["reasoning"] = {}
            out.append(d)
        return out
    finally:
        conn.close()


def latest_variant_group(job_id: int) -> list[dict]:
    """Return all drafts in the most recently created variant group for a job."""
    all_drafts = list_drafts(job_id)
    if not all_drafts:
        return []
    target = all_drafts[0]["variant_group_id"]
    if not target:
        return [all_drafts[0]]
    return [d for d in all_drafts if d["variant_group_id"] == target]


def update_draft(draft_id: int, *, body=None, subject=None, status=None) -> dict:
    sets: list[str] = []
    args: list = []
    if body is not None:
        sets += ["body = ?", "edited = 1", "edit_count = edit_count + 1"]
        args += [body]
    if subject is not None:
        sets.append("subject = ?")
        args.append(subject)
    if status:
        if status not in ("draft", "sent"):
            raise ValueError(f"invalid status: {status}")
        sets.append("status = ?")
        args.append(status)
        if status == "sent":
            sets.append("sent_at = CURRENT_TIMESTAMP")
    if not sets:
        return {"ok": True, "noop": True}
    sets.append("updated_at = CURRENT_TIMESTAMP")
    args.append(draft_id)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(f"UPDATE outreach_drafts SET {', '.join(sets)} WHERE id = ?", args)
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


def pick_winner(draft_id: int) -> dict:
    """Mark this draft as the chosen variant in its group; clears is_winner on siblings."""
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT variant_group_id FROM outreach_drafts WHERE id = ?", (draft_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "draft not found"}
        group = row[0]
        if group:
            conn.execute("UPDATE outreach_drafts SET is_winner = 0 WHERE variant_group_id = ?", (group,))
        conn.execute("UPDATE outreach_drafts SET is_winner = 1 WHERE id = ?", (draft_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def set_outcome(draft_id: int, outcome: str, notes: str | None = None) -> dict:
    if outcome not in ("response", "no_response", None, ""):
        raise ValueError(f"invalid outcome: {outcome}")
    conn = sqlite3.connect(DB_PATH)
    try:
        if outcome in (None, ""):
            conn.execute(
                "UPDATE outreach_drafts SET outcome = NULL, outcome_at = NULL, outcome_notes = NULL WHERE id = ?",
                (draft_id,),
            )
        else:
            conn.execute(
                "UPDATE outreach_drafts SET outcome = ?, outcome_at = CURRENT_TIMESTAMP, outcome_notes = ? WHERE id = ?",
                (outcome, notes, draft_id),
            )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def delete_draft(draft_id: int) -> dict:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM outreach_drafts WHERE id = ?", (draft_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def list_slants() -> list[dict]:
    kit = _load_kit()
    return [
        {"id": sid, "label": s["label"], "use_when": s.get("use_when", "")}
        for sid, s in kit.get("slants", {}).items()
    ]


# Legacy single-variant entry kept for backwards compat with the old route name.
def draft_outreach(job_id: int, model: str = DEFAULT_MODEL) -> dict:
    return generate_variants(job_id, model=model)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("job_id", type=int)
    p.add_argument("--slants", nargs="*", help="slant ids, e.g. --slants builder tight")
    p.add_argument("--opus", action="store_true")
    args = p.parse_args()
    result = generate_variants(
        args.job_id,
        slants=args.slants,
        model=OPUS_MODEL if args.opus else DEFAULT_MODEL,
    )
    print(json.dumps(result, indent=2, default=str))
