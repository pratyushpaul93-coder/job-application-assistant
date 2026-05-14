#!/usr/bin/env python3
"""Daily-spend gate for outreach drafting.

After the 2026-05-04 $13 web-search incident, every outreach API call is
gated by a daily-spend cap. Sums today's research-cache + draft cost_usd
columns and refuses new calls past the cap.

Limit is intentionally low for a single-user dashboard. Bump in env if
multi-variant testing in a batch needs more headroom.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime

DB_PATH = "/root/pp-jobapp/workspace/jobapp.db"
DAILY_CAP_USD = float(os.environ.get("OUTREACH_DAILY_CAP_USD", "5.00"))


def today_spend_usd(conn: sqlite3.Connection | None = None) -> float:
    own = conn is None
    if own:
        conn = sqlite3.connect(DB_PATH)
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        draft = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM outreach_drafts WHERE substr(created_at, 1, 10) = ?",
            (today,),
        ).fetchone()[0] or 0.0
        cache = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM outreach_research_cache WHERE substr(fetched_at, 1, 10) = ?",
            (today,),
        ).fetchone()[0] or 0.0
        return float(draft) + float(cache)
    finally:
        if own:
            conn.close()


class BudgetExceeded(RuntimeError):
    pass


def check(estimated_cost_usd: float, *, conn: sqlite3.Connection | None = None) -> None:
    """Raise BudgetExceeded if today's spend plus this estimate would exceed cap."""
    spent = today_spend_usd(conn)
    if spent + estimated_cost_usd > DAILY_CAP_USD:
        raise BudgetExceeded(
            f"daily cap ${DAILY_CAP_USD:.2f} would be exceeded "
            f"(spent ${spent:.2f}, this call ~${estimated_cost_usd:.3f}). "
            f"Bump OUTREACH_DAILY_CAP_USD or wait until tomorrow."
        )


# Anthropic per-MTok pricing (USD) as of model release. Used for cost estimates;
# real cost is computed from `usage` returned by the API after each call.
PRICING = {
    "claude-sonnet-4-6": {"input": 3.0,  "output": 15.0},
    "claude-opus-4-7":   {"input": 15.0, "output": 75.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
}
WEB_SEARCH_USD = 0.01  # $10 / 1k searches


def estimate_cost(model: str, in_toks: int, out_toks: int, searches: int = 0) -> float:
    p = PRICING.get(model)
    if not p:
        return 0.0
    return (in_toks / 1_000_000) * p["input"] + (out_toks / 1_000_000) * p["output"] + searches * WEB_SEARCH_USD


def compute_actual_cost(model: str, usage: dict, searches: int = 0) -> float:
    """Compute cost from Anthropic /v1/messages usage object."""
    if not usage:
        return 0.0
    return estimate_cost(
        model,
        int(usage.get("input_tokens", 0)),
        int(usage.get("output_tokens", 0)),
        searches,
    )
