---
name: issue#26 cross-device latency measurement tool — paused at Mode-A round 1 reject
description: Python tool under /tools/latency_measure/ (RPi5 ↔ MacBook on broadcasting-room wired LAN). Captures FreeD UDP egress + recv timestamps + SSE recv + clock sync, writes to test_sessions/<TS_ID>/<device>.csv. Plan + Mode-A fold ready; rework deferred per operator decision 2026-05-03 ~15:00 KST.
type: project
---

## What

Python measurement tool that runs as an agent pair (RPi5 + MacBook). Captures cross-device timestamps with packet-identity matching (last-N bytes + FreeD checksum), so analyst can compute end-to-end latency from RPi5 UDP egress to MacBook UDP/SSE arrival. Designed to inform issue#11 Live pipelined-parallel architecture decision empirically.

**Status: PAUSED at Mode-A round 1 REJECT**. Plan body + Mode-A fold persisted at `.claude/tmp/plan_issue_26_latency_measurement_tool.md`. Round 2 deferred per operator decision (origin-pick + yaw rotation get next-session priority instead).

## Where it lives

- **Plan + Mode-A round 1 fold**: `.claude/tmp/plan_issue_26_latency_measurement_tool.md` (lines 1-849; Mode-A starts at line 634).
- **Design context**: `/doc/issue11_design_analysis.md` §5.2 (operator-locked test surface) + §5.2 packet-identity matching detail.
- **Companion memory**: `project_issue11_analysis_paused.md` (why this tool exists).

## Operator-locked spec (twentieth-session, 2026-05-03 KST)

### Scope
- Two devices: **RPi5** (production tracker host) + **MacBook** (operator's dev laptop).
- Wired Ethernet in broadcasting room, same /24 subnet.
- Broadcasting PC **explicitly out of scope** — server gating prod traffic; dev tool installation too risky.
- Agent-pair model: SSH starts RPi5 agent; MacBook agent runs locally; both write CSV to shared git-tracked dir; Ctrl+C within ~10 s.
- Folder: `/tools/latency_measure/` (new top-level, UV-managed Python ≥ 3.13 — match godo-webctl).

### Output layout
```text
<repo-root>/test_sessions/<TS_ID>/
├─ RUN_ID.txt
├─ rpi5-tracker.csv             # RPi5 sniffer + clock-sync server CSV
├─ rpi5-tracker.meta.json
├─ macbook-dev.csv              # MacBook UDP recv + SSE recv + clock-sync client CSV
├─ macbook-dev.meta.json
└─ clock_sync_<TS_ID>.json
```

### Measurement points (5)
1. RPi5 UDP egress (raw socket sniffer — does NOT modify tracker).
2. RPi5 UDP echo server (clock-sync server).
3. MacBook UDP receive (FreeD packet arrival).
4. MacBook SSE receive (`/api/last_pose/stream` from webctl).
5. MacBook clock-sync client.

### Out of MVP scope
- Webctl-side SSE send-timestamp instrument (separate PR).
- Tracker-side cold-path stage instrumentation (issue#11 follow-up).
- Broadcasting PC measurement (operator decision).
- Auto-analysis / pandas notebook (operator analyzes manually post-capture).
- GPS PPS hardware sync.

### Packet-identity matching (operator detail, 2026-05-03 ~14:30 KST)
Each log line records `(timestamp, last_N_bytes_of_payload, checksum)` rather than full payload. For FreeD UDP (29-byte structured packet): `last 4 bytes payload + 1-byte D1 checksum = 5-byte match key`. Analyst grep-joins by checksum across rpi5-tracker.csv and macbook-dev.csv.

### NTP infrastructure (operator detail, 2026-05-03 ~15:00 KST)
Office network has NTP reference server on the gateway. Both devices peer to it for baseline time discipline (cross-device offset ~0.2-2 ms RMS, drift ≈ 0 over 30-min run). The in-tool 4-timestamp clock-sync is per-run sanity check on top of this baseline. **Both layers are needed** — gateway NTP alone doesn't give per-run offset record; in-tool sync alone doesn't bound drift over 30 min.

### UDP target IP+port — config.toml SSOT
`network.ue_host` + `network.ue_port` are already SSOT in `production/RPi5/src/core/config_schema.hpp:140`. Live state at twentieth-session close: `ue_host = "192.168.0.0"`, `ue_port = 6666` in `/var/lib/godo/tracker.toml`. Operator may update before tomorrow's measurement (mentioned 50003). Tool design: agent reads target IP+port from `/var/lib/godo/tracker.toml` at startup, with CLI postfix override (`--target-port`, `--target-host` or env `GODO_LATENCY_TARGET_PORT/HOST`). Hardcoding any value in tool source is forbidden.

## Mode-A round 1 verdict (REJECT — REWORK REQUIRED)

7 Critical, all source-verified against live news-pi01 state. **Architecture itself is sound** — rework is focused factual fixes (~half-day for Planner round 2):

| # | Plan claim | Reality | Fix |
|---|---|---|---|
| C1 | clock-sync offset formula `((t1 - server_tai_t1 + ...) // 2` | Dimensionally invalid (mixes monotonic_ns + TAI_ns in one subtraction). Protocol carries 1 server timestamp; NTP needs 2 (`t1` recv + `t2` send) | Rewrite §4.3 protocol: `(server_tai_t1, server_tai_t2, seq)`. Standard NTP: `offset = ((t1-t0) + (t2-t3))/2`, all in cross-host TAI domain. Asymmetry detector reframe to "RTT-variance / minimum-RTT-stability" — true asymmetry is structurally unobservable with 4-timestamp NTP |
| C2 | "Zero packet" checksum = `0x92` | Correct value `0x6E` (Planner inverted subtraction direction). Verified `XR_FreeD_to_UDP/src/main.cpp:185-191` + `production/RPi5/src/freed/d1_parser.cpp:18-31` | Fix §6.4 case 1 to `0x6E`; add case 0 (all-zero packet) with `0x40` |
| C3 | UDP target port `50001` hardcoded in plan | Live `ue_port = 6666` per schema row 140; SSOT exists in tracker.toml | Agent reads target IP+port from live `/var/lib/godo/tracker.toml`; CLI postfix override; record in meta.json |
| C4 | `CLOCK_TAI` for leap-second avoidance | RPi5 kernel TAI offset = 0 → TAI ≈ REALTIME today; introduces 37-second silent step risk if asymmetric configuration ever applied | Drop CLOCK_TAI; standardize on CLOCK_REALTIME everywhere; document the leap-second risk acceptance |
| C5 | Pidfile `/tmp/godo-latency-*.pid` | CLAUDE.md §6 mandates `/run/godo/<service>.pid` | `/run/godo/godo-latency-<role>.pid` on Linux; per-platform Tier-2 default for macOS |
| C6 | "chrony installed on RPi5" | Live: `chrony=inactive`, `systemd-timesyncd=active` | §4.2 + §10 R12 + HIL pre-conditions — drop chrony refs; "use whatever NTP service the host already runs" |
| C7 | SSE endpoint `https://10.10.204.123:8080/...` | Live: `http://0.0.0.0:8080` plain HTTP | Change scheme to `http://`; accept either via env `GODO_LATENCY_WEBCTL_BASE` |

12 Major + 11 Minor → see Mode-A fold for full list.

## Key Mode-A insights worth preserving

- **Asymmetry is structurally unobservable** with 4-timestamp NTP between RPi5↔MacBook. Reframe as RTT-variance / minimum-RTT-stability detector. True asymmetry detection requires PTP HW timestamping or GPS PPS or known-symmetric ground truth.
- **Kernel-stamp via `SO_TIMESTAMPNS_NEW` cmsg** is the right egress timestamp source on AF_PACKET (saves 50-200 µs scheduling jitter vs Python userspace `recvfrom()` time). Record both for transparency.
- **Considered alternatives missing in Round 1**: tcpdump+pcap (kernel-stamped, scapy/pyshark post-process), `owamp` one-way active measurement, `bpftrace kprobe:ip_send_skb` for ns-precision. Round 2 should mention these as "considered, not chosen because [reason]".
- **Real interface auto-detect needed**: agent reads `ip route get <ue_host>` at startup to find egress interface, NOT hardcoded `eth0` (which is currently DOWN on news-pi01).

## Resumption procedure (when issue#26 resumes)

1. Read this memory + `project_issue11_analysis_paused.md` for context.
2. Read full Mode-A fold at `.claude/tmp/plan_issue_26_latency_measurement_tool.md` lines 634-849.
3. Run **Planner round 2** with brief that absorbs every Critical fix + Major reframe inline. Plan path stays the same; round 2 replaces §1-§16 body and renames the round-1 Mode-A fold to "(HISTORICAL — superseded by round 2)".
4. **Mode-A round 2** verifies the 10 specific check-items at end of round-1 fold (lines 834-846).
5. Writer implements per approved plan. Operator drives HIL on news-pi01 + MacBook in broadcasting room (~30 min capture).
6. PR opens after Mode-B; operator runs first capture; data lands in `test_sessions/<TS_ID>/`. issue#11 analysis (paused) can resume on this data.

## Why deferred (operator decision, twentieth-session)

The Mode-A REJECT happened at ~14:40 KST after a long deep-analysis afternoon. Operator chose to:
1. Origin-pick + yaw-rotation (issue#6 / B-MAPEDIT-3 family) is concrete, immediately verifiable, no algorithmic dependency on measurement data — perfect for next session.
2. Measurement tool round 2 + Writer + HIL is a half-day effort that operator can drive at office tomorrow with full focus.

Decision feels right: ship the SPA feature first (operator's daily-use surface), let the measurement tool round 2 happen with a clear head + physical access to broadcasting-room wiring on the same day.
