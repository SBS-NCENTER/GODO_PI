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

## Broadcaster naming — TS vs ST

In this broadcaster's terminology, two paired prefixes describe a production room set:

- **TS<N>** = **부조정실 N** (Sub-Control Room N) — the room with the controllers, switchers, and (for GODO) the RPi 5 deployment.
- **ST-<N>** = **스튜디오 N** (Studio N) — the physical studio where cameras and the SHOTOKU crane operate.

A matching number means the rooms are paired: **TS5 ↔ ST-5** is a single SCR + Studio set. GODO's hardware lives in BOTH rooms — the RPi 5 sits in TS5, the LiDAR + crane sit in ST-5, connected by cable.

## Session ID map

| ID | Points to | Notes |
| --- | --- | --- |
| TS4 | Windows dev bench (home/office) — NOT a TV station location | First hardware smoke + SDK/Non-SDK parity + reflector-tape baseline (2026-04-21). The "TS" prefix here predates the broadcaster convention and is grandfathered |
| TS5 | **부조정실 5** (Sub-Control Room 5). Paired with **ST-5** (Studio 5). RPi 5 `news-pi01` is deployed in TS5 | All GODO measurements collected at this site land here, regardless of whether the sensor sits in TS5 (RPi 5 itself, e.g. RT jitter) or in ST-5 (LiDAR + crane). Already populated 2026-04-25 with `jitter_summary.md`. Future: reflector sweep, chroma-wall NIR, post-IRQ-pinning re-measurement, Phase 5 long-run |

The directory `<repo-root>/test_sessions/TS<N>/` is **the location's archive**, not "one dataset". It grows topic files (`jitter_summary.md`, `reflector_sweep.csv`, `chroma_nir.md`, ...) over time. Non-LiDAR measurements (RT jitter, etc.) go here too — `prototype/Python/out/` is reserved only for Phase 1 / 2 raw LiDAR data.
