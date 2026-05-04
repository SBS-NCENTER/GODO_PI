# Pristine baseline + derived-pair pattern (Project)

> Established 2026-05-04 KST as part of issue#28 (B-MAPEDIT-3 close).
> Operator-locked spec → see `project_map_edit_origin_rotation.md` for the
> origin/rotation surface; this memory pins the *pattern* itself for ALL
> future map-mutation work.

## Rule

Every map slot has exactly **one immutable pristine pair** plus zero or
more **derived pairs**. The pristine pair is written once at mapping
time and is **never** modified afterwards. Every Map Edit Apply (Coord
mode, Erase mode, future modes) reads the pristine baseline as input
and emits a NEW derived pair as output. Derived pairs are
chronologically ordered, immutable once written, and never used as
inputs to subsequent edits.

```text
maps/
  ├─ studio_v1.pgm                                  ← pristine (immutable)
  ├─ studio_v1.yaml                                 ← pristine (immutable)
  ├─ studio_v1.20260504-103412-wallcal01.pgm        ← derived #1
  ├─ studio_v1.20260504-103412-wallcal01.yaml
  ├─ studio_v1.20260504-141055-tvshift.pgm          ← derived #2
  └─ studio_v1.20260504-141055-tvshift.yaml
```

Filename grammar (regex `DERIVED_NAME_REGEX` in
`godo-webctl/constants.py`):
`<base>.YYYYMMDD-HHMMSS-<memo>.{pgm,yaml}`. Memo is filesystem-safe
(`^[A-Za-z0-9_-]+$`, max 32 chars). Second-resolution timestamp +
`asyncio.Lock` serialisation makes collisions practically impossible
(Mode-A M5 lock).

## Why

1. **Cumulative quality loss prevention** — Every Apply does exactly
   ONE Lanczos-3 (intent) / BICUBIC (Pillow constraint) resample of
   the pristine PGM. If the operator chains 10 derivations the
   tenth one is still 1× resampled, not 10×. Without the pristine
   baseline, image quality would compound-degrade with each edit
   (boundary pixels would jitter, occupancy semantics would drift).

2. **Operator iteration safety** — Operator can experiment with
   10 different (x_m, y_m, theta_deg) tunings without losing the
   ground truth. A bad pick is a `git rm` of one derived pair, not
   a return-trip to re-mapping.

3. **Reversibility** — Re-activating the pristine pair is a one-click
   action in the SPA map list (pristine appears as the parent row
   with derived variants indented beneath). No deletion, no recovery
   step.

4. **Audit trail** — The `YYYYMMDD-HHMMSS-<memo>` postfix
   self-documents WHY each derivation exists. The memo is the
   operator's free-text note ("wallcal01", "tvshift", "after-set-build").

## How to apply

Every NEW map-mutation feature (future Erase variants, future
geometry tweaks, future fiducial overlays) MUST:

- **Read** the pristine pair as input. Never read the latest derived.
  Pinned by `godo-webctl/tests/test_map_rotate.py::
  test_apply_reads_pristine_not_latest_derived` and integration test
  in `test_app_integration.py`.
- **Write** a new derived pair via the atomic pair-write protocol
  (PGM tmp → YAML tmp → fsync both → fsync dir → rename PGM → rename
  YAML → rollback PGM on YAML failure). See SYSTEM_DESIGN.md §13.4.
- **Never modify** the pristine bytes (`.pgm` / `.yaml`) post-mapping.
  Pinned by `tests/test_map_rotate.py::test_pristine_unchanged_after_apply`
  (byte-for-byte hash compare).
- **Use** `is_pristine(name)` (sole classifier in
  `godo-webctl/maps.py`) to distinguish pristine vs derived in any
  list/scan path.

The classifier + composer + atomic writer trio (`maps.py` +
`map_origin.py` + `map_rotate.py` + atomic-write helpers) is the
single sanctioned implementation. New mutation modules MUST extend
these, not reimplement the pattern.

## Cross-links

- `.claude/memory/project_map_edit_origin_rotation.md` — Origin pick
  + yaw rotation surface that introduced this pattern.
- `.claude/memory/feedback_subtract_semantic_locked.md` — SUBTRACT
  semantic for typed origin values (extended to yaw in issue#28).
- `SYSTEM_DESIGN.md` §13 — full pipeline narrative.
- `godo-webctl/CODEBASE.md` invariants for map_rotate / map_origin
  sole-owner discipline.
