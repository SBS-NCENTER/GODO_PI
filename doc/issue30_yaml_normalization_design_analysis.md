# issue#30 — YAML Normalization to (0, 0, 0°): Design Analysis & Lock-In

> Source session: 2026-05-04 KST late-night → twenty-third-session opening discussion.
> Status: design candidates locked at this conversation; Planner kickoff queued.
> Permanence: this document is **retained** as a reference. Do not auto-prune
> even after issue#30 ships; the meta-lesson in §10 is reusable.

## 1. Background

PR #81 (B-MAPEDIT-3, merged 2026-05-04 KST as `da78dd0`) shipped the bitmap-rotation
Apply pipeline with two semantics:

- YAML `origin` x/y: `pristine - typed` (SUBTRACT)
- YAML `origin` yaw: unchanged from pristine (Option B — yaw is baked into the bitmap, not metadata)

The operator's PICK#1 → PICK#2 cascade test that night surfaced an intent gap:

> "우리가 원점을 변경하여 적용한 맵은 새로 정렬되었을테니 현재 origin은 당연히 (0, 0, 0°)로 나와야 하는 것 아닌가요?"

PR #81's math NEVER produces YAML `origin = [0, 0, 0]`; the operator typed world
coordinates of the picked point, but those values just shifted the YAML `origin` field
by their negation, rather than re-anchoring the world frame so the picked point
becomes the new origin.

The deferred follow-up — issue#30 — captures the corrected semantic.

The initial spec memory (`.claude/memory/project_yaml_normalization_design.md`,
drafted 2026-05-04 KST late-night during PR #81 close) presented two interpretations:
(1) literal `(0, 0, 0)` with crop, (2) centred-origin no-crop. The operator's
question on twenty-third-session opening surfaced a third interpretation that
the memory had silently excluded — the cleanest path of all three.

## 2. ROS map YAML/PGM format primer (refresher)

GODO uses the standard ROS map_server pair format:

```yaml
image: <base>.pgm
mode: trinary
resolution: 0.025                                          # m/px
origin: [-4.600163, -8.599652, 1.603957582582789]          # [x_m, y_m, yaw_rad]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.196
```

PGM is netpbm P5 grayscale: pixel `0` = occupied, `205` = unknown, `254` = free.
Header is `P5\n<W> <H>\n255\n`.

### `origin` field semantics — name is misleading

`origin: [ox, oy, oθ]` is **NOT** "the world-frame coordinates of the origin point".
It is the world coordinates + yaw of the **bottom-left pixel of the bitmap**:

- pixel `(i, j)` (i=left→right, j=bottom→top) → world `(wx, wy)`:
  ```
  wx = ox + (i·cos(oθ) - j·sin(oθ)) · res
  wy = oy + (i·sin(oθ) + j·cos(oθ)) · res
  ```
- world `(wx, wy)` → pixel: solve the inverse.

This means the YAML `origin` field is just an **anchor** that pins the bottom-left
pixel to a chosen world coordinate. The world's `(0, 0)` point can land **anywhere**
in the bitmap — including outside it, including at any specific pixel — depending
on what `[ox, oy]` is set to.

GODO already exploits this freedom in pristine maps. `studio_v1.yaml` has
`origin: [-3.437, -11.518, 0]` which puts world `(0, 0)` somewhere inside the
bitmap — neither at the bottom-left pixel nor at the bitmap centre.

## 3. The "(0, 0, 0°)" intent has two layers

The operator's stated goal — "origin should be (0, 0, 0°)" — admits two readings:

| Layer | Meaning |
|---|---|
| A. Semantic origin | World `(0, 0)` sits at the picked point; no residual yaw correction remains |
| B. YAML field literal | The `origin:` line reads `[0, 0, 0]` byte-for-byte |

Layer A is the operator's actual mental model. Layer B is a YAML-serialization
choice. Satisfying both at once (B's literal `[0, 0, 0]` AND A's "world (0, 0)
at picked point") forces the picked point to be the bitmap's bottom-left pixel —
which is the cropping-prone path.

Satisfying only A allows any YAML `origin` value, as long as the picked point
lands at world `(0, 0)` when the bitmap is interpreted with that origin. **This
is what the operator actually wants.**

## 4. Three interpretations compared

Test scenario: pristine `(W=400, H=400)` at `res=0.025`. Picked point currently
at pristine pixel `(300, 200)`. Typed yaw = +30°.

### Interpretation (1) — Strict literal `(0, 0, 0)` with crop

Algorithm:
1. Rotate pristine by `-30°` (Pillow `Image.rotate`, `expand=True`).
2. Compute picked-point's new pixel after rotation.
3. Translate so picked-point lands at bottom-left `(0, 0)`.
4. Crop everything outside the upper-right quadrant.

YAML: `origin: [0, 0, 0]` — literal.
Bitmap: ~75% of studio content lost (everything in the cropped quadrants).

### Interpretation (2) — Bitmap centre = world (0, 0)

Algorithm:
1. Rotate pristine around picked-point pivot by `-30°`, expand canvas.
2. Pad symmetrically so picked-point lands at the centre of the new canvas.
3. YAML `origin = [-W_new/2 · res, -H_new/2 · res, 0]`.

YAML: `origin: [-5.0, -5.0, 0]` (example) — yaw is 0 but x/y are not.
Bitmap: no content loss; picked-point forced to centre.

### ★ Interpretation (3) — Pick-anchored + canvas-expand ("Paint-style")

Algorithm:
1. Compute picked-point's pristine pixel `(i_p, j_p)` from pristine YAML origin
   + typed `(tx, ty)`.
2. Apply affine transform around pivot `(i_p, j_p)` (rotate by `-θ`), with
   `expand=True` semantics — canvas grows to fit content + rotation overhang.
   **Requires `Image.transform` with explicit affine matrix; `Image.rotate`
   only allows centre-pivot.**
3. Compute picked-point's new pixel `(i_p', j_p')` in the expanded canvas.
4. YAML `origin = [-i_p' · res, -j_p' · res, 0]`.

YAML: `origin: [-7.5, -5.0, 0]` (example) — yaw is 0; x/y are whatever lands
`(0, 0)` on the picked-point pixel.
Bitmap: no content loss; picked-point stays visually at its pristine location;
only rotation-overhang corners are padded with `205` (unknown).

This is the operator's "그림판처럼 pan + rotate, 여분만 늘리기" intent.

### Visual comparison

```
pristine                    (1) crop                (2) centre               (3) pick-anchored

┌──────────┐                ┌──────┐                ┌──────────┐              ┌─────────────┐
│          │                │ ▓▓   │                │          │              │             │
│   ▓▓     │   →            │ ▓▓   │                │  ▓▓      │              │  ▓▓         │
│   ▓▓ ●   │                │      │                │  ▓▓ ●    │              │  ▓▓ ●       │
│          │                └──────┘                │          │              │             │
└──────────┘                                        │          │              │     padding │
                                                    └──────────┘              └─────────────┘
                            ●=bottom-left           ●=centre                  ●=natural pos
                            content cropped         padded around             rotation pad only
```

(`●` = picked point; `▓▓` = studio content)

## 5. Why (3) is the right answer — AMCL yaw-blind interaction

`.claude/memory/project_amcl_yaw_metadata_only.md` documents that AMCL's likelihood
field cell mapping (`scan_ops.cpp:84-85`) reads `origin_x_m` and `origin_y_m`
only — `origin_yaw_deg` is completely ignored by the particle filter. It is consumed
only by `apply_yaw_tripwire` (a stderr diagnostic) and `compute_offset` (output-stage
subtraction `current.yaw_deg - origin.yaw_deg`).

In Interpretation (3):

- Bitmap content is rotated → AMCL's likelihood field reflects the new world
  frame → particle filter pose adjusts.
- YAML yaw = 0 → consistent with AMCL's yaw-blind cell mapping; no hidden
  divergence.
- YAML origin x/y is the negative of the picked-point's new pixel × resolution
  → AMCL maps world `(0, 0)` to that exact pixel during cell lookup.
- Output-stage `compute_offset` becomes `current.yaw_deg - 0 = current.yaw_deg`
  → operator's FreeD-output dyaw reads cleanly in the new frame.

(3) is not a workaround for AMCL's yaw-blindness — it is the design that
**naturally aligns** with it.

## 6. Implementation delta vs PR #81

| Area | PR #81 ship | issue#30 |
|---|---|---|
| Rotation function | `Image.rotate(-θ, expand=True)` — centre pivot | `Image.transform(size, AFFINE, matrix)` — picked-point pivot |
| Canvas-size formula | `\|W·cosθ\|+\|H·sinθ\|` | Off-centre-pivot bbox: rotate the four pristine corners around picked-point, take max/min |
| YAML origin formula | `pristine - typed` (x/y); `pristine` (yaw) | `[-i_p'·res, -j_p'·res, 0]` |
| Cumulative tracking | None | Pristine baseline preserved (1× resample); cumulative `(tx, ty, θ)` from pristine stored in sidecar JSON; each Apply composes new cumulative from previous + this typed |
| Frontend numeric input UX | typed = world coord of picked-point in pristine frame | typed = incremental adjustment from current view; placeholders show `0`/empty meaning "no change" |

## 7. Locked decisions (twenty-third-session opening, 2026-05-04 KST)

| # | Topic | Lock |
|---|---|---|
| 1 | Where does the picked point land in the new bitmap | **(c) pick-anchored + canvas-expand** — operator's original intent |
| 2 | Frontend numeric input UX | Incremental: defaults are `0`/empty meaning "no change"; typed values are deltas against current view |
| 4 | PR #81-era derived map handling | Auto-migration with backup; backup file naming/relationship managed via sidecar JSON (see §9) |
| 8 | Sidecar lineage / generation tracking | Sidecar JSON includes `lineage.generation` (0 = pristine, N = N-th descendant) + `lineage.parents[]` chain. Frontend exposes via an `!`/ⓘ button on each map list item that opens a lineage tree modal |
| 9 | Atomic write protocol for derived/backup pairs | **C3-triple** — see §11. Three-file write (PGM + YAML + JSON), JSON committed last; recovery sweep reconciles orphan combinations on startup + `list_maps` |
| 10 | Filename + log timestamp convention | All operator-facing timestamps emitted by godo-webctl + godo-tracker are KST (host-local, explicit `ZoneInfo("Asia/Seoul")`). Filename forms drop the offset suffix; ISO 8601 forms carry explicit `+09:00`. See `.claude/memory/feedback_timestamp_kst_convention.md` for the full convention |

## 8. Pending decisions (deferred to Planner brief or session-end discussion)

| # | Topic | Status |
|---|---|---|
| 3 | Cumulative-tracking storage location | **Sidecar JSON** preferred per operator's §9 alignment; concrete schema (filename, fields) TBD in Planner round 1 |
| 5 | Cropping/padding policy | Moot under (c); skipped |
| 6 | `feedback_subtract_semantic_locked.md` deprecation | Discuss at session end; (c) supersedes the SUBTRACT semantic, so the lock memory needs explicit retraction or extension |
| 7 | PICK cascade equivalence regression test pin shape | Mode-A must demand: `apply(pick1) → apply(pick2)` produces visually + YAML-identical result to `apply(compose(pick1, pick2))`. Pins cumulative-composition correctness |

## 9. Adjacent concern surfaced — backup-file naming via sidecar JSON

During this conversation the operator raised a separate but related pain point:
backup map filenames carry no human-readable trace of which map they back up.
They proposed a sidecar JSON pattern that ties backup files to their source map.

This pattern aligns naturally with the cumulative-tracking sidecar in §8 #3.
A unified sidecar JSON schema across both use cases is a candidate Planner
deliverable. Out of issue#30's strict scope but worth surfacing in the Planner
brief so the file-naming/sidecar conventions are not designed twice.

Provisional sketch for the unified sidecar JSON:

```json
{
  "schema": "godo.map.sidecar.v1",
  "kind": "derived" | "backup",
  "source": {
    "pgm": "test_v4.pgm",
    "yaml": "test_v4.yaml",
    "yaml_sha256": "abc..."
  },
  "cumulative_from_pristine": {
    "translate_x_m": -0.275,
    "translate_y_m": 0.275,
    "rotate_deg": -91.7
  },
  "created": {
    "iso_kst": "2026-05-04T13:11:04+09:00",
    "session": "twenty-third",
    "memo": "test4",
    "reason": "operator Apply" | "auto-migration before issue#30 deploy"
  }
}
```

Concrete schema is a Planner round-1 deliverable; this sketch is a discussion
seed only.

## 10. Meta-lesson for Planner / Mode-A discipline

The spec memory presented two interpretations and led the reader toward picking
one of them. The operator on cold-start asked "is a different point not possible?"
and re-opened the design space, surfacing the actually-cleanest option that the
memory had silently excluded.

**Lesson** — when a design memo enumerates a choice set, Planner/Mode-A
discipline should require:

1. **Explicit justification for what was excluded.** If only N options are
   presented, why not N+1? Memos that fence the choice set without explaining
   the fence are doing the reader a disservice.
2. **Reframe pressure on cold-start.** When the operator opens a session against
   a memo, "what was excluded" should be reread with as much scrutiny as
   "what was included." The strongest framing of a problem often surfaces
   during the cold-start question, not the original drafting.
3. **Update the spec memory with the surfaced option even if it is the chosen
   one.** Future readers should see the full design space, not the truncated one.

This lesson applies to all design memos under `.claude/memory/project_*.md` and
design-doc analysis files under `/doc/`. Cross-link this section from
`feedback_verify_before_plan.md` if the lesson recurs.

## 11. 3-file atomic write protocol (C3-triple)

PR #81's `map_rotate.py::_atomic_write_pair` ships a 2-file C3 protocol
(PGM + YAML, atomic rename pair, cascade rollback on graceful failure).
issue#30 adds a third file — the sidecar JSON — and extends the protocol
to C3-triple.

### Protocol shape

```text
Phase 1 (durable tmp files)
  1. _write_fsync(pgm_tmp, pgm_bytes)
  2. _write_fsync(yaml_tmp, yaml_bytes)
  3. _write_fsync(json_tmp, json_bytes)
  4. _fsync_dir(parent)

Phase 2 (atomic rename sequence — each os.replace is one syscall, atomic)
  5. os.replace(pgm_tmp,  pgm_target)        ← commit 1
  6. os.replace(yaml_tmp, yaml_target)        ← commit 2 (on fail: unlink PGM)
  7. os.replace(json_tmp, json_target)        ← commit 3 (on fail: unlink YAML, PGM)
  8. _fsync_dir(parent)
```

### Why JSON is committed LAST

PGM + YAML are the AMCL-consumable critical pair. They must land
consistently first so the AMCL loader never sees a half-pair. The JSON
sidecar is supplementary metadata (lineage + cumulative tracking) — its
absence is recoverable (lineage can be synthesized from filename).
Committing JSON last keeps the AMCL-critical commit window small and
treats sidecar absence as a soft fault.

### Crash window + recovery sweep

`os.replace` syscalls run in microseconds, so the crash window between
commits is small but non-zero. A `kill -9` or power-loss between commit
2 and commit 3 leaves PGM + YAML committed without a sidecar — a working
derived map but no lineage record.

Recovery sweep (extended `sweep_stale_tmp` invoked at startup +
`list_maps`):

| State | Cause | Action |
|---|---|---|
| `*.tmp` files alone | crash during phase 1 | unlink (existing sweep) |
| PGM alone (no YAML) | crash between commits 1 and 2 | warn + unlink (orphan PGM) |
| YAML alone (no PGM) | abnormal write order | warn + unlink |
| PGM + YAML, no JSON | crash between commits 2 and 3, **OR** PR #81-era legacy derived | parse filename pattern → synthesize sidecar JSON with `lineage.kind: "synthesized"`, `lineage.generation: -1` (unknown depth), warn |
| JSON alone | unlikely (always written last) | warn + unlink |

The "synthesized" path also subsumes the auto-migration of PR #81-era
derived maps (Decision #4 in §7) — same code path, no separate
migration tool needed.

### Hash-based integrity field

Sidecar JSON includes an `integrity` block:

```json
"integrity": {
  "pgm_sha256": "...",
  "yaml_sha256": "..."
}
```

Read-time validation:

1. **External-edit detection** — operator hand-edits a YAML; SHA mismatch
   → sidecar marked stale; lineage treated as orphan.
2. **Partial-write corruption** — disk corruption mid-rename leaves byte
   damage; SHA mismatch surfaces it on next read.
3. **Cascade-safety check** — when PICK#3 reads PICK#2's sidecar to
   compose the new cumulative, it verifies PICK#2's `pgm_sha256` against
   the on-disk PGM. Mismatch → cumulative composition is refused (the
   parent has been mutated outside the Apply flow; safe fallback is to
   treat current state as a new pristine baseline).

### Mode-A required test pins

1. `test_pair_write_pgm_alone_orphan_recovers` — pre-place a stale PGM
   without YAML/JSON, invoke sweep, confirm unlink.
2. `test_pair_write_pgm_yaml_no_json_synthesizes` — pre-place a derived
   pair without sidecar, invoke sweep, confirm a synthesized JSON appears
   with `lineage.kind == "synthesized"`.
3. `test_pair_write_failure_rolls_back_all_committed` — inject an
   `os.replace` failure on the JSON rename, confirm both PGM and YAML
   are unlinked (cascade rollback).
4. `test_sidecar_integrity_detects_external_yaml_edit` — write a derived
   pair with sidecar, hand-mutate the YAML, confirm next read flags it
   as stale via SHA mismatch.

## Cross-references

- `.claude/memory/project_yaml_normalization_design.md` — original spec memory;
  its (1)/(2) framing is superseded by (3) — needs an update note pointing here.
- `.claude/memory/project_amcl_yaw_metadata_only.md` — AMCL yaw-blindness
  sub-finding that makes (3) clean.
- `.claude/memory/project_map_edit_origin_rotation.md` — PR #81 ship state;
  describes the SUBTRACT semantic that (3) supersedes.
- `.claude/memory/feedback_subtract_semantic_locked.md` — pending retraction
  (decision #6).
- `.claude/memory/project_pristine_baseline_pattern.md` — invariant that (3)
  preserves (1× resample regardless of cascade depth).
