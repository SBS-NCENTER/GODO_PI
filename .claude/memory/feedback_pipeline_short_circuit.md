---
name: Pipeline short-circuit for small + well-specified work
description: Skip planner AND Mode-B for small/well-specified config-only or single-file work; direct writer + Parent self-verify is sufficient
type: feedback
---

For small + well-specified work (≤200 LOC, single concern, design surface fully captured by the existing SSOT — SYSTEM_DESIGN.md, CODEBASE.md, prior plan amendments), use the abbreviated pipeline: **direct writer → Parent self-verify → commit**. Skip planner. Skip Reviewer Mode-B.

**Why:** Confirmed twice this session — Phase 4-2 C deadband filter (50 LOC + tests, fully specified by SYSTEM_DESIGN.md §6.4.1) and Phase 4-2 systemd carry (3 unit files + helper script + install README, fully specified by the prior phase's design decisions). Both delivered cleanly without the full planner+reviewer roundtrip. Running the full pipeline would have wasted ~30-40 minutes per phase with little caught — Mode-A had nothing new to flag, Mode-B's likely findings would have been style nits already covered by the writer's diligence.

**How to apply:**
- **Use full pipeline (planner → Mode-A → writer → Mode-B)** when: feature-scale work touches multiple modules, design surface has open decisions (new Config keys, API shape changes, threading additions), OR the user explicitly asks for it. Examples: Phase 4-2 B AMCL port, Phase 4-2 D Live mode, Phase 4-3 webctl.
- **Use abbreviated pipeline (direct writer → Parent self-verify)** when: single-module changes, fully-specified design (SSOT-driven), config-only or install-only work, doc-only work, or housekeeping. Examples: Phase 4-2 C deadband, Phase 4-2 systemd carry, post-Mode-B fold commits.
- **Hybrid**: planner skipped but Mode-B run when output quality is uncertain (new pattern, unfamiliar territory). Did NOT happen this session, but valid.
- Parent's self-verify in abbreviated mode: read the writer's diff manually, run the build/test gates yourself, commit. Do not rubber-stamp.
