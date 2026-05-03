---
name: Build-grep allow-list narrowing over regex weakening
description: When a build-gate guard (regex grep) catches a legitimate use of the same syntactic pattern in a different domain, prefer extending the allow-list with named per-file rationale comments over weakening the regex. Single-point-of-strict + named exceptions.
type: feedback
---

When a `production/RPi5/scripts/build.sh` build-gate grep (e.g.,
`[atomic-toml-write-grep]`, `[hot-path-isolation-grep]`,
`[hot-config-publisher-grep]`) catches a legitimate use of the SAME
syntactic pattern in a DIFFERENT domain than the gate's intended
discipline, the right fix is to extend the gate's per-file allow-list
with a rationale comment — NOT to relax the regex.

**Why:** Confirmed during issue#18 PR #75 Writer's plan deviation
2026-05-03 KST. The `[atomic-toml-write-grep]` gate exists to discipline
`production/RPi5/src/config/atomic_toml_writer.cpp`'s `mkstemp + fsync
+ rename` write pattern. PR #73 introduced the SAME `mkstemp/rename`
pattern in `production/RPi5/src/uds/uds_server.cpp` for the UDS
atomic-rename of `ctl.sock` (a SOCKET path, completely unrelated to
TOML). The grep falsely matched the UDS code; build broke. Two correct
responses:

- **(a) Tighten the regex to be TOML-specific** (e.g., add `\.toml`
  context check) — fragile because the grep would need to know about
  every file pattern that uses TOML. Easy to miss future TOML files.
- **(b) Extend the allow-list with a one-file rationale comment**:
  `# atomic_toml_writer.cpp + uds/uds_server.cpp (UDS ctl.sock atomic-rename)`
  with a comment line explaining why uds_server.cpp is allowed despite
  the syntactic match.

**Option (b) chosen**, accepted by Mode-B as inline scope. Narrow,
single-file allow, well-documented. The TOML discipline regex stays
strict; UDS gets a named exception.

**How to apply:**

- When a build-gate fires on legitimate code, FIRST ask: does the
  caught code legitimately use the same syntactic pattern for a
  different purpose?
- If yes → extend the allow-list (per-file path with a one-line
  rationale comment in the script).
- If no → the gate caught a real discipline violation; fix the code
  per the gate's intent.
- Do NOT weaken the regex. The gate's STRICTNESS is its value; allow-list
  exceptions are NAMED so future readers can see the rationale.
- Document the allow-list extension in the commit message / PR body
  as a deliberate scope creep so reviewers see it explicitly.

**When this is wrong (use regex tightening instead):**

- The gate fires on >2-3 legitimate cases — at that point the regex
  itself is too loose and the discipline isn't actually being captured.
  Tighten the regex to be more specific.
- The gate's intent applies to ALL files that match the pattern (not
  just one specific file's discipline). E.g., a "no malloc in hot path"
  grep should catch malloc anywhere in the hot-path code; that's the
  point.

**Generalizable lesson:** SSOT principle for build gates — the
DISCIPLINE is the SSOT, the regex is the implementation. When the
implementation over-matches, refine the implementation by exclusion
(allow-list) not by relaxation (regex weakening). Single-point-of-strict
preserves the discipline; named exceptions absorb the syntactic overlap
between unrelated domains.

**See also:** the same pattern applies in webctl Pydantic validators
(strict bounds + per-field documented exceptions) and frontend type
narrowing (strict types + named cast points). Discipline first, escape
hatch named.
