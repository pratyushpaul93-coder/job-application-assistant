# tools/

One-off, human-run scripts. Use this directory for ad-hoc utilities, data
explorations, and migrations you intend to run by hand and then forget about.

Rules:

- Anything here may be deleted at any time without notice.
- Do **not** import from `tools/` in `scripts/`. Production code in `scripts/`
  must not depend on anything under `tools/`.
- Prefer copying a snippet into a script in `scripts/` over reaching across
  the boundary.
- If a tool here graduates into something we run regularly, promote it into
  `scripts/` (with tests) rather than leaving it here.
