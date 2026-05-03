---
name: Helper-injection for testability — extract hard-to-force-failure branches to namespace-internal scope
description: When a code branch is gated behind a hard-to-force trigger (rename failure, EXDEV, permission denied) AND the codebase forbids mocks, extract the per-branch helper to namespace-internal scope (header-exposed) so the unit test can drive it directly. No mocks, no forcing-failure gymnastics.
type: feedback
---

When you need to test a code branch whose trigger is hard to force
portably (e.g., `rename(2)` failure requires chmod-as-root or EXDEV
cross-fs), AND the codebase convention forbids mocks (verified by Mode-A
reviewer 2026-05-03 KST: `production/RPi5/tests/` has zero mocking
framework usage), extract the per-branch helper from file-private
`static` to namespace-internal scope (declare in header, define in
.cpp). The unit test then calls the helper directly with synthetic
inputs and asserts behavior (e.g., stderr substrings via `freopen`
capture).

**Why:** Confirmed during issue#18 PR #75 Mi3 fold 2026-05-03 09:30 KST.
MF2 forensic logging path was gated behind `rename(2)` failure inside
`UdsServer::open()`. Two obvious approaches both had problems:

- **(a) Force `rename(2)` failure**: chmod-the-test-dir-to-read-only
  bypassed when the test host runs as root (CI gym); `EXDEV` cross-fs
  requires test-host filesystem layout assumptions that don't port
  across dev machines. **Fragile.**
- **(b) Mock layer**: would violate the codebase's no-mocks convention
  and require introducing doctest-compatible mocking machinery only
  for this one test. **Convention-breaking.**

**Mi3 solution**: extract `log_lstat_for_throw(path, label)` from
file-private `static` to namespace-internal scope (declared in
`production/RPi5/src/uds/uds_server.hpp`). The throw call site inside
`UdsServer::open()` calls the helper before throwing; the unit test
calls the SAME helper directly with regular-file / ENOENT / socket /
directory inputs and asserts stderr substrings. The throw call site
itself stays untested by unit; the helper that the throw delegates to
is fully testable. **No mocks. No forcing-failure gymnastics. Codebase
convention preserved.**

**How to apply:**

- Identify the smallest "leaf" function within the hard-to-test branch
  — the one whose inputs you CAN synthesize.
- If it's currently file-private `static`, promote it to
  `namespace::name` scope (declare in header, define in .cpp).
- Add a brief header comment marking it as test-injection point:
  `// Namespace-internal helper exposed for direct unit testing —
  see tests/test_X.cpp`.
- The throw / propagate / abort call site that USES the helper stays
  untested at unit level; the helper is fully tested.
- Document in the plan / commit message which test calls the helper
  directly so future maintainers see the testability seam.

**When it works:**

- The branch's behavior is observable through the helper's outputs
  (stderr, return value, side effect on disk).
- The helper has bounded inputs you can construct in a tmp_path test.
- The codebase has zero / few mocks already (preserve convention).

**When it doesn't:**

- The branch is a control-flow leaf with NO observable extractable
  helper (just a single `throw`). In that case, the branch may
  legitimately go untested at unit level; pin the integration test
  instead.
- The codebase already uses mocks heavily; just mock and move on.

**Generalizable:** same pattern applies to any "I want to test this
branch but the trigger is hard to force" case — file-system errors,
network errors, permission errors, race-condition windows. Extract +
test directly + leave the trigger site untested at unit level.

**See also:** Mode-A's Mi3 fold in
`.claude/tmp/plan_issue_18_uds_bootstrap_audit.md` documents the full
reasoning chain.
