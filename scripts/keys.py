"""
keys.py
=======
Standardized credential loader for the pp-jobapp pipeline.

This module is the single source of truth for *how* API keys are loaded.
The keys themselves are stored in two openclaw-managed config files:

  - Anthropic: /root/.openclaw/agents/job-scout/auth-profiles.json
               -> profiles."anthropic:default".key

  - DeepSeek:  /root/.openclaw/openclaw.json
               -> models.providers.deepseek.apiKey

These storage locations are owned by the openclaw tool, not by this codebase.
Do NOT move keys between files - openclaw will rewrite them on next config sync.
This module just centralizes the *reading* logic.

Usage:
    from keys import get_anthropic_key, get_deepseek_key

    anthropic_key = get_anthropic_key()
    if not anthropic_key:
        sys.exit("Anthropic key missing")

    deepseek_key = get_deepseek_key()
"""

from __future__ import annotations

import json
from typing import Optional


AUTH_PROFILES_PATH = "/root/.openclaw/agents/job-scout/auth-profiles.json"
OPENCLAW_CONFIG_PATH = "/root/.openclaw/openclaw.json"
TAVILY_KEY_PATH = "/root/.tavily/key"


def get_anthropic_key() -> str:
    """
    Read the Anthropic API key from auth-profiles.json.
    Returns empty string on any failure (matches existing convention in
    tailor.py and dashboard.py).
    """
    try:
        with open(AUTH_PROFILES_PATH) as f:
            data = json.load(f)
        return (
            data.get("profiles", {})
                .get("anthropic:default", {})
                .get("key", "")
        )
    except Exception:
        return ""


def get_deepseek_key() -> str:
    """
    Read the DeepSeek API key from openclaw.json.
    Returns empty string on any failure (matches existing convention in
    ats_matcher.py).
    """
    try:
        with open(OPENCLAW_CONFIG_PATH) as f:
            cfg = json.load(f)
        return (
            cfg.get("models", {})
               .get("providers", {})
               .get("deepseek", {})
               .get("apiKey", "")
        )
    except Exception:
        return ""


def get_tavily_key() -> str:
    """Read the Tavily search-API key from /root/.tavily/key.

    Used for URL-recovery flows where direct scraping is blocked (Built In WAF).
    Returns empty string on any failure.
    """
    try:
        with open(TAVILY_KEY_PATH) as f:
            return f.read().strip()
    except Exception:
        return ""


def get_key(provider: str) -> str:
    """
    Generic accessor by provider name. Useful for code that wants to be
    provider-agnostic.
    """
    if provider == "anthropic":
        return get_anthropic_key()
    if provider == "deepseek":
        return get_deepseek_key()
    if provider == "tavily":
        return get_tavily_key()
    return ""


# Smoke test when run directly: python3 keys.py
if __name__ == "__main__":
    a = get_anthropic_key()
    d = get_deepseek_key()
    t = get_tavily_key()
    print(f"anthropic: {'present' if a else 'MISSING'} ({len(a)} chars)")
    print(f"deepseek:  {'present' if d else 'MISSING'} ({len(d)} chars)")
    print(f"tavily:    {'present' if t else 'MISSING'} ({len(t)} chars)")
