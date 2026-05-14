#!/bin/bash
# apply_keys_refactor.sh
# =====================
# Patches tailor.py, dashboard.py, ats_matcher.py, ats_scout_getro_match_new.py
# to use scripts/keys.py for API key loading.
#
# Idempotent: safe to re-run. Skips files that already have the new import.
# Creates .bak.YYYYMMDD-HHMMSS backups of every modified file.
#
# Run from project root:  bash tools/apply_keys_refactor.sh

set -euo pipefail

PROJECT_ROOT="/root/pp-jobapp"
SCRIPTS="${PROJECT_ROOT}/scripts"
TS=$(date +%Y%m%d-%H%M%S)

cd "${PROJECT_ROOT}"

# Sanity: keys.py must already exist
if [ ! -f "${SCRIPTS}/keys.py" ]; then
    echo "ERROR: ${SCRIPTS}/keys.py not found. SCP it first."
    exit 1
fi

# Sanity: keys.py works
echo "=== Sanity check: scripts/keys.py ==="
python3 "${SCRIPTS}/keys.py"
echo ""

backup() {
    local file="$1"
    cp "${file}" "${file}.bak.${TS}"
    echo "  backup: ${file}.bak.${TS}"
}

already_patched() {
    grep -q "from keys import" "$1" 2>/dev/null
}

# ---------------------------------------------------------------------------
# 1. tailor.py — replace get_api_key() with keys.get_anthropic_key
#    Also fix the bug where openclaw.json is loaded then thrown away (line 26).
# ---------------------------------------------------------------------------
TAILOR="${SCRIPTS}/tailor.py"
echo "=== Patching tailor.py ==="
if already_patched "${TAILOR}"; then
    echo "  already patched, skipping"
else
    backup "${TAILOR}"
    python3 << PYEOF
import re

path = "${TAILOR}"
with open(path) as f:
    src = f.read()

# Replace the buggy get_api_key() function with import + alias
old = '''def get_api_key():
    try:
        cfg = json.load(open("/root/.openclaw/openclaw.json"))
        return json.load(open("/root/.openclaw/agents/job-scout/auth-profiles.json")).get("profiles",{}).get("anthropic:default",{}).get("key","")
    except:
        return ""'''

new = '''from keys import get_anthropic_key as get_api_key'''

if old in src:
    src = src.replace(old, new)
    with open(path, "w") as f:
        f.write(src)
    print("  replaced get_api_key() with import alias")
else:
    print("  ERROR: did not find expected get_api_key() block. Manual review needed.")
    exit(1)
PYEOF
fi
echo ""

# ---------------------------------------------------------------------------
# 2. dashboard.py — line 313-314 inline JSON load -> keys.get_anthropic_key
#    NOTE: line 600's reference to "auth-profiles" / "openclaw.json" is in a
#    safety blocklist (do NOT touch).
# ---------------------------------------------------------------------------
DASH="${SCRIPTS}/dashboard.py"
echo "=== Patching dashboard.py ==="
if already_patched "${DASH}"; then
    echo "  already patched, skipping"
else
    backup "${DASH}"
    python3 << PYEOF
import re

path = "${DASH}"
with open(path) as f:
    lines = f.readlines()

# Find the two lines (313-314 in current rev) that read auth-profiles inline
patched = False
for i, line in enumerate(lines):
    if 'cfg = json.load(open("/root/.openclaw/openclaw.json"))' in line:
        # Look at next line for the auth-profiles read
        if i + 1 < len(lines) and 'auth-profiles.json' in lines[i+1]:
            indent = re.match(r'^(\s*)', line).group(1)
            # Replace both lines with single call
            lines[i]   = f"{indent}api_key = get_anthropic_key()\n"
            lines[i+1] = ""
            patched = True
            break

if not patched:
    print("  ERROR: did not find expected JSON-load pattern. Manual review needed.")
    exit(1)

# Add import at top - find last 'import' or 'from' line in the first 50 lines
import_inserted = False
for i in range(min(50, len(lines))):
    if lines[i].startswith("from ") or lines[i].startswith("import "):
        last_import = i

# Insert after last import in header
lines.insert(last_import + 1, "from keys import get_anthropic_key\n")

with open(path, "w") as f:
    f.writelines(lines)
print(f"  patched inline JSON loader and added 'from keys import get_anthropic_key'")
PYEOF
fi
echo ""

# ---------------------------------------------------------------------------
# 3. ats_matcher.py — replace get_deepseek_key() with import alias
# ---------------------------------------------------------------------------
MATCHER="${SCRIPTS}/ats_matcher.py"
echo "=== Patching ats_matcher.py ==="
if already_patched "${MATCHER}"; then
    echo "  already patched, skipping"
else
    backup "${MATCHER}"
    python3 << PYEOF
path = "${MATCHER}"
with open(path) as f:
    src = f.read()

old = """def get_deepseek_key():
    try:
        cfg = json.load(open('/root/.openclaw/openclaw.json'))
        return cfg.get('models', {}).get('providers', {}).get('deepseek', {}).get('apiKey', '')
    except Exception:
        return ''"""

new = """from keys import get_deepseek_key"""

if old in src:
    src = src.replace(old, new)
    with open(path, "w") as f:
        f.write(src)
    print("  replaced get_deepseek_key() with import")
else:
    print("  ERROR: did not find expected get_deepseek_key() block. Manual review needed.")
    exit(1)
PYEOF
fi
echo ""

# ---------------------------------------------------------------------------
# 4. ats_scout_getro_match_new.py — same as ats_matcher.py
#    (BACKLOG #1 plans to archive this script, but patch for consistency.)
# ---------------------------------------------------------------------------
SCOUT_MATCH="${SCRIPTS}/ats_scout_getro_match_new.py"
echo "=== Patching ats_scout_getro_match_new.py ==="
if already_patched "${SCOUT_MATCH}"; then
    echo "  already patched, skipping"
else
    backup "${SCOUT_MATCH}"
    python3 << PYEOF
path = "${SCOUT_MATCH}"
with open(path) as f:
    src = f.read()

old = """def get_deepseek_key():
    try:
        cfg = json.load(open("/root/.openclaw/openclaw.json"))
        return cfg.get("models", {}).get("providers", {}).get("deepseek", {}).get("apiKey", "")
    except Exception:
        return \"\""""

new = """from keys import get_deepseek_key"""

if old in src:
    src = src.replace(old, new)
    with open(path, "w") as f:
        f.write(src)
    print("  replaced get_deepseek_key() with import")
else:
    # The double quotes vs single quotes might differ - try a regex fallback
    import re
    pattern = re.compile(
        r'def get_deepseek_key\(\):\s*\n'
        r'\s*try:\s*\n'
        r'\s*cfg = json\.load\(open\(["\']\/root/\.openclaw/openclaw\.json["\']\)\)\s*\n'
        r'\s*return cfg\.get\(["\']models["\'].*?\)\s*\n'
        r'\s*except Exception:\s*\n'
        r'\s*return ["\']{2}',
        re.DOTALL,
    )
    new_src, count = pattern.subn("from keys import get_deepseek_key", src)
    if count == 1:
        with open(path, "w") as f:
            f.write(new_src)
        print("  replaced via regex (1 match)")
    else:
        print(f"  ERROR: did not find expected pattern (matches={count}). Manual review needed.")
        exit(1)
PYEOF
fi
echo ""

# ---------------------------------------------------------------------------
# Final smoke test: import each module to catch syntax errors immediately
# ---------------------------------------------------------------------------
echo "=== Smoke test: import each patched module ==="
cd "${SCRIPTS}"
for mod in tailor dashboard ats_matcher ats_scout_getro_match_new keys; do
    if python3 -c "import ${mod}" 2>/dev/null; then
        echo "  ${mod}: import OK"
    else
        echo "  ${mod}: IMPORT FAILED"
        python3 -c "import ${mod}" 2>&1 | tail -5
    fi
done

echo ""
echo "=== All patches applied ==="
echo "Backups saved with suffix .bak.${TS}"
echo "If anything breaks, restore with:"
echo "  for f in ${SCRIPTS}/*.bak.${TS}; do mv \"\$f\" \"\${f%.bak.${TS}}\"; done"
