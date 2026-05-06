# UDS control protocol

> Phase 4-2 D Wave B operator/automation input surface for
> `godo_tracker_rt`. The Phase 4-3 `godo-webctl` will eventually drive
> this socket.

## A. Socket

Default path: `/run/godo/ctl.sock` (`cfg.uds_socket`).

Type: `AF_UNIX`, `SOCK_STREAM`, blocking. The server listens with
`backlog = 4`; one client at a time, request/response then close.

File permissions: `0660` (owner + group rw). Group ownership inherits
from the `godo_tracker_rt` process. See "Caveats" below.

## B. Wire format

JSON-lines: each request and response is a single UTF-8-free ASCII JSON
object terminated by `\n`. Maximum request size:
`godo::constants::UDS_REQUEST_MAX_BYTES = 4096` bytes including the
trailing newline.

Backslash escapes inside string values are **not** supported (the schema
is pure ASCII). Whitespace between structural tokens is tolerated.

## C. Commands

### `set_mode`

Set `g_amcl_mode` atomically. Always succeeds for the bare-mode shape
(the value is overwritten even if AMCL is mid-iteration; the cold
writer observes the new mode at the next loop top or after the in-flight
scan completes).

issue#3 (pose hint, §C.1.1) — the request MAY carry an optional pose-
hint payload of up to five number-valued fields. When present, the
tracker publishes the hint into the calibrate-hint atomics via the
M3 release/acquire ordering chain BEFORE storing
`g_amcl_mode = OneShot`, so the cold writer sees a fresh hint on its
next acquire-load of the mode.

```text
Request:  {"cmd":"set_mode","mode":"<Idle|OneShot|Live>"}\n
          {"cmd":"set_mode","mode":"OneShot",
           "seed_x_m":<num>,"seed_y_m":<num>,"seed_yaw_deg":<num>}\n
          {"cmd":"set_mode","mode":"OneShot",
           "seed_x_m":<num>,"seed_y_m":<num>,"seed_yaw_deg":<num>,
           "sigma_xy_m":<num>,"sigma_yaw_deg":<num>}\n
Response: {"ok":true}\n
Errors:   {"ok":false,"err":"bad_mode"}\n                  unknown mode value
          {"ok":false,"err":"parse_error"}\n               malformed JSON
          {"ok":false,"err":"bad_seed_partial"}\n          two-of-three seed_* fields
          {"ok":false,"err":"bad_seed_with_non_oneshot"}\n hint with mode != OneShot
          {"ok":false,"err":"bad_sigma_without_seed"}\n    σ override without seed_*
          {"ok":false,"err":"bad_seed_value"}\n            non-finite or out-of-range
```

#### `set_mode` — pose hint payload (issue#3, §C.1.1)

The pose-hint extension carries the operator-placed initial seed for
AMCL phase-0 (`converge_anneal`). When the hint is present, the cold
writer's phase-0 calls `seed_around(hint, σ_xy, σ_yaw)` instead of
`seed_global`, narrowing the multi-basin spread to a single Gaussian
basin around the operator's click.

Field semantics:

| Field | Type | Optional | Range | Notes |
|---|---|---|---|---|
| `seed_x_m`     | JSON number | yes (all-or-none) | `[-100, 100]` m       | AMCL-frame X. |
| `seed_y_m`     | JSON number | yes (all-or-none) | `[-100, 100]` m       | AMCL-frame Y. |
| `seed_yaw_deg` | JSON number | yes (all-or-none) | `[0, 360)` (CCW REP-103) | AMCL-frame yaw. |
| `sigma_xy_m`   | JSON number | independent       | `[0.05, 5.0]` m       | Per-call σ_xy override. Cfg default `amcl.hint_sigma_xy_m_default = 0.50` applies when omitted. |
| `sigma_yaw_deg`| JSON number | independent       | `[1.0, 90.0]` deg     | Per-call σ_yaw override. Cfg default `amcl.hint_sigma_yaw_deg_default = 20.0` applies when omitted. |

Validation rules:

1. The seed triple `(seed_x_m, seed_y_m, seed_yaw_deg)` is
   **all-or-none**. Two-of-three is rejected as `bad_seed_partial`.
2. σ overrides require the seed triple to be present. σ alone is
   rejected as `bad_sigma_without_seed`.
3. Hint payloads with `mode != "OneShot"` are rejected as
   `bad_seed_with_non_oneshot`. Live-mode hint is out of scope; GPIO
   calibrate keeps its current uniform-seed behaviour.
4. Each field MUST be a JSON NUMBER (not a JSON string). The C++
   parser rejects string-quoted "1.0" on a number-valued key as
   `parse_error`. `repr(float)` (Python webctl encoder) emits the
   accepted shape: optional `-`, integer part, optional `.N+`,
   optional `eN`. NaN / Infinity / leading `+` / leading `.` are
   rejected.
5. Non-finite or out-of-range values are rejected as `bad_seed_value`.

Wire ordering (Mode-A M3): the tracker stores the bundle into
`Seqlock<HintBundle> g_calibrate_hint_data`, then sets
`std::atomic<bool> g_calibrate_hint_valid` to `true` with release
ordering, THEN stores `g_amcl_mode = OneShot` (also release). The
cold writer's acquire-load on `g_amcl_mode` happens-after the bundle
publish.

Consume-once: the cold writer (`run_one_iteration`) is the SOLE
clearer of `g_calibrate_hint_valid`. Every OneShot completion
clears the flag whether the OneShot started with a hint or not, so
a stale hint from a previous OneShot can never bleed into the next
one. See production/RPi5/CODEBASE.md invariant (p) for the full
ownership chain.

Empty-body `set_mode` (no hint fields) is byte-identical to the
pre-issue#3 wire — back-compat is pinned by webctl
`test_protocol::encode_set_mode_no_hint_byte_identical_to_pre_issue3`
+ `test_app_integration::test_calibrate_empty_body_byte_identical_to_pre_issue3`.

### `get_mode`

Read the current `g_amcl_mode`.

```text
Request:  {"cmd":"get_mode"}\n
Response: {"ok":true,"mode":"<Idle|OneShot|Live>"}\n
```

### `ping`

Health check. Returns `ok:true` without side effect; useful for
`godo-webctl` to verify the tracker process is alive and the UDS is
reachable.

```text
Request:  {"cmd":"ping"}\n
Response: {"ok":true}\n
```

### `get_last_pose` (Track B)

Read the last AMCL pose published by the cold writer. Used by the Phase 1
repeatability harness (`godo-mapping/scripts/repeatability.py`) and the
live `godo-mapping/scripts/pose_watch.py` cmd-window monitor to capture
each OneShot result without restarting the tracker.

```text
Request:  {"cmd":"get_last_pose"}\n
Response: {"ok":true,
           "valid":<0|1>,
           "x_m":<%.6f>,
           "y_m":<%.6f>,
           "yaw_deg":<%.6f>,
           "xy_std_m":<%.9g>,
           "yaw_std_deg":<%.9g>,
           "iterations":<int>,
           "converged":<0|1>,
           "forced":<0|1>,
           "published_mono_ns":<uint64>}\n
```

Field semantics:

| Field | Type | Meaning |
| --- | --- | --- |
| `valid` | `0|1` | `0` = no AMCL pose ever published since boot (sentinel `iterations=-1`); `1` = at least one OneShot or Live iteration has completed |
| `x_m`, `y_m` | `double` (m) | Weighted-mean pose in the world frame, same convention as `Offset` |
| `yaw_deg` | `double` ([0, 360)) | Canonical-360 yaw (M3 convention) |
| `xy_std_m` | `double` (m) | Combined-variance scalar `sqrt(weighted_var_x + weighted_var_y)`; see `localization/amcl.cpp:272-300` (`Amcl::xy_std_m`) for the formula |
| `yaw_std_deg` | `double` (°) | Circular standard deviation of the particle yaw distribution (M5) |
| `iterations` | `int32` | AMCL iteration count for the last run (`-1` when `valid=0`) |
| `converged` | `0|1` | `0` = the convergence-budget tripwire fired; `1` = early-exit on convergence threshold |
| `forced` | `0|1` | `0` = published by Live mode; `1` = published by OneShot |
| `published_mono_ns` | `uint64` | `clock_gettime(CLOCK_MONOTONIC)` nanoseconds at publish time; readers can detect a stale snapshot by comparing against their own monotonic clock + a freshness budget |

**Precision policy (F8)**:

- Pose fields (`x_m`, `y_m`, `yaw_deg`) use `%.6f` — 1 µm / 1 µdeg
  precision is well below the AMCL noise floor and avoids the `%g`
  exponential-form output for small-magnitude values.
- Std fields (`xy_std_m`, `yaw_std_deg`) use `%.9g` — keeps the full
  diagnostic mantissa visible even for very small values close to the
  convergence threshold.
- `published_mono_ns` uses `%llu` (uint64).

**Always succeeds**. There is no error response shape for this command;
even on a fresh boot before any AMCL run, the server returns
`valid=0, iterations=-1` and the rest of the fields zeroed.

**Worst-case reply size**: under 512 bytes. Pinned by
`tests/test_uds_server.cpp::format_ok_pose_reply_under_512_bytes` (F17).

```text
Request:  {"cmd":"get_last_pose"}\n
Response examples:
  No pose yet:
    {"ok":true,"valid":0,"x_m":0.000000,...,"iterations":-1,...,"published_mono_ns":0}\n
  After a OneShot:
    {"ok":true,"valid":1,"x_m":1.234567,...,"iterations":12,"converged":1,"forced":1,...}\n
  Live tick:
    {"ok":true,"valid":1,...,"forced":0,...}\n
```

**Cross-language SSOT**: the field names embedded in the reply format
string in `production/RPi5/src/uds/json_mini.cpp::format_ok_pose` are the
canonical wire-name source. `godo-webctl/src/godo_webctl/protocol.py::
LAST_POSE_FIELDS` mirrors the field-name tuple and is pinned at test
time by `godo-webctl/tests/test_protocol.py` reading the C++ source as
text.

**Race pin (F5)**: the cold writer publishes `last_pose_seq` BEFORE
storing `g_amcl_mode = Idle` at the OneShot success path
(`production/RPi5/src/localization/cold_writer.cpp` — search for the
"SSOT: last_pose_seq.store BEFORE g_amcl_mode = Idle" comment). Readers
poll `get_mode==Idle` first, then read `get_last_pose`; without this
ordering the reader could see the new Idle and the stale snapshot from
the previous OneShot.

### `get_last_scan` (Track D)

Returns the latest LIDAR scan snapshot published by the cold writer at
the same seam where it publishes `LastPose`. Used by the SPA's live
LIDAR overlay (`/api/last_scan`, `/api/last_scan/stream` @ 5 Hz) to
draw raw scan dots on the B-MAP page so an operator can verify AMCL
convergence visually.

**Request**:

```json
{"cmd":"get_last_scan"}
```

**Response (no scan ever published)**:

```json
{"ok":true,"valid":0,"forced":0,"pose_valid":0,"iterations":-1,"published_mono_ns":0,"pose_x_m":0.000000,"pose_y_m":0.000000,"pose_yaw_deg":0.000000,"n":0,"angles_deg":[],"ranges_m":[]}
```

**Response (after a OneShot or Live publish)**:

```json
{"ok":true,"valid":1,"forced":1,"pose_valid":1,"iterations":17,"published_mono_ns":1234567890123,"pose_x_m":1.234567,"pose_y_m":-0.876543,"pose_yaw_deg":92.345678,"n":3,"angles_deg":[0.0000,0.5000,1.0000],"ranges_m":[1.2345,1.2456,1.2567]}
```

**Field semantics**:

| Field | Type | Meaning |
|---|---|---|
| `valid` | `0|1` | `0` = no scan ever published (sentinel); `1` = the rest of the fields carry a real publish. |
| `forced` | `0|1` | `1` = OneShot publish; `0` = Live publish. Mirrors `LastPose.forced`. |
| `pose_valid` | `0|1` | `1` = the anchor pose (`pose_*` fields) came from a converged AMCL run; `0` = non-converged (the SPA dims/hides the overlay in this case per Mode-A M3). |
| `iterations` | `int32` | AMCL iterations consumed by the producing call; `-1` is the never-published sentinel. |
| `published_mono_ns` | `uint64` | `clock_gettime(CLOCK_MONOTONIC)` ns at publish. **Ordering primitive only** — the SPA computes freshness against `Date.now() - _arrival_ms` (per Mode-A M2). |
| `pose_x_m`, `pose_y_m`, `pose_yaw_deg` | `double` | The AMCL pose at the moment this scan was processed. The SPA uses these as the polar→Cartesian anchor; same-frame pose-scan correlation is exact (zero skew). |
| `n` | `uint16` | Count of valid samples in `angles_deg`/`ranges_m`. ≤ `LAST_SCAN_RANGES_MAX` (= 720 in `core/constants.hpp`). |
| `angles_deg` | `double[n]` | Per-beam bearing in the LiDAR frame, degrees, `[0, 360)`. |
| `ranges_m` | `double[n]` | Per-beam range in metres. The cold writer drops samples with `distance_mm <= 0` or out of `[range_min_m, range_max_m]` (matches the AMCL beam decimation rule in `localization/scan_ops.cpp::downsample`). |

**Bandwidth budget**: 720-sample worst case, `%.4f` precision per
double, fits in ~14 KiB JSON. Wire scratch on both sides:
- Server formatter: `core/constants.hpp::JSON_SCRATCH_BYTES = 24576`
  (24 KiB) — pinned by `static_assert` in `format_ok_scan`.
- Client (webctl) read cap: `protocol.py::LAST_SCAN_RESPONSE_CAP =
  32768` (32 KiB) — used only by `get_last_scan`; all other commands
  keep the standard 4 KiB.

**Discipline — server emits raw polar (Mode-A TM5 + invariant (l))**:
the scan body is in the LiDAR frame; the SPA does the world-frame
transform using the same-frame anchor pose. The server NEVER pre-
transforms scan points to world coordinates because doing so would
hide the pose ↔ scan temporal correlation that makes AMCL
debugging useful.

**Cross-language SSOT**: the field NAMES are taken from the
`godo::rt::LastScan` struct declaration in `core/rt_types.hpp`; the
field ORDER on the wire is set by the format string in
`uds/json_mini.cpp::format_ok_scan`; the Python mirror
`godo-webctl/src/godo_webctl/protocol.py::LAST_SCAN_HEADER_FIELDS` is
pinned by `tests/test_protocol.py::test_last_scan_header_fields_match_cpp_source`
which reads `rt_types.hpp` as text and regex-extracts the names.

**Hot-path isolation**: Thread D (UDP send @ 59.94 Hz) does NOT
reference `last_scan_seq`. Build-grep `[hot-path-isolation-grep]`
fails the build if any line inside `thread_d_rt` mentions the seqlock.
Cold writer is the sole publisher; `[scan-publisher-grep]` enforces
this at build time.

### `get_config` (Track B-CONFIG, §C.8)

Returns a single JSON object whose keys are the dotted Tier-2 names
declared in `core/config_schema.hpp` and whose values are the live
effective Config (post-CLI/env/TOML application). The reply is
typed: `int` rows emit JSON integers, `double` rows emit JSON numbers,
`string` rows emit quoted strings.

**Request**:

```json
{"cmd":"get_config"}
```

**Response (abridged — 37 keys in production)**:

```json
{"ok":true,"amcl.converge_xy_std_m":0.015,"amcl.map_path":"/etc/godo/maps/studio_v1.pgm","network.ue_port":6666,"smoother.deadband_mm":10.0}
```

**Order**: alphabetical by key. Mirrors the schema's compile-time order.
Webctl's projection (`config_view.project_config_view`) drops the `ok`
flag before forwarding to the SPA.

**Bandwidth**: ~2 KiB for 37 rows; default 4 KiB read cap is sufficient.

### `get_config_schema` (Track B-CONFIG, §C.9)

Returns the schema metadata as a JSON array. Each row carries the
operator-visible attributes (`name`, `type`, numeric range, default,
reload-class, description). Webctl's Python mirror parses
`config_schema.hpp` directly, so this UDS command is rarely needed in
production — it exists for cross-language parity tests + future
clients that lack the C++ source on disk.

**Request**:

```json
{"cmd":"get_config_schema"}
```

**Response (one row example)**:

```json
{"ok":true,"schema":[{"name":"smoother.deadband_mm","type":"double","min":0.0,"max":200.0,"default":"10.0","reload_class":"hot","description":"Deadband on translation (mm)."}]}
```

**Bandwidth**: ~7 KiB for 37 rows; webctl's read cap for this command
is `protocol.py::CONFIG_SCHEMA_RESPONSE_CAP = 16384` (16 KiB).

### `set_config` (Track B-CONFIG, §C.10)

Validates a (key, value_text) pair against the schema and, on success,
atomically rewrites `/etc/godo/tracker.toml`, updates the live Config
under `live_cfg_mtx`, publishes the hot-config seqlock if the row's
reload-class is `hot`, and touches `/var/lib/godo/restart_pending` if
the reload-class is `restart` or `recalibrate`.

**Request**:

```json
{"cmd":"set_config","key":"smoother.deadband_mm","value":"12.5"}
```

`value` is always a JSON string on the wire — the tracker's
`validate.cpp` re-parses per the schema's `ValueType` (Int / Double /
String). Webctl's PATCH endpoint accepts native JSON int / float /
bool / string in the body and string-coerces server-side before
forwarding to this command.

**Response (success)**:

```json
{"ok":true,"reload_class":"hot"}
```

**Response (validation failure)**:

```json
{"ok":false,"err":"bad_value","detail":"smoother.deadband_mm out of range [0.0, 200.0]: got 250.0"}
```

**Error codes**:

| `err`             | Meaning                                                          |
|-------------------|------------------------------------------------------------------|
| `bad_key`         | The `key` is not in `CONFIG_SCHEMA`.                             |
| `bad_value`       | `value` failed type or range validation; `detail` carries the human-readable reason. |
| `non_ascii_value` | `value` contains a byte outside `[0x20, 0x7E]`; the tracker's hand-rolled JSON parser tolerates ASCII only. |
| `write_failed`    | `core/atomic_toml_writer` could not write `tracker.toml`; `detail` carries the underlying errno text. RAM `Config` is unchanged in this case. |

**Atomicity**: the on-disk TOML and live RAM Config are kept in
lockstep. The sequence is `validate → mkstemp/write/fsync/rename →
update RAM → publish seqlock | touch restart-pending`. A power loss
between any two steps leaves either the pre-PATCH state OR the post-
PATCH state on disk, never a torn write. See
`core/atomic_toml_writer.cpp` + `[atomic-toml-write-grep]`.

**Reload-class semantics**:
- `hot`: the cold writer reads the new value via
  `hot_cfg_seq.load()` on the next iteration (no restart needed). The
  SPA shows ✓ on this row.
- `restart`: the new value lands in TOML + RAM but is only consumed by
  code that reads `Config` once at startup (e.g. UDP sender, serial
  reader). The SPA shows red `!` and the
  `RestartPendingBanner` until the operator restarts via B-LOCAL.
- `recalibrate`: same as `restart` plus the AMCL particle cloud must
  be re-seeded (next OneShot). The SPA shows red `‼`.

### `get_parallel_eval` (issue#11, §C.11)

Returns a snapshot of the cold-side `ParallelEvalPool`'s runtime
counters, sampled at the diag publisher's 1 Hz cadence (the same
seqlock-store seam as `get_jitter` / `get_amcl_rate`). Wire shape
mirrors `get_jitter` for SPA-side rendering uniformity.

**Request**:

```json
{"cmd":"get_parallel_eval"}
```

**Response**:

```json
{"ok":true,"valid":1,"dispatch_count":1542,"fallback_count":0,"p99_us":1850,"max_us":2100,"degraded":0,"published_mono_ns":12345678901234}
```

**Field semantics**:

| Field                | Type   | Meaning                                                      |
|----------------------|--------|--------------------------------------------------------------|
| `valid`              | uint8  | 0 = no diag publish yet (first second post-boot); 1 = populated |
| `dispatch_count`     | uint64 | Total `parallel_for` calls since boot (monotonic)            |
| `fallback_count`     | uint64 | Total inline-sequential fallbacks (degraded ctor / 50 ms join timeout / subsequent inline dispatches) |
| `p99_us`             | uint32 | p99 wallclock dispatch+join latency over the last ~1.5 s     |
| `max_us`             | uint32 | Decaying max latency over a 1 s window                       |
| `degraded`           | uint8  | 1 = pool transitioned to permanent inline-sequential; 0 = active |
| `published_mono_ns`  | uint64 | `monotonic_ns()` at diag-publisher store time                |

**Operator interpretation**:
- `degraded=1` ⇒ pool has fallen back permanently for this tracker
  process; restart to retry. The cold writer continues at sequential
  speed (~7 Hz on Phase-0 baseline) — accuracy is unaffected (output
  bit-equal per plan §3.6) but Hz-vs-LiDAR margin disappears.
- `fallback_count` growing while `degraded=0` is unexpected — investigate
  CPU oversubscription on cores 0/1/2 (e.g., another process pinned).
- `p99_us` should be ≤ 4000 µs in steady state at N=500 particles
  (Phase-0 projection: ~1.85 ms × 1.05 jitter buffer ≈ 1950 µs typical).

**Workers=1 rollback path**: `cfg.amcl_parallel_eval_workers = 1` boots
the pool with no worker threads; `parallel_for` runs fn on the caller
thread. The diag snapshot reports `degraded=0` (workers=1 is a
configured choice, not a degradation), `fallback_count=0`, and `p99_us`
reflects the inline sequential cost (~5.6 ms typical at N=500).

## D. Errors

| Code            | Meaning                                                |
|-----------------|--------------------------------------------------------|
| `parse_error`   | Request JSON is malformed, missing `cmd`, or has unknown keys |
| `unknown_cmd`   | `cmd` is not one of `ping` / `get_mode` / `set_mode`   |
| `bad_mode`      | `set_mode` `mode` is not one of `Idle` / `OneShot` / `Live` |

A request that exceeds `UDS_REQUEST_MAX_BYTES` without a newline is
treated as hostile/malformed: the server closes the connection without
sending any response.

## E. Examples

```bash
# Calibrate now
echo '{"cmd":"set_mode","mode":"OneShot"}' | nc -U /run/godo/ctl.sock
# → {"ok":true}

# What mode is the tracker in?
echo '{"cmd":"get_mode"}' | nc -U /run/godo/ctl.sock
# → {"ok":true,"mode":"Idle"}

# Toggle Live tracking on
echo '{"cmd":"set_mode","mode":"Live"}' | nc -U /run/godo/ctl.sock
# → {"ok":true}

# Liveness check
echo '{"cmd":"ping"}' | nc -U /run/godo/ctl.sock
# → {"ok":true}
```

## F. Caveats

### File permissions and same-uid client expectation

`/run/godo/ctl.sock` is created with mode `0660`. Until the systemd unit
`godo-tracker.service` introduces `SocketGroup=` (Phase 4-2 follow-up),
ANY client must run under the **same uid** as `godo_tracker_rt`. On
news-pi01 this means launching `godo-webctl` as `ncenter`.

If multi-user dev becomes a real workflow, revisit by either:

- adding a `cfg.uds_socket_mode` Tier-2 key (allows operator override),
  OR
- having systemd own the socket via `socket-activated`, with
  `SocketGroup=godo` set so any user in the `godo` group can connect.

### Graceful degradation

If `bind()` fails (stale socket without permission to unlink, parent
directory missing, path too long), the UDS thread logs and exits cleanly
without affecting `g_running`. GPIO and HTTP triggers still work.

### One-shot connection model

Each accepted connection handles exactly one request and closes. Clients
must `connect → send request → recv response → close → reopen` for the
next request. This keeps the server stateless and lets a stalled client
not block the accept loop (per-connection `SO_RCVTIMEO = 1 s`; the
listen socket itself is poll-based per Mode-A amendment M1).

### Mid-OneShot set_mode behaviour

`set_mode` while the cold writer is in `case OneShot` (mid-`converge()`)
**does NOT abort the in-flight converge**. The cold writer's loop only
re-reads `g_amcl_mode` at the top of each iteration; the OneShot kernel
runs to completion (~1 s at 5000 particles × 25 iters), then stores
`Idle` itself at the case-OneShot exit. A second store of `OneShot`
that arrived during this window is silently absorbed by the terminal
`store(Idle)` (race resolved by ordering — the cold writer's terminal
store happens after the kernel returns, so it wins against an earlier
UDS store of the same value).

Practical implication for clients: `set_mode("OneShot")` is idempotent
in spirit but NOT a "queue an additional OneShot" call. If the operator
wants two consecutive calibrates, wait for the first to complete (poll
`get_mode` until it returns `Idle`) before issuing the second.

If true mid-OneShot abort becomes a real workflow (kidnapped recovery,
operator panic-cancel), add a `force=true` field to `set_mode` and have
the cold writer re-check `g_amcl_mode` between converge() iterations.
Not required for Wave B.

## G. Phase 4-3 client expectations

`godo-webctl` connects to `cfg.uds_socket` per-request. Recommended Python
shape (post-Phase-4-3):

```python
import socket, json
def call(req: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect("/run/godo/ctl.sock")
        s.sendall((json.dumps(req) + "\n").encode())
        return json.loads(s.recv(256))
```

The 4 KiB buffer cap is far above the response size; a 256-byte recv is
safe.

## H. Bootstrap and operator forensics

issue#18 (2026-05-03) hardened the tracker UDS bootstrap path against the
stale-`/run/godo/ctl.sock` failure mode observed during issue#10.1 HIL.
This section is the operator-facing reference for how the bootstrap path
behaves and how to diagnose future stale-state events.

### H.1 Atomic-rename + stale guard + destructor unlink lifecycle

The full lifecycle of `/run/godo/ctl.sock` looks like this:

```text
┌───────────────────────────────────────────────────────────────────┐
│ Boot path                                                         │
├───────────────────────────────────────────────────────────────────┤
│ 1. main() — pidfile lock acquired (CODEBASE invariant (l))        │
│    └─ proves we are the sole tracker.                             │
│ 2. main() — audit_runtime_dir(cfg.uds_socket)                     │
│    └─ ONE stderr line documenting inherited state.                │
│ 3. main() — sweep_stale_siblings(cfg.uds_socket)                  │
│    └─ unlinks stale `<path>.<pid>.tmp` (regular files always;     │
│       sockets only when older than                                │
│       constants::UDS_STALE_SIBLING_MIN_AGE_SEC).                  │
│ 4. thread_uds — UdsServer::open()                                 │
│    ├─ socket(AF_UNIX) → bind to `<path>.<our_pid>.tmp`            │
│    ├─ lstat(target) — if non-socket, unlink (PR #73 guard).       │
│    ├─ rename(tmp → target) — atomic; on failure logs lstat of     │
│    │  both endpoints (issue#18 MF2) before throwing.              │
│    ├─ chmod(target, 0660)                                         │
│    └─ listen(LISTEN_BACKLOG=4)                                    │
│ 5. UdsServer::run() — accept loop.                                │
├───────────────────────────────────────────────────────────────────┤
│ Shutdown path                                                     │
├───────────────────────────────────────────────────────────────────┤
│ 6. signal handler → g_running.store(false)                        │
│ 7. UdsServer::run() returns at next 100 ms poll wake.             │
│ 8. ~UdsServer() → close()                                         │
│    ├─ close(listen_fd_)                                           │
│    └─ unlink(socket_path_)  ◄ MF1 destructor closure.             │
└───────────────────────────────────────────────────────────────────┘
```

Source pointers:

- `src/uds/uds_server.cpp::UdsServer::open()` — atomic-rename bind +
  PR #73 stale-non-socket guard + MF2 rename-failure forensic logging.
- `src/uds/uds_server.cpp::UdsServer::close()` — destructor's unlink
  path (MF1).
- `src/uds/uds_server.cpp::audit_runtime_dir()` — MF3 boot-audit log line.
- `src/uds/uds_server.cpp::sweep_stale_siblings()` — SF3 sibling sweep.

### H.2 `ss -lxp` historical-bind-path display quirk

`ss -lxp` shows the FIRST bind path of each AF_UNIX socket — meaning the
`.<pid>.tmp` path created during atomic-rename, NOT the post-rename target
`/run/godo/ctl.sock`. The kernel records the original bind path for
historical reasons; the rename(2) syscall rebinds the directory entry
without updating this record.

This is a kernel display quirk, NOT a tracker bug. The actual socket inode
IS reachable via `/run/godo/ctl.sock` — clients connect successfully.

Verification recipe:

```bash
sudo ss -lxp | grep ctl.sock
# Likely output:
#   u_str  LISTEN  0  4  /run/godo/ctl.sock.12345.tmp ...  users:(("godo_tracker_",pid=12345,fd=N))
# Even though `ls -la /run/godo/ctl.sock` shows a srw-rw---- socket file.
ls -la /run/godo/ctl.sock
# srw-rw---- 1 ncenter ncenter 0 ... /run/godo/ctl.sock
```

If you need the actual bound-and-served path, use `lsof -p <pid> | grep
ctl.sock` — `lsof` resolves the inode rather than reading the bind cache.

### H.3 journalctl forensics recipe

Every new log tag from issue#18 is greppable; one grep per failure
hypothesis lets the operator localise the issue without reading the
whole boot log.

Boot-audit line (always emitted, fresh every boot):

```bash
sudo journalctl -u godo-tracker -b | grep 'uds bootstrap audit'
# Fresh boot:           ctl.sock=ENOENT siblings=0 []
# Clean shutdown ran:   ctl.sock=ENOENT siblings=0 []
# Unclean shutdown:     ctl.sock=S_IFSOCK_size=0 siblings=0 []
# issue#10.1 failure:   ctl.sock=S_IFREG_size=0 siblings=1 [ctl.sock.12345.tmp]
# Pathological:         ctl.sock=S_IFDIR_size=4096 siblings=4 [...] (out-of-band mkdir)
```

Stale-non-socket-cleared by PR #73 guard:

```bash
sudo journalctl -u godo-tracker -b | grep 'stale non-socket'
# Expected when issue#10.1 fires:
#   uds_server::open: stale non-socket at '/run/godo/ctl.sock' (mode=0100644, size=0); unlinking before atomic rename
```

Sibling sweep activity:

```bash
sudo journalctl -u godo-tracker -b | grep 'uds sibling sweep'
# Expected when stale .tmp leftovers get reclaimed:
#   godo_tracker_rt: uds sibling sweep: unlinked stale '/run/godo/ctl.sock.99999.tmp' (mode=0100644, size=0)
# Or when a fresh socket is kept:
#   godo_tracker_rt: uds sibling sweep: keeping fresh socket '/run/godo/ctl.sock.12345.tmp' (mtime=..., threshold=...)
```

Rename-failure forensics (only fires on the ENOSPC / EACCES failure path):

```bash
sudo journalctl -u godo-tracker -b | grep 'rename failure forensics'
# Two lines per failure — one per endpoint:
#   uds_server::open: rename failure forensics — tmp_path='/run/godo/ctl.sock.NNNNN.tmp' lstat=S_IFSOCK_size=0
#   uds_server::open: rename failure forensics — target='/run/godo/ctl.sock' lstat=S_IFREG_size=0
```

#### HIL recipe — stale-state injection

Replays the issue#10.1 failure on demand to verify the PR #73 guard is
still in place:

```bash
# On news-pi01, after the new build is deployed to /opt/godo-tracker/:
sudo systemctl stop godo-tracker
sudo rm -f /run/godo/ctl.sock /run/godo/ctl.sock.*.tmp
# Inject a stale regular file:
sudo install -m 0644 -o ncenter -g ncenter /dev/null /run/godo/ctl.sock
ls -la /run/godo/ctl.sock                # expect -rw-r--r-- (regular file)
# Start tracker via SPA System tab Start button (operator-managed; do NOT
# systemctl-enable per .claude/memory/project_godo_service_management_model.md).
# Verify the boot-audit captured the stale state:
sudo journalctl -u godo-tracker -b | grep 'uds bootstrap audit'
# Expected: ctl.sock=S_IFREG_size=0 siblings=0 []
sudo journalctl -u godo-tracker -b | grep 'stale non-socket'
# Expected: stale non-socket at '/run/godo/ctl.sock' (mode=0100644, size=0); unlinking before atomic rename
ls -la /run/godo/ctl.sock                # expect srw-rw---- (socket)
# Verify SPA reaches the tracker:
# - hard-reload SPA (Ctrl+Shift+R), observe Dashboard tracker:"reachable"
# - press Calibrate to confirm UDS round-trip
```

#### HIL recipe — sibling sweep

Replays the half-failed-rename hypothesis:

```bash
sudo systemctl stop godo-tracker
sudo rm -f /run/godo/ctl.sock /run/godo/ctl.sock.*.tmp
sudo install -m 0644 -o ncenter -g ncenter /dev/null /run/godo/ctl.sock.99999.tmp
sleep 3                                  # > UDS_STALE_SIBLING_MIN_AGE_SEC
# Start tracker via SPA System tab.
sudo journalctl -u godo-tracker -b | grep 'uds bootstrap audit'
# Expected: siblings=1 [ctl.sock.99999.tmp]
sudo journalctl -u godo-tracker -b | grep 'uds sibling sweep'
# Expected: unlinked stale '/run/godo/ctl.sock.99999.tmp' (mode=0100644, size=0)
ls -la /run/godo/ctl.sock.99999.tmp      # expect ENOENT
```

Both recipes are pinned by the unit tests in
`tests/test_uds_server.cpp::TEST_CASE("issue#18 ...")`.
