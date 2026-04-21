---
name: CLAUDE.md stays concise (guide, not encyclopedia)
description: In the GODO project, CLAUDE.md is a short guide; detailed analyses and specs live in separate reference docs with back-links
type: feedback
---

Do **not** accumulate long analyses, specifications, or research results inside `CLAUDE.md`. It is a guide. Push detail into dedicated reference documents and link to them from `CLAUDE.md`.

**Why**: On 2026-04-20 the user said explicitly, "It's a guidebook; I'd rather have long content split into separate reference docs." For example, the Phase 0 RPLIDAR C1 analysis was moved out of `CLAUDE.md` into `RPLIDAR/RPLIDAR_C1.md`.

**How to apply**:

- `CLAUDE.md` covers only: goals, architecture overview, phases, directory structure, design principles. High-level why/how.
- Spec tables, binary protocols, benchmarks, trade-off analyses → a dedicated `/<topic>/<topic>.md` file, linked from `CLAUDE.md §9` (reference documents).
- If `§9` itself starts to sprawl, propose a reorganization pass to the user rather than adding another bullet.
