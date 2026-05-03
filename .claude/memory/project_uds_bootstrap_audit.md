---
name: issue#18 — UDS bootstrap audit (broader scope after PR #73 quick fix)
description: PR #73 shipped a quick `lstat → unlink-if-non-socket` guard before atomic-rename in uds_server.cpp. Broader audit covers stale-state root-cause tracing, rename-failure path-aware logging, atexit/destructor unlink semantics, mapping@active socket parity, and `ss -lxp` historical-bind-path display behavior.
type: project
---

**Surfaced**: 2026-05-03 KST during issue#10.1 PR #73 HIL. **Quick fix shipped**: PR #73 (uds_server.cpp lstat guard + self-documenting stderr). **Broader audit**: deferred as issue#18.

## Symptom observed during HIL

Operator restarts godo-tracker via SPA → SPA shows `tracker:"unreachable"`, `/api/calibrate/status` 404. tracker process is `active running` per systemd, fd 8 is a socket (UDS server bound), banner output normal (`ue=192.168.0.0:6666 freed=/dev/ttyAMA0@38400 rt_cpu=3 rt_prio=50`). But:

```
$ sudo ss -lxp 2>/dev/null | grep ctl.sock
u_str LISTEN ... /run/godo/ctl.sock.<pid>.tmp ... godo_tracker_rt(pid=<pid>,fd=8)
```

`ctl.sock` (without the `.tmp` suffix) coexisted as a separate **0-byte regular file** (mtime AFTER tracker's start time). webctl was connecting to `ctl.sock` and finding the empty regular file → connection failed → SPA showed unreachable.

Recovery: `sudo systemctl stop godo-tracker; sudo rm -f /run/godo/ctl.sock /run/godo/ctl.sock.*.tmp; sudo systemctl start godo-tracker`. After restart, `ctl.sock` was a proper socket (`srw-rw----`) and webctl reconnected.

## What the existing code does (uds_server.cpp:121-191)

The atomic-rename pattern is correctly implemented:

1. `socket()` — line 121
2. Build `tmp_path = "<socket_path_>.<pid>.tmp"` — line 132
3. `unlink(tmp_path)` to sweep stale .tmp from prior crash — line 147 (existing)
4. `bind()` to tmp_path — line 154
5. **PR #73 guard**: `lstat(socket_path_)` → if `!S_ISSOCK` then `unlink` + log — added at line ~163
6. `rename(tmp_path, socket_path_)` — atomically replaces target — line 200
7. `chmod(socket_path_, 0660)` — line 213
8. `listen()` — line 219

POSIX `rename(2)` GUARANTEES atomic replacement of the destination regardless of file type. So **theoretically**, the stale 0-byte `ctl.sock` should not have been an issue — rename would have overwritten it.

## Open questions for issue#18

1. **What created the stale 0-byte `ctl.sock` regular file in the first place?** Root cause unknown. Hypotheses:
   - **webctl's `uds_client` ENOENT handling**: when webctl connects to a nonexistent path, does it touch the path? (Probably not, but verify.) `socket.connect()` with non-existent UDS path returns ENOENT — no file is created.
   - **half-failed prior rename**: previous tracker boot may have hit a `rename()` that failed AFTER unlinking the source `.tmp` but BEFORE establishing the destination socket. Result: target unlinked, source unlinked, but inotify/journal would show... need to check.
   - **systemd-tmpfiles**: `/run/godo/` is on tmpfs (managed by `systemd-tmpfiles`). A `tmpfiles.d/godo.conf` line could create a placeholder. Check `/usr/lib/tmpfiles.d/` and `/etc/tmpfiles.d/`.
   - **install.sh `daemon-reload` race**: at install.sh `[11/12]` step, `systemctl daemon-reload` happens. If a unit file's `RuntimeDirectory=godo` was being recreated, could it touch existing files? Unlikely but worth checking.

2. **Why didn't `rename()` fire?** If the code path reached step 6 with the existing 0-byte regular file at target, rename would have atomic-replaced it with the bound socket — no stale file would remain. Possibilities:
   - rename DID fire successfully on this boot, but the stale file appeared AFTERWARD (some race between webctl restart and tracker's atomic-rename).
   - rename was never called: tracker stuck before step 6. Banner output was BEFORE this code path? (Check ordering — banner happens during `Config::load`, UDS server is started later.)
   - rename returned an error and was caught silently somewhere.

3. **Logging gap on rename failure**: existing `rename()` failure path at line 200-211 throws `std::runtime_error`. If the throw is caught by main and tracker exits, journal would show the throw message. But our HIL didn't see any rename-failed message in the journal — suggesting rename did NOT fail (at least not synchronously).

4. **`ss -lxp` historical-bind-path display**: even after PR #73's guard ran, when the operator did `ss -lxp` post-restart, the listening path STILL showed `ctl.sock.<pid>.tmp` (not `ctl.sock`). This is because Linux's `/proc/net/unix` (which `ss` reads) caches the path used at `bind()` time, not the current file system path. After `rename()`, the inode's kernel-side bind path is NOT updated — only the directory entry is. This is a kernel behavior, not a tracker bug. Verify: webctl client `connect("/run/godo/ctl.sock")` resolves the path through filesystem → finds inode → connects → matches the listening socket regardless of `ss` display. So `ss` display is misleading but operationally fine.

## Scope of issue#18

### Must-fix (real fixes, not just diagnostics)

- **MF1**: Add atexit/destructor handler in tracker that explicitly `unlink`s `ctl.sock` on graceful shutdown. SIGTERM-during-init is the operator-locked stop signal — leaving stale state across stop+start is a known footgun.
- **MF2**: Improve rename-failure logging to write to `journal` (via `stderr` since the unit's `StandardError=journal`). Current `throw std::runtime_error("uds_server::open: rename(...): ...")` should include the path types pre/post (lstat both before throw). Operator should be able to grep journal for "rename" and see context.
- **MF3**: Identify and fix the source of stale 0-byte `ctl.sock`. Most likely: another component (webctl? install.sh?) is touching the path. Find via `inotifywait` on `/run/godo/` during a problematic boot cycle, or audit all reads/writes in webctl + tracker + install.sh.

### Should-fix (defensive depth)

- **SF1**: Apply the same `lstat → unlink-if-non-socket` guard pattern to `mapping@active` UDS sockets (if any exist — verify `mapping.py` and related). Symmetric defense.
- **SF2**: Document the `ss -lxp` historical-bind-path quirk in `doc/uds_protocol.md` (or create such a doc) so operators don't waste time investigating "wrong path" reports.
- **SF3**: pidfile-style stale detection at startup — if the previous instance's pidfile points to a no-longer-running process, force-clean any stale UDS files associated.

### Could-fix (nice-to-have)

- **CF1**: Move `/run/godo/` to a single tracker-only namespace if webctl truly never writes there. Currently `/run/godo/godo-webctl.pid` shows webctl writes its pidfile here — check what else.
- **CF2**: Replace path-based UDS with abstract namespace UDS (Linux-specific, `\0`-prefixed sun_path). No filesystem entry → no stale-state class. Tradeoff: loses filesystem permissions, requires both ends to use abstract namespace.

## Cross-references

- **uds_server.cpp** invariant in `production/RPi5/CODEBASE.md` (currently no dedicated invariant for atomic-rename; consider adding `(u)` for "UDS-bootstrap-atomic-rename-with-stale-guard" if issue#18 expands the surface).
- PR #73 commit message details the quick fix.
- `feedback_post_mode_b_inline_polish.md` documents how this guard was absorbed inline post-Mode-B.

## When to ship issue#18

No urgency — quick fix is in place. Operator-locked priority puts issue#18 at #1 in the next-session queue, but timing is operator's call. If repeated stale-state events occur in production (operator observes), promote to immediate. If 1-2 weeks pass without recurrence, lower-priority depth audit.

Estimated: 50-100 LOC across uds_server.cpp + (possibly) mapping.py + new test cases + doc/uds_protocol.md (if created).
