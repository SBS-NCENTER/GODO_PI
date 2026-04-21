---
name: Test-session naming convention
description: How field-test data is archived under `/Python/out/TS<N>/`, and what each session ID maps to physically.
type: project
---

Phase 1 field-test data is archived under `C:\Users\User\Desktop\GODO\Python\out\TS<N>\` with `data/` + `logs/` + `analysis/` + `README.md` subtree. Each `TS<N>` is a distinct test session (location + setup).

**Why**: the user picks short numeric session IDs over descriptive names because reviewing / re-analyzing historic sessions by ID is faster than by prose location.

**How to apply**: when the user refers to "TS4" etc., resolve against this mapping; when starting a new field session, create the next `TS<N+1>` folder and include the physical location in the session README.

## Session ID map

| ID | Date | Location | Setup | Purpose |
| --- | --- | --- | --- | --- |
| TS4 | 2026-04-21 | Windows dev bench (home/office) | C1 on bench, static | First hardware smoke + SDK/Non-SDK parity + reflector-tape baseline |
| TS5 | (planned) | **부조정실 (sub-control-room / chroma studio)** — the production environment | Studio set with chroma walls, crane base area | Full reflector sweep (distance × angle) + chroma-wall NIR reflectivity measurement |

The "부조정실" is the physical production studio where the SHOTOKU crane lives; TS5 is how we refer to any dataset captured there. This is the environment the whole system is being built for.
