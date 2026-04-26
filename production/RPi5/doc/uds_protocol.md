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

`set_mode` is honoured even during a OneShot run (unlike the GPIO
live-toggle, which drops). Operator intent: the GPIO physical button is
the safety guard; UDS is the automation escape hatch (Phase 4-3 webctl
may legitimately want to abort a hung OneShot).

If this becomes a footgun in field testing, add a `force=true` field to
`set_mode` and reject mid-OneShot transitions without it. Not required
for Wave B.

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
