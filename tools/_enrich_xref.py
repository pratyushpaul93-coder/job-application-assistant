#!/usr/bin/env python3
"""Cross-reference enrichment_review.csv against enrichment_cache to:
  1. resolve real source (deepseek / claude_websearch / *_unverified)
  2. propose action transitions per the agreed policy
  3. print summary table
  4. (optionally) write the edited CSV with action column updated
"""
from __future__ import annotations
import argparse
import csv
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

DB_PATH  = "/root/pp-jobapp/workspace/jobapp.db"
CSV_PATH = "/root/pp-jobapp/workspace/enrichment_review.csv"

# url_enrichment exposes normalize_name; reuse for cache lookup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from url_enrichment import normalize_name  # noqa: E402


def load_cache(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name_normalized, source, confidence, head_status FROM enrichment_cache"
        ).fetchall()
    finally:
        conn.close()
    return {r[0]: {"source": r[1], "confidence": r[2], "head_status": r[3]} for r in rows}


_PUNCT_RE = re.compile(r"[^a-z0-9]")
def _slug(s: str) -> str:
    return _PUNCT_RE.sub("", s.lower())


def domain_contains_company(url: str, company_name: str) -> bool:
    if not url or not company_name:
        return False
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    if not host:
        return False
    # Strip leading www.
    host = host[4:] if host.startswith("www.") else host
    # Take the registered domain (label before TLD)
    parts = host.split(".")
    label = parts[0] if parts else host
    company_slug = _slug(company_name)
    if not company_slug:
        return False
    label_slug = _slug(label)
    full_slug  = _slug(host)
    # Require the company slug to appear in the registered label, OR for short
    # company slugs (<=4 chars) require full host match to avoid false positives.
    if len(company_slug) <= 4:
        return company_slug == label_slug
    return company_slug in label_slug or company_slug in full_slug


def head_status_ok(s) -> bool:
    try:
        n = int(s)
    except (ValueError, TypeError):
        return False
    return 200 <= n < 400


def head_status_strict_200(s) -> bool:
    try:
        return int(s) == 200
    except (ValueError, TypeError):
        return False


def propose_action(real_source: str, confidence: str, head_status,
                   url: str, company_name: str, current_action: str) -> str:
    # Rule 1: claude_websearch + high + 200..399 -> commit
    if real_source == "claude_websearch" and confidence == "high" \
            and head_status_ok(head_status):
        return "commit"
    # Rule 2: deepseek + high (any verified) -> commit
    if real_source == "deepseek" and confidence == "high" \
            and head_status_ok(head_status):
        return "commit"
    # Rule 3: claude_websearch + medium + strict 200 + domain heuristic -> commit
    if real_source == "claude_websearch" and confidence == "medium" \
            and head_status_strict_200(head_status) \
            and domain_contains_company(url, company_name):
        return "commit"
    return current_action


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--write", action="store_true",
                   help="Write the proposed actions back to the CSV")
    p.add_argument("--db",  default=DB_PATH)
    p.add_argument("--csv", default=CSV_PATH)
    args = p.parse_args()

    cache = load_cache(args.db)

    with open(args.csv) as f:
        rows = list(csv.DictReader(f))
        fieldnames = csv.DictReader(open(args.csv)).fieldnames

    # Resolve real source per row + compute proposal
    transitions = Counter()
    proposals = []
    for r in rows:
        nn = normalize_name(r["company_name"])
        c = cache.get(nn, {})
        real_source = c.get("source", "MISSING")
        # Prefer cache fields when CSV's are stale (CSV head_status comes from cache too,
        # but we re-pull to be safe)
        real_conf = c.get("confidence", r["confidence"])
        real_head = c.get("head_status")
        if real_head is None:
            real_head = r["head_status"]

        proposed = propose_action(
            real_source=real_source,
            confidence=real_conf,
            head_status=real_head,
            url=r["proposed_url"],
            company_name=r["company_name"],
            current_action=r["action"],
        )
        proposals.append((r, real_source, real_conf, real_head, proposed))
        transitions[(real_source, real_conf, r["action"], proposed)] += 1

    # Print summary table
    print("\n=== source × confidence × current_action -> proposed_action ===\n")
    print(f"{'source':32s} {'conf':8s} {'current':8s} {'proposed':9s} {'count':>6s}")
    print("-" * 70)
    flips_total = 0
    for (src, conf, cur, prop), n in sorted(transitions.items(),
                                            key=lambda kv: (-kv[1], kv[0])):
        flag = "  <-- FLIP" if cur != prop else ""
        if cur != prop:
            flips_total += n
        print(f"{src:32s} {conf:8s} {cur:8s} {prop:9s} {n:6d}{flag}")
    print("-" * 70)
    print(f"Total rows:  {len(rows)}")
    print(f"Total flips: {flips_total}")

    # Per-rule breakdown
    print("\n=== rule contribution to flips ===")
    rule_counts = Counter()
    for (r, src, conf, head, prop) in proposals:
        if r["action"] == prop:
            continue
        url = r["proposed_url"]
        cname = r["company_name"]
        if src == "claude_websearch" and conf == "high" and head_status_ok(head):
            rule_counts["R1: claude_websearch+high+2xx/3xx"] += 1
        elif src == "deepseek" and conf == "high" and head_status_ok(head):
            rule_counts["R2: deepseek+high"] += 1
        elif (src == "claude_websearch" and conf == "medium"
              and head_status_strict_200(head)
              and domain_contains_company(url, cname)):
            rule_counts["R3: claude_websearch+medium+200+domain-match"] += 1
        else:
            rule_counts["??? (unexpected)"] += 1
    for k, v in rule_counts.most_common():
        print(f"  {k:50s} {v}")

    # Sample of R3 candidates so user can sanity check the heuristic
    r3_examples = [(r, src, conf, head) for (r, src, conf, head, prop) in proposals
                   if r["action"] != prop and src == "claude_websearch"
                   and conf == "medium" and head_status_strict_200(head)
                   and domain_contains_company(r["proposed_url"], r["company_name"])]
    if r3_examples:
        print(f"\n=== R3 medium-confidence flips ({len(r3_examples)}): first 15 ===")
        for r, src, conf, head in r3_examples[:15]:
            print(f"  {r['company_name'][:30]:30s} -> {r['proposed_url']}")

    # Write if asked
    if args.write:
        out_rows = []
        for (r, src, conf, head, prop) in proposals:
            r2 = dict(r)
            r2["action"] = prop
            # Optionally overwrite the bogus 'source' column with real source
            r2["source"] = src
            out_rows.append(r2)
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(out_rows)
        new_actions = Counter(r["action"] for r in out_rows)
        print(f"\nWROTE {args.csv}")
        print(f"New action distribution: {dict(new_actions)}")


if __name__ == "__main__":
    main()
