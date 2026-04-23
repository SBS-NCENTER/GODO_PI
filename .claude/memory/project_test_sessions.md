---
name: Test-session naming convention
description: How field-test data is archived under `/prototype/Python/out/TS<N>/`, and what each session ID maps to physically.
type: project
---

Phase 1 field-test data is archived under `<repo-root>/prototype/Python/out/TS<N>/` with `data/` + `logs/` + `analysis/` + `README.md` subtree. Each `TS<N>` is a distinct test session (location + setup).

**Why**: the user picks short numeric session IDs over descriptive names because reviewing / re-analyzing historic sessions by ID is faster than by prose location.

**How to apply**: when the user refers to "TS4" etc., resolve against this mapping; when starting a new field session, create the next `TS<N+1>` folder and include the physical location in the session README.

## Bring-up area (not a test session)

`<repo-root>/production/RPi5/out/<ts>_<tag>/` is the **bring-up archive** on
the RPi 5 host. It holds ad-hoc `godo_smoke` captures that have NOT yet
been promoted to a formal `TS<N>`. Contents are gitignored.

Promote a captured run to a real session via
`production/RPi5/scripts/promote_smoke_to_ts.sh <smoke-dir> TS<N> "<note>"`
— this moves the directory to `<repo-root>/test_sessions/TS<N>/` and
appends a `## Promotion` block to its session log.

Do not conflate the two locations: `production/RPi5/out/` = scratch /
bring-up; `prototype/Python/out/TS<N>/` and `<repo-root>/test_sessions/TS<N>/`
= versioned test sessions.

## Session ID map

| ID | Date | Location | Setup | Purpose |
| --- | --- | --- | --- | --- |
| TS4 | 2026-04-21 | Windows dev bench (home/office) | C1 on bench, static | First hardware smoke + SDK/Non-SDK parity + reflector-tape baseline |
| TS5 | (planned) | **부조정실 (sub-control-room / chroma studio)** — the production environment | Studio set with chroma walls, crane base area | Full reflector sweep (distance × angle) + chroma-wall NIR reflectivity measurement |

The "부조정실" is the physical production studio where the SHOTOKU crane lives; TS5 is how we refer to any dataset captured there. This is the environment the whole system is being built for.
