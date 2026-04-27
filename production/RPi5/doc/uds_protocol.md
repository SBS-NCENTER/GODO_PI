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

Set `g_amcl_mode` atomically. Always succeeds (the value is overwritten
even if AMCL is mid-iteration; the cold writer observes the new mode at
the next loop top or after the in-flight scan completes).

```text
Request:  {"cmd":"set_mode","mode":"<Idle|OneShot|Live>"}\n
Response: {"ok":true}\n
Errors:   {"ok":false,"err":"bad_mode"}\n     unknown mode value
          {"ok":false,"err":"parse_error"}\n  malformed JSON
```

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
