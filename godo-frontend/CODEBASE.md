# godo-frontend — codebase map

## Scope

GODO 운영자 SPA. P0 페이지 4개 (DASH / MAP / AUTH / LOCAL) + 공통 shell
(TopBar / Sidebar / 테마). 백엔드는 PR-A에서 완성된 godo-webctl;
프론트는 HTTP/SSE wire만 알고 UDS는 모른다.

## Directory layout

```text
godo-frontend/
├─ package.json                       # pinned deps; npm scripts
├─ vite.config.ts                     # svelte plugin + dev proxy + path aliases
├─ tsconfig.json                      # strict, $lib/$stores/$components
├─ svelte.config.js                   # vitePreprocess + runes mode
├─ eslint.config.js                   # flat config (ESLint 9)
├─ .prettierrc / .prettierignore
├─ index.html                         # SPA shell, favicon link
├─ public/
│   └─ favicon.svg                    # :D glyph (FRONT_DESIGN §3 G-Q3)
├─ /src
│   ├─ main.ts                        # mount(App, #app)
│   ├─ App.svelte                     # router shell + auth gate
│   ├─ routes.ts                      # path → component map
│   ├─ /lib                           # framework-free helpers (no Svelte)
│   │   ├─ constants.ts               # SPA-internal Tier-1
│   │   ├─ protocol.ts                # wire-shape mirror of godo-webctl/protocol.py
│   │   ├─ router.ts                  # 30-line hash-router (per N9)
│   │   ├─ api.ts                     # apiFetch/apiGet/apiPost/apiPatch
│   │   ├─ auth.ts                    # login/logout/refresh/getClaims
│   │   ├─ sse.ts                     # SSEClient (token-on-URL + visibility)
│   │   └─ format.ts                  # Korean-friendly time/distance formatters
│   ├─ /stores
│   │   ├─ auth.ts                    # Writable<AuthSession|null> + localStorage
│   │   ├─ lastPose.ts                # SSE-fed; polling fallback
│   │   ├─ mode.ts                    # /api/health polled @ 1 Hz
│   │   └─ theme.ts                   # 'light' | 'dark', persisted
│   ├─ /components
│   │   ├─ TopBar.svelte              # session info + theme toggle + logout
│   │   ├─ Sidebar.svelte             # nav; LOCAL row only on loopback host
│   │   ├─ ModeChip.svelte            # Idle | OneShot | Live
│   │   ├─ ServiceCard.svelte         # systemd service status + actions
│   │   ├─ PoseCanvas.svelte          # canvas overlay + pan/zoom/trail
│   │   └─ ConfirmDialog.svelte       # reused for reboot/shutdown
│   ├─ /routes
│   │   ├─ Dashboard.svelte           # B-DASH
│   │   ├─ Map.svelte                 # B-MAP
│   │   ├─ Login.svelte               # B-AUTH
│   │   ├─ Local.svelte               # B-LOCAL (loopback-gated)
│   │   ├─ System.svelte              # B-SYSTEM (anon-readable; admin-gated buttons)
│   │   ├─ Backup.svelte              # B-BACKUP (anon-readable; admin-gated restore)
│   │   └─ NotFound.svelte
│   └─ /styles
│       ├─ tokens.css                 # CSS variables (light/dark)
│       └─ global.css                 # base + layout + chip/button/card
└─ /tests
    ├─ /unit                          # vitest
    │   ├─ api.test.ts                # 9 cases
    │   ├─ auth.test.ts               # 11 cases
    │   └─ sse.test.ts                # 9 cases
    └─ /e2e                           # playwright
        ├─ playwright.config.ts
        ├─ _stub_server.py            # stdlib HTTP server, mirrors webctl wire
        ├─ login.spec.ts              # 3 cases
        ├─ dashboard.spec.ts          # 3 cases
        ├─ map.spec.ts                # 2 cases
        └─ local.spec.ts              # 3 cases
```

## Dependency graph

```text
constants.ts ◄──── protocol.ts ◄────┐
                                     │
              router.ts ◄─── api.ts ◄┤
                                     ├── stores/* ◄──── components/* ◄── routes/*
              auth.ts (lib) ◄────────┤
              sse.ts ◄───────────────┤
              format.ts ◄────────────┘
```

`stores/auth.ts` wires `lib/api.ts` via `configureAuth({ getToken,
onUnauthorized })` at module-init — that's the only back-edge from a
store into a lib, deliberate and one-way.

## Module responsibilities

| Module                           | Responsibility                                                                                                                                                              |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lib/constants.ts`               | SPA-internal Tier-1. **Every numeric literal in `src/` MUST trace here, to `protocol.ts`, or to a local iteration bound.**                                                  |
| `lib/protocol.ts`                | Wire-shape mirror of `godo-webctl/src/godo_webctl/protocol.py` — types, mode names, error codes, LAST_POSE_FIELDS order.                                                    |
| `lib/router.ts`                  | 30-line hash-router. Emits `route` rune; `navigate(path)` updates `location.hash`.                                                                                          |
| `lib/api.ts`                     | `apiFetch` adds Bearer header from auth store; 401 → clearSession + nav `/login`; non-2xx → throws `ApiError`.                                                              |
| `lib/sse.ts`                     | `SSEClient` — token-on-URL (Q3), Page Visibility handbrake, expired-token guard before reconnect.                                                                           |
| `lib/auth.ts`                    | `login/logout/refresh/getClaims/isExpired`. Decode-only on token (server is the SSOT for trust).                                                                            |
| `lib/format.ts`                  | Korean-friendly formatters for topbar countdown + pose readouts.                                                                                                            |
| `stores/auth.ts`                 | Persisted `AuthSession`. Writes from outside limited to `setSession/clearSession`.                                                                                          |
| `stores/lastPose.ts`             | SSE-fed `LastPose`; refcounts subscribers; polling fallback when SSE drops.                                                                                                 |
| `stores/mode.ts`                 | Polls `/api/health` at HEALTH_POLL_MS; supports `setModeOptimistic` after button clicks.                                                                                    |
| `stores/theme.ts`                | Light/dark theme; persisted in localStorage; sets `data-theme` attribute on `<html>`.                                                                                       |
| `components/PoseCanvas.svelte`   | Canvas with pan/zoom/trail; world↔canvas conversion via `mapMetadata.resolution + .origin + .height`.                                                                      |
| `lib/mapYaml.ts`                 | Pure parser for ROS map_server YAML (`image`, `resolution`, `origin`, `negate`); throws `MapYamlParseError` on malformed input.                                             |
| `stores/mapMetadata.ts`          | Composes `parseMapYaml` + `/api/maps/<name>/dimensions` fetch; refetches on `mapImageUrl` change with AbortController-cancelled previous load.                              |
| `components/MapListPanel.svelte` | Track E (PR-C). Lists every map under `${GODO_WEBCTL_MAPS_DIR}`; admin-gated activate / delete actions; reuses `<ConfirmDialog/>` with the optional `secondaryAction` prop. |
| `stores/maps.ts`                 | Track E. `Writable<MapEntry[]>` + `refresh()` / `activate(name)` / `remove(name)`. No periodic polling — refresh on mount, post-activate, post-remove only.                 |
| `routes/*.svelte`                | Page composition only — no business logic; orchestrate via stores + lib calls.                                                                                              |

## Invariants

### (a) Token-on-URL for SSE (per Q3 user decision)

`EventSource` cannot send custom headers, so SSE auth happens via
`?token=…` query param. Backend `_extract_bearer` accepts the fallback;
backend uvicorn access-log strips `?token=…` from URL lines so the
token never lands in journald.

`SSEClient` is the SOLE place that builds an `?token=` URL — components
must NOT construct EventSource directly.

### (b) Loopback gate is two-layer

The B-LOCAL page checks `window.location.hostname` against
`LOCAL_HOSTNAMES = ['127.0.0.1', 'localhost', '::1']` BEFORE making any
`/api/local/*` calls. The backend separately enforces 403 via
`Depends(loopback_only)`. **Both gates must agree.** Adding `'192.168.x.y'`
to `LOCAL_HOSTNAMES` without changing the backend gate would expose
controls that the backend then rejects — bad UX. Adding to the backend
without the frontend would surface the page on hosts that can't actually
use it.

### (c) No business logic in components

`routes/*.svelte` and `components/*.svelte` orchestrate via store
subscriptions + lib calls. The wire shapes belong to `lib/protocol.ts`;
the fetch/SSE plumbing belongs to `lib/{api,sse}.ts`. A component that
constructs JSON request bodies inline or massages backend responses with
ad-hoc transforms is a code-review block.

### (d) CSS-variable-only theming

Light/dark toggle flips `data-theme` on `<html>`; every visual difference
is a CSS variable in `src/styles/tokens.css`. Components MUST NOT branch
on theme value — read variables and let the cascade decide.

The PoseCanvas exception: canvas drawing uses hex literals
(`MAP_TRAIL_COLOR`, `MAP_POSE_COLOR`) because canvas is rasterised and
doesn't see CSS variables. Documented in-file.

### (e) No magic numbers

Every numeric literal in `src/` resolves to one of:

- a named export in `lib/constants.ts`
- a wire-side mirror in `lib/protocol.ts`
- a local iteration bound (e.g. `for (let i = 0; i < trail.length; i++)`)
- a CSS variable (in `.css` files only — CSS is not subject to the rule)

Reviewer Mode-B will fail any literal that violates this. Numeric literals
in tests are exempt (test fixtures are intentional values).

### (f) Wire SSOT — `lib/protocol.ts` mirrors `godo-webctl/src/godo_webctl/protocol.py`

Hand-mirrored. Drift detection is by inspection during code review +
backend's own `tests/test_protocol.py` (which regex-pins the C++ side).
Adding a field to `LAST_POSE_FIELDS` requires the same diff in:

1. C++ `production/RPi5/src/uds/json_mini.cpp::format_ok_pose`
2. `godo-webctl/src/godo_webctl/protocol.py::LAST_POSE_FIELDS`
3. `godo-frontend/src/lib/protocol.ts::LAST_POSE_FIELDS`

The frontend e2e stub server's canned `_canned_pose()` should also be
updated to include the new field.

### (g) Token persistence + cross-tab sync

`AuthSession` lives in `localStorage` under key `STORAGE_KEY_TOKEN =
'godo:auth'`. The auth store reads on init and writes on every change.
Cross-tab synchronisation is NOT implemented in P0 — closing the original
tab's session does not clear other tabs until they next reload. Acceptable
for P0 (1-2 operators, single window typically).

### (h) Default light theme

Theme defaults to `'light'` when `localStorage` is empty. Per
FRONT_DESIGN §3 G-Q4 (user decision: 라이트 default + 회색 톤). The
toggle flips between `'light'` and `'dark'`; no system-preference
auto-detect because the device may be a kiosk display with no OS-level
theme signal.

### (i) Test surface — playwright runs on dev machines only (per N8)

Playwright Chromium binary download (~170 MB) is gated behind
`npm run test:e2e` and is intended for developer machines (Mac/Linux x86).
RPi 5 CI runs only `npm run test:unit` (vitest, ~30 cases) plus the
backend `uv run pytest` suite. The e2e suite uses the in-tree
`tests/e2e/_stub_server.py` (stdlib only) so no real RPi backend is
required to run them.

### (k) Map-name regex mirror (Track E, PR-C)

`MAPS_NAME_REGEX_PATTERN_STR` in `src/lib/protocol.ts` MUST equal the
backend `MAPS_NAME_REGEX.pattern` from
`godo-webctl/src/godo_webctl/constants.py`. The frontend uses the
pattern for client-side `activate(name)` / `remove(name)`
short-circuiting (so a typo never hits the network). The backend
re-validates inside `maps.validate_name` (defence-in-depth — same
regex, different process).

Drift detection: by inspection during code review, plus the backend's
`tests/test_protocol.py::test_maps_name_regex_pattern_str_mirrors_constants`
which pins the backend mirror against `constants.py`. The frontend
mirror cannot be auto-checked at test time; the inspection contract is
that any change to the regex updates BOTH files in the same commit.

### (l) `<ConfirmDialog/>` accepts an optional `secondaryAction` (Track E, PR-C)

`components/ConfirmDialog.svelte` was extended (NOT replaced) with
optional props:

- `secondaryAction?: { label, handler } | null` — when set, renders a
  third button between cancel and confirm. The dialog still renders
  cancel + primary as before; reuses the same theming / a11y patterns.
- `showPrimary?: boolean` — when `false`, the primary (`onConfirm`)
  button is hidden and replaced with a tooltip placeholder. Used by
  `MapListPanel` to hide the "godo-tracker 재시작" button on
  non-loopback hostnames per Mode-A M4.
- `primaryHiddenTooltip?: string` — hover text for the placeholder.

A new `MultiActionDialog` was considered and rejected: the existing
component is small enough that two more optional props are cheaper
than a parallel implementation that would have to keep the same
theming + a11y discipline.

### (m) Track D — scan-overlay freshness uses arrival-wall-clock (Mode-A M2)

The `LastScan` wire body carries two clocks:

- `published_mono_ns` — tracker `CLOCK_MONOTONIC` ns at publish; an
  ORDERING primitive only.
- `_arrival_ms` — client-side, set inside `stores/lastScan.ts` at
  `Date.now()`-time of SSE frame arrival; never on the wire.

The freshness gate (`PoseCanvas.svelte::redraw`, `ScanToggle.svelte`)
computes `Date.now() - lastScan._arrival_ms` against
`MAP_SCAN_FRESHNESS_MS = 1000`. Subtracting `published_mono_ns`
directly from `Date.now()` would mix tracker monotonic time and
browser wall-clock — meaningless. The store stamps `_arrival_ms` on
every frame BEFORE pushing to subscribers, so the gate is computed in
a single clock domain.

Pinned by:

- `tests/unit/lastScan.test.ts::stamps _arrival_ms on every received frame (Mode-A M2)`,
- `tests/unit/poseCanvasFreshness.test.ts` (data-scan-fresh attribute
  flips when fake timers advance past the freshness window).

### (n) Track D — SPA does the polar→Cartesian transform; uses the SCAN's anchor pose (Mode-A TM5)

The server (`godo_tracker_rt`) emits raw polar (`angles_deg` +
`ranges_m` in the LiDAR frame) plus the anchor pose
(`pose_x_m / pose_y_m / pose_yaw_deg`) baked into the SAME LastScan
frame. The SPA does the world-frame transform using the SCAN's own
anchor — NOT the parallel `lastPose` store.

Reasoning: the AMCL pose at the moment the cold writer processed THIS
scan is exactly correct for THIS scan; using a separately-fetched
pose would re-introduce the SSE-skew the brief explicitly avoids.
The transform lives in `lib/scanTransform.ts::projectScanToWorld` so
unit tests can exercise the math without mounting the full
PoseCanvas component.

Mode-A M3 fold: `projectScanToWorld` returns an empty array unless
`scan.valid === 1 && scan.pose_valid === 1`. `pose_valid === 0`
means the AMCL run that produced this scan did not converge; the
anchor coordinates are undefined zeros, and rendering them would
mislead the operator.

Pinned by `tests/unit/poseCanvasScanLayer.test.ts` — TB2's three
non-trivial yaw cases (yaw=90°+beam=0°; yaw=45°+beam=0° to catch
x/y-swap; yaw=0°+beam=90° to catch yaw-vs-beam-angle confusion) +
gating tests + the TB1-equivalent positional integrity sweep.

### (o) Track D — `lastScan` SSE is gated on the `scanOverlay` toggle

The `lastScan` store opens its underlying `SSEClient` ONLY when
the `scanOverlay` store is `true` AND there is at least one
subscriber. The gating lives inside `stores/lastScan.ts`, not in
`Map.svelte`. Operators who never flip the toggle on never trigger
the tracker UDS `get_last_scan` round-trip; the cold writer's seqlock
publish is unaffected (Track D's "0 hot-path impact" promise extended
to the webctl layer).

`scanOverlay` persists in `sessionStorage` (NOT `localStorage`, per
Q-OQ-D2): same-tab reload preserves the operator's choice; new tab /
new operator session defaults OFF. The overlay generates ~30-60 KB/s
of WAN traffic at 5 Hz; OFF-by-default for any new session is the
defensive baseline.

Pinned by:

- `tests/unit/lastScan.test.ts::does not start SSE while overlay is off`,
- `tests/unit/lastScan.test.ts::starts SSE when overlay flips to on`,
- `tests/unit/lastScan.test.ts::stops SSE when overlay flips back to off`,
- `tests/unit/scanOverlay.test.ts` (4 cases — default off, persist,
  restore, toggle round-trip),
- `tests/e2e/map.spec.ts::scan toggle state persists through same-tab reload`.

### (p) PR-DIAG — Diagnostics store opens SSE only when subscribers exist

The `diag` store (`stores/diag.ts`) opens its underlying `SSEClient`
ONLY when at least one subscriber is registered (refcounted via
`subscribeDiag(fn)` → returns unsub closure). The gating lives inside
the store, NOT in `routes/Diagnostics.svelte`. A page that doesn't
mount the Diagnostics route never triggers `/api/diag/stream`; multiple
mounts share one SSE.

`_arrival_ms` is stamped on every frame on receipt (Mode-A M2 +
PR-DIAG N4 fold extension). The freshness gate in `Diagnostics.svelte`
reads `Date.now() - frame._arrival_ms`, NOT `published_mono_ns`
deltas (clock-domain mismatch — the C++ tracker's CLOCK_MONOTONIC and
the webctl-side `time.monotonic_ns()` are SEPARATE clock domains and
must never be compared).

Pinned by:

- `tests/unit/diag.test.ts::does not open SSE when there are no subscribers`,
- `tests/unit/diag.test.ts::sse opens on first subscribe and closes on last unsubscribe`,
- `tests/unit/diag.test.ts::stamps _arrival_ms on every received frame`.

### (q) PR-DIAG — JournalTail allow-list mirrors webctl

`components/JournalTail.svelte` hardcodes the allow-list dropdown
options as `['godo-tracker', 'godo-webctl', 'godo-irq-pin']` —
mirroring `godo_webctl.services::ALLOWED_SERVICES`. Drift detected by
inspection during code review (per OQ-DIAG-3). The webctl-side rejects
a non-listed unit anyway (HTTP 404 `unknown_service`) so a SPA-side
drift surfaces as a sad-UX 404, not a security hole.

`n` input is clamped client-side to `LOGS_TAIL_MAX_N_MIRROR = 500`;
the server's Pydantic `Field(le=...)` is the authoritative cap.

### (t) Track B-SYSTEM PR-2 — services panel polls `/api/system/services` at 1 Hz, no SSE

`routes/System.svelte` adds a 5th panel rendering one
`<ServiceStatusCard/>` per allow-listed GODO service. Polls
`/api/system/services` via `setInterval(SYSTEM_SERVICES_POLL_MS = 1000)`
through `stores/systemServices.ts` (refcounted; opens on first
subscribe, closes on last). The timer is captured in `onMount` and
cleared in `onDestroy` (T5 fold pin: `vi.getTimerCount() === 0` after
the last unsub). 1 Hz × 1 s backend cache TTL is the matched cadence;
an SSE was rejected because operator UX gains nothing over the polled
shape.

Chip-class is single-sourced in `$lib/serviceStatus.ts` (1-export
module: `STATUS_TO_CHIP` map + `statusChipClass(s)`) and re-used by
both `ServiceCard` (loopback-admin actions on `/local`) and
`ServiceStatusCard` (read-only-or-admin twin on `/system`) so the two
cannot drift.

Both cards render `body.detail` (Korean) on a 409
`service_starting`/`service_stopping` response in their existing
`lastError` slot, with auto-dismiss after
`SERVICE_TRANSITION_TOAST_TTL_MS = 4000`. The dismiss timer is cleared
in `onDestroy`. ServiceStatusCard ALSO shows admin Start/Stop/Restart
buttons gated by `$isAdmin`; the click POSTs to
`apiSystemServiceAction(name, action)` which builds the
`/api/system/service/<name>/<action>` path. Anon viewers see the
read-only card with no buttons.

Stale-banner: when `Date.now() - svcState._arrival_ms >
SYSTEM_SERVICES_STALE_MS = 3000`, the panel header shows a "데이터
갱신 지연" inline tag (mirror of the Diagnostics page stale-banner
pattern; same `renderTick` heartbeat re-evaluation).

Pinned by `tests/unit/system.test.ts` (services panel renders + admin
button visibility + anon hides buttons + clicking restart POSTs to the
right path), `tests/unit/systemServices.test.ts` (T4 fold: exactly 4
fetches in 3500 ms; T5 fold: timer count drops to 0 on unmount),
`tests/unit/serviceStatus.test.ts` (chip-class drift catch),
`tests/unit/format.test.ts` (formatUptimeKo + formatBytesBinaryShort
corpus with S4 fold "51 MiB" pin), and `tests/e2e/system.spec.ts`
(3 new playwright cases: services panel renders, env collapse reveals
mixed redacted/non-redacted KEYs per T6 fold, admin restart click
under stub 409 surfaces Korean detail toast).

### (y) Track B-SYSTEM PR-B — System page sub-tab pattern + PR-B SSE stores

`routes/System.svelte` switches from a single-panel-list layout to a
sub-tab layout with three keys: `overview` (default — wraps the
original PR-SYSTEM panels), `processes`, `extended`. The sub-tab key
is held in component-local `$state` (`activeSubtab`); the URL doesn't
reflect it.

Discipline rationale:

1. **Component-local state, intentional reset on route change**
   (Final fold S3): operator clicks `/map` then comes back to
   `/system`, the sub-tab returns to `overview` and the search
   filter clears. Persisting via URL hash is a follow-up if
   operators request it (Risk R10 deferred).
2. **No new dependency** for the popover primitive (Final fold O2):
   the `i 도움말` block in `<ProcessTable/>` is a vanilla HTML5
   `<details><summary>` disclosure — click-to-toggle, NOT hover.
3. **Filters are CLIENT-SIDE only** (Mode-A S1 fold): the SSE URL
   carries only the `token` query param. A future writer adding
   `?filter=foo` to the SSE wire fails the `processes.test.ts`
   "SSE URL has only the token param" pin.
4. **Refcounted SSE per stream** (mirror of invariant (p)):
   `subscribeProcesses` / `subscribeResourcesExtended` share one
   `EventSource` across multiple subscribers; the underlying SSE
   closes only when the last subscriber unsubscribes. Pinned by
   `processes.test.ts::shares one SSE across multiple subscribers
   (refcounted)` and the equivalent in `resourcesExtended.test.ts`.
5. **`_arrival_ms` stamped per frame** (Mode-A M6, mirror of
   invariant (m)): both PR-B stores stamp `Date.now()` on every
   received SSE frame so freshness gates use arrival-wall-clock,
   never `published_mono_ns` across the C++/webctl boundary.
6. **Typography over background shading** (Final fold §5 + Mode-A
   M5 + O1): managed-category process names render in
   `font-weight: bold` + `color: var(--color-status-warn)` — the
   existing token, no new colors. Duplicate rows get a
   `border-left: var(--border-width-emphasis) solid var(--color-status-err)`
   on the name cell only. New token: `--border-width-emphasis: 3px`
   in `tokens.css` (the only new token; reused colors from existing
   `--color-status-{warn,err}`).
7. **No raw hex literals** in `ProcessTable.svelte` or
   `ResourceBars.svelte` (per invariant (d)): every color references
   `var(--color-*)` from `tokens.css`. Verified by inspection
   during code review; mirror of invariant (e) "no magic numbers"
   discipline applied to colors.
8. **Cross-language SSOT** mirrored in `lib/protocol.ts`:
   `PROCESS_FIELDS` (10 fields), `EXTENDED_RESOURCES_FIELDS`
   (6 fields, GPU absent), `MANAGED_PROCESS_NAMES`,
   `GODO_PROCESS_NAMES`. Drift detected by inspection per
   the existing wire-mirror discipline.

Pinned by:

- `tests/unit/processes.test.ts` (6 cases — SSE refcount,
  `_arrival_ms` stamping, duplicate-alert propagation, token-only
  URL, malformed-payload drop).
- `tests/unit/resourcesExtended.test.ts` (4 cases — refcount,
  `_arrival_ms`, null GPU-style fields, malformed-payload drop).
- `tests/unit/processTable.test.ts` (8 cases — sort order, text
  search, GODO-only toggle, duplicate banner + per-row marker,
  info popover bullets, managed-category class, count summary).
- `tests/unit/system.test.ts` (existing 11 cases continue to pass —
  the sub-tab wrapping defaults to `overview` so existing panels
  still render on mount).

### (j) Router is home-grown (per N9)

The plan called for `svelte-spa-router@~4`. After install the package's
own description still reads "Router for SPAs using Svelte 4". Rather than
ship a router that explicitly targets the prior major version, we wrote
a 30-line hash-router (`src/lib/router.ts`). The trade-off: no nested
routes, no params (e.g. `/users/:id`), no transition hooks. None of these
are needed in P0 — every route is a static path.

If a future page needs URL params, replace `matchRoute` with a
trie/prefix matcher in the same file. The `route` rune + `navigate(path)`
contract is what the rest of the SPA depends on; keep that stable.

## Build flow

```text
src/main.ts  →  vite (esbuild)  →  Rollup tree-shake  →  dist/
                  │
                  ├─ Svelte plugin (svelte 5 compiler in runes mode)
                  ├─ TS compiler (strict)
                  └─ CSS transform (autoprefixer not enabled — modern targets only)
```

Bundle target: `es2022` (Chromium ≥ 110, Safari ≥ 16). Source maps
disabled in production build (smaller dist; debug builds use
`--sourcemap`). Chunk size warning limit set to 250 KB.

## Dev proxy

`vite.config.ts` proxies `/api → http://127.0.0.1:8080` in dev mode only.
Production has no proxy — godo-webctl serves both `/` (SPA) and `/api/*`
from the same origin (port 8080), so CORS is never invoked.

## Path aliases

`tsconfig.json` `paths` + `vite.config.ts` `resolve.alias`:

| Alias           | Resolves to        |
| --------------- | ------------------ |
| `$lib/*`        | `src/lib/*`        |
| `$stores/*`     | `src/stores/*`     |
| `$components/*` | `src/components/*` |

These exist to make module imports source-of-truth-explicit (e.g.
`import { apiGet } from '$lib/api'` cannot accidentally resolve to a
node_modules package called `lib`).

## Theme variable map (excerpt)

| Variable             | Light value | Dark value | Used by                   |
| -------------------- | ----------- | ---------- | ------------------------- |
| `--color-bg`         | `#f5f5f7`   | `#1d1d20`  | `body`                    |
| `--color-bg-elev`    | `#ffffff`   | `#28282b`  | `.card`, topbar           |
| `--color-text`       | `#2c2c30`   | `#e6e6e9`  | global                    |
| `--color-accent`     | `#1565c0`   | `#4a8be0`  | primary buttons, link     |
| `--color-status-ok`  | `#2e7d32`   | `#66bb6a`  | active chip               |
| `--color-status-err` | `#c62828`   | `#ef5350`  | error chip, danger button |

Full set in `src/styles/tokens.css`.

## Stub server contract

`tests/e2e/_stub_server.py` mirrors the wire shapes of
`godo-webctl/src/godo_webctl/app.py` exactly. **When adding a new
endpoint to the backend, update the stub in the same PR.** Otherwise the
e2e suite goes green on outdated wire shapes and the SPA breaks against
the real backend.

The stub serves both:

- `/api/*` — canned JSON / SSE responses
- `/` and everything else — serves `dist/index.html` (the built SPA)

so a single stub process is enough to drive playwright. No vite
preview proxy needed.

## Change log

### 2026-04-30 14:00 KST — Track B-SYSTEM PR-B (frontend) — System tab sub-tabs

#### Added

- `src/lib/protocol.ts` — `PROCESS_FIELDS` (10), `ProcessEntry`,
  `ProcessesSnapshot`, `EXTENDED_RESOURCES_FIELDS` (6),
  `ExtendedResources`, `MANAGED_PROCESS_NAMES`, `GODO_PROCESS_NAMES`,
  `ProcessCategory` literal type. Mirror of the webctl SSOT in
  `godo_webctl/protocol.py`.
- `src/lib/constants.ts` — `PROCESSES_POLL_FALLBACK_MS`,
  `EXTENDED_RESOURCES_POLL_FALLBACK_MS`, `CPU_BAR_HEIGHT_PX`,
  `SYSTEM_SUBTAB_OVERVIEW`, `SYSTEM_SUBTAB_PROCESSES`,
  `SYSTEM_SUBTAB_EXTENDED`.
- `src/styles/tokens.css` — `--border-width-emphasis: 3px` (NEW
  token; reuses existing `--color-status-{warn,err}` for typography
  colors per Mode-A M5 + Final fold O1).
- `src/stores/processes.ts` — refcounted SSE store for
  `/api/system/processes/stream`. One initial fetch covers
  the SSE-connect gap; `_arrival_ms` stamped per frame.
- `src/stores/resourcesExtended.ts` — same pattern for
  `/api/system/resources/extended/stream`.
- `src/components/ProcessTable.svelte` — sortable table with
  text-search + GODO-only filter + duplicate-alert banner + per-row
  duplicate marker + `<details>`-style info popover (3 documented
  bullet strings per Final fold S4).
- `src/components/ResourceBars.svelte` — per-core CPU bars + mem bar
  + disk bar. No SVG / rings (operator decision); null-tolerant.
- `src/routes/System.svelte` — wraps the existing 5-panel content in
  a default `overview` sub-tab + adds `processes` and `extended`
  sub-tabs. `activeSubtab` is component-local `$state`.
- `tests/unit/processes.test.ts` — 6 cases (SSE refcount,
  `_arrival_ms`, duplicate-alert propagation, token-only URL,
  malformed-payload drop).
- `tests/unit/resourcesExtended.test.ts` — 4 cases.
- `tests/unit/processTable.test.ts` — 8 cases (sort, search, GODO
  toggle, duplicate banner + row marker, popover bullets, managed
  styling, count summary).

#### Changed

- Invariant (y) added (see above).
- `routes/System.svelte` no longer flattens its 5 panels; they live
  inside the default `overview` sub-tab. Existing
  `tests/unit/system.test.ts` (11 cases) continues to pass —
  defaulting to `overview` keeps the original DOM tree on mount.

#### Removed

- (none)

#### Tests

- 164 → 182 hardware-free vitest (+18 from PR-B frontend half).
- `npm run lint` clean on all PR-B paths (no new warnings).

#### Mode-A folds applied

- Final fold (07:09 KST) + Operator decisions:
  - GPU widget dropped entirely (no `gpu_pct` in
    `EXTENDED_RESOURCES_FIELDS`, no GPU panel).
  - All-PID enumeration with category classifier; kernel threads
    excluded.
  - `category` (NOT `class`) wire field name.
  - Sub-tab + filter state component-local; resets on route change.
  - HTML5 `<details><summary>` popover (no new component dep).
  - `--color-status-warn` reused for managed accent; new
    `--border-width-emphasis: 3px` token only.
- M3 — `category` everywhere (no `class`).
- M5 — no raw hex; only token references.
- M6 — `_arrival_ms` stamped per frame; pinned by per-store tests.
- S1 — token-only SSE URL; pinned by `processes.test.ts`.
- S4 — popover-bullets test (`processTable.test.ts`).
- S5 — single banner string (no restart-detection sub-text);
  TODO comment in `ProcessTable.svelte` references the deferred
  Phase 4-5 polish item.

### 2026-04-30 17:30 KST — Track D scale + Y-flip fix

#### Added

- `src/lib/mapYaml.ts` — pure parser for ROS map_server YAML; extracts
  `image / resolution / origin / negate`. Throws `MapYamlParseError`
  on missing or malformed fields; tolerates blank + comment lines.
- `src/lib/protocol.ts` — `MapYaml`, `MapDimensions`, `MapMetadata`
  interfaces. `MapMetadata` composes both wire shapes plus a
  `source_url` field for store-side staleness detection.
- `src/stores/mapMetadata.ts` — `Writable<MapMetadata | null>` +
  `loadMapMetadata(mapImageUrl)`. Parallel-fetches YAML + dimensions
  via `apiFetch` / `apiGet`; AbortController-cancels the previous
  load on rapid name changes (Mode-A T2 fold pin).
- `tests/unit/mapYaml.test.ts` (6 cases — minimal valid + missing
  resolution + bad type + 3-element origin + non-zero theta + comment
  tolerance).
- `tests/unit/mapMetadata.test.ts` (5 cases — parallel fetch + name
  derivation + cancellation race + 404 + parse-error).
- `tests/unit/poseCanvasScale.test.ts` (8 cases — Mode-A T3 hand-
  computed integers: §C-1 identity, §C-2 non-zero origin, §C-3
  Y-flip pin (the fail-then-pass DoD gate per S1), §C-4 direction
  sanity, §C-5 zoom-equiv, §C-6 non-square (M2 rewrite), §C-7
  resolution variance, §C-8 inverse-resolution scaling (T1 rewrite)).
- `tests/unit/poseCanvasImageReload.test.ts` + `_PoseCanvasHost.svelte`
  (Mode-A M3 reactive image refetch — assert exactly 1 fetch on
  initial mount, 2 after first prop change, 3 after second).
- `tests/e2e/map.spec.ts` — 1 new playwright case "scan overlay
  survives wheel-zoom (Track D scale fix)".

#### Changed

- `src/components/PoseCanvas.svelte` — (a) subscribes to
  `$stores/mapMetadata`; (b) `worldToCanvas` / `canvasToWorld` now
  read `metadata.resolution`, `.origin`, `.width`, `.height` (Y-flip
  in the single `H - 1 - (wy - oy)/res` line); (c) image draw uses
  `img.naturalWidth × zoom` anchored to canvas centre — the world
  frame sits on the SAME centre via `(imgCol - width/2)` so the
  overlay aligns with the bitmap at every zoom; (d) `MAP_PIXELS_PER_METER`
  import deleted; (e) reactive `$effect(() => mapImageUrl)` refetches
  BOTH bitmap + metadata on prop change (Mode-A M3); (f) non-zero
  theta warning banner (Mode-A S6); (g) overlay gating extended to
  `meta != null`.
- `src/lib/constants.ts` — DELETED `MAP_PIXELS_PER_METER` (the
  structural witness for the fix).
- `tests/unit/poseCanvasFreshness.test.ts` — inject identity metadata
  mock + add Mode-A S5 case (scan stays fresh when metadata resolves
  at t=400ms because Date.now() - 0 = 400 < MAP_SCAN_FRESHNESS_MS).
- `tests/e2e/_stub_server.py` — new `_h_maps_dimensions(name)` handler
  returning `{width: 200, height: 100}` non-square (so the e2e suite
  exercises the H-1 - (wy-oy)/res row math); existing YAML stub
  unchanged (the earlier "placeholder" claim was a misread per Mode-A
  S4 fold).
- `CODEBASE.md` — module-responsibilities row updated; new invariant
  `(x)` documented.

#### Removed

- `src/lib/constants.ts::MAP_PIXELS_PER_METER` — pre-flight grep
  captured (single hit in `src/`, two hits in `src/components/`).
  Post-deletion grep returns zero hits in `src/`.

#### Tests

- 143 → 164 vitest unit cases (+21 from this PR: 6 mapYaml + 5
  mapMetadata + 8 poseCanvasScale + 1 poseCanvasImageReload + 1
  Mode-A S5 freshness case; existing freshness tests amended in place).
- 36 → 37 passing playwright e2e cases (+1 from `map.spec.ts`). The
  pre-existing `config.spec.ts: anonymous viewer does NOT see the
Config nav row` failure remains red (unrelated to this PR).
- `npm run lint` clean for new files; pre-existing warning in
  `tests/unit/maps.test.ts` is unchanged.
- `npm run build` produces 33.18 kB gzipped JS (was 31.89 kB on
  `main e68e035`; +1.29 KB delta — within the +2.0 KB Mode-A M3+S6
  budget).

#### Mode-A folds applied

- M1: §C-3 rewritten as a fail-on-unfixed test pinning
  `worldToCanvas(0, 0).cy === 249` against the new metadata-aware
  math; FAILED on `main e68e035` (cy=75) and PASSED on the new
  code — fail-then-pass evidence in PR body.
- M2: §C-6 worked example uses non-square `width=200, height=50`
  with origin=[0,0,0]; literal-integer expected coords.
- M3: P4-D5 step iii — reactive `$effect` for image refetch added.
  Pinned by `poseCanvasImageReload.test.ts` via a Svelte 5 host
  component that mutates an internal `$state(url)`.
- M4: webctl invariant tail = `(x)` on `main e68e035`; this PR adds
  `(y)` to webctl. Frontend tail = `(w)`; this PR adds `(x)`.
- S1: §C-3 fail-on-unfixed-then-pass evidence captured.
- S2: pre-flight grep of `MAP_PIXELS_PER_METER` recorded; post-
  deletion grep returns zero hits in `src/`.
- S3: line 102 module-responsibilities row updated to read
  `mapMetadata.resolution + .origin + .height`.
- S5: scan-arrives-at-t=0 / metadata-at-t=400ms / fresh case added
  to `poseCanvasFreshness.test.ts`.
- S6: non-zero theta warning banner in `PoseCanvas.svelte` (visible
  to operator, not a silent `console.warn`).
- T1: §C-8 replaces the vacuous "constant deleted" test with the
  inverse-resolution scaling property (delta_b = 2 × delta_a).
- T2: `mapMetadata.test.ts::cancellation race` strengthened to spy
  on store transitions and assert v1 NEVER leaks into the store.
- T3: §C-1 expected coords are hand-computed literal integers, not
  formula-recomputed.

### 2026-04-29 — Track D: Live LIDAR overlay (Phase 4.5+ P0.5)

#### Added

- `src/lib/protocol.ts` — `LastScan` interface (11 fields), tuple
  `LAST_SCAN_HEADER_FIELDS`, `LAST_SCAN_RANGES_MAX = 720`,
  `CMD_GET_LAST_SCAN`. `_arrival_ms` is documented as a CLIENT-SIDE
  field (set in the SSE adapter, never on the wire).
- `src/lib/constants.ts` — 5 new constants:
  `MAP_SCAN_DOT_RADIUS_PX = 1.5`, `MAP_SCAN_DOT_COLOR = '#26a69a'`
  (teal — Q-OQ-D3 color-blind friendly trio with pose red and trail
  blue), `MAP_SCAN_DOT_OPACITY = 0.7`, `MAP_SCAN_FRESHNESS_MS = 1000`,
  `LAST_SCAN_POLL_FALLBACK_MS = 1000`.
- `src/lib/scanTransform.ts` — pure function `projectScanToWorld(scan)`
  that does the polar→Cartesian world-frame transform using the SCAN's
  own anchor pose (invariant (n)); empty array when validity flags fail
  (Mode-A M3 — pose_valid gate). Extracted so unit tests can exercise
  the math without mounting PoseCanvas.
- `src/stores/scanOverlay.ts` — `Writable<boolean>` toggle store with
  `sessionStorage` persistence (key `godo:scanOverlay`), default OFF,
  `setScanOverlay/toggleScanOverlay/_resetScanOverlayForTests`.
- `src/stores/lastScan.ts` — SSE-fed store + polling fallback,
  refcounted subscribers, lifecycle GATED on the `scanOverlay` toggle
  (invariant (o)). Stamps `_arrival_ms = Date.now()` on every frame
  before emit (Mode-A M2). Mirrors `stores/lastPose.ts` structure.
- `src/components/ScanToggle.svelte` — on/off button + freshness badge
  ("최신" / "약간 지연됨" / "정지됨"). Computes the badge state from
  `Date.now() - scan._arrival_ms` (invariant (m)). 250 ms heartbeat
  tick so the badge animates even when no new SSE frame arrives.
- `tests/unit/scanOverlay.test.ts` (4 cases), `lastScan.test.ts`
  (8 cases), `poseCanvasScanLayer.test.ts` (10 cases — TB2 three
  non-trivial yaw cases + gating + TB1-equivalent positional integrity),
  `poseCanvasFreshness.test.ts` (2 cases — Mode-A M2 patch using
  `vi.useFakeTimers`), `scanToggle.test.ts` (6 cases).
- `tests/e2e/map.spec.ts` — 4 new playwright cases: toggle visible /
  defaults off, toggle on shows ≥ 5 dots via `data-scan-count`,
  toggle off clears, sessionStorage persists same-tab reload.
- `tests/e2e/_stub_server.py` — `_canned_scan()` (5-dot canned shape),
  `/api/last_scan` GET handler (anon), `/api/last_scan/stream` SSE
  handler (anon, mirrors `last_pose_stream` pattern).

#### Changed

- `src/components/PoseCanvas.svelte` — extended with optional
  `scan: LastScan | null` and `scanOverlayOn: boolean = false` props.
  `redraw()` adds a third draw layer between the map underlay and the
  trail loop, calling `projectScanToWorld(scan)` and rendering the
  resulting world-frame points as teal dots. `data-scan-count` and
  `data-scan-fresh` attributes are exposed on the wrap div for e2e
  selector reliability (Q-OQ-D9).
- `src/routes/Map.svelte` — mounts `<ScanToggle/>` above
  `<PoseCanvas/>`; subscribes to `lastScan` and threads `scan` +
  `scanOverlayOn` into `<PoseCanvas/>`. The lastScan subscription
  lifecycle is automatic — the store gates its own SSE on the
  scanOverlay flag.

#### Tests

- 47 → 67 vitest unit cases (+20: scanOverlay 4, lastScan 8,
  poseCanvasScanLayer 10, poseCanvasFreshness 2, scanToggle 6 —
  minus map_list_panel's 2 + auth's 11 + ... net delta is +20).
- 14 → 18 playwright e2e cases (+4 from `map.spec.ts`).
- `npm run lint` clean; `npm run build` produces ~22 kB gzipped.

#### Notes

- `LastScan` is canonically defined in `production/RPi5/src/core/
rt_types.hpp::struct LastScan`. The TS interface order matches the
  wire body emitted by `godo-webctl/src/godo_webctl/app.py::
_last_scan_view`, which iterates `LAST_SCAN_HEADER_FIELDS`. Drift
  detected by inspection per invariant (n).

### 2026-04-29 — Track E Mode-B folds (M4 unit test + lint scaffold)

#### Added

- `tests/unit/map_list_panel.test.ts` — 2 vitest cases mounting the
  real `MapListPanel` component into jsdom via Svelte 5's built-in
  `mount(...)` API (no `@testing-library/svelte` dependency added).
  Pins the Mode-A M4 hide-button contract: with
  `window.location.hostname` stubbed to `192.168.1.50`, the activate
  dialog's primary button is HIDDEN and the placeholder span carrying
  the `로컬 kiosk에서만 가능` tooltip renders in its slot. Companion
  case on `127.0.0.1` proves the primary button DOES render on
  loopback (anti-tautology check).
- `vitest.config.ts` — dedicated test config so the svelte plugin can
  run with `style: false` preprocessing under vitest (the production
  `vite.config.ts` + `svelte.config.js` use `vitePreprocess()` with
  default style preprocessing, which `preprocessCSS` cannot consume
  inside vitest's transform pipeline). Adds `resolve.conditions =
['browser']` so `mount(...)` resolves to svelte's client build under
  jsdom.

#### Changed

- `vite.config.ts` — removed the embedded `test:` block (now lives in
  `vitest.config.ts`); production build is unchanged.

#### Tests

- 37 vitest unit cases (was 35; +2 from `map_list_panel.test.ts`).
- 14 playwright e2e cases unchanged.
- `npm run lint` clean; `npm run build` produces ~22 kB gzipped.

### 2026-04-29 — PR-C: Track E (multi-map management)

#### Added

- `src/components/MapListPanel.svelte` — list every map under
  `${GODO_WEBCTL_MAPS_DIR}`, mark the active row, expose admin-gated
  `기본으로 지정` + `삭제` buttons. Reuses `<ConfirmDialog/>` with the
  new `secondaryAction` prop (per invariant (l)). Refresh on mount /
  post-activate / post-remove only — no polling (per Mode-A N6).
- `src/stores/maps.ts` — `Writable<MapEntry[]>` + `refresh()` /
  `activate(name)` / `remove(name)`. Mutations short-circuit
  client-side via `MAPS_NAME_REGEX_PATTERN_STR`.
- `src/lib/api.ts::apiDelete` — companion of `apiGet`/`apiPost`.
- `src/lib/protocol.ts` — 4 new error-code mirrors
  (`ERR_INVALID_MAP_NAME`, `ERR_MAP_NOT_FOUND`, `ERR_MAP_IS_ACTIVE`,
  `ERR_MAPS_DIR_MISSING`), `MAPS_NAME_REGEX_PATTERN_STR`, `MapEntry`
  - `MapListResponse` + `ActivateResponse` interfaces.
- `tests/unit/maps.test.ts` — 6 vitest cases covering the store
  contract + client-side validator.
- `tests/e2e/map.spec.ts` — 3 new playwright cases (list panel,
  activate flow, delete-disabled-on-active).
- `tests/e2e/_stub_server.py` — 5 new endpoints, in-memory map state
  shared across tests, loopback-flag flag (`?stub_loopback=…`) for
  the M4 non-loopback restart-button test path.

#### Changed

- `src/components/ConfirmDialog.svelte` — extended with optional
  `secondaryAction`, `showPrimary`, `primaryHiddenTooltip` props
  (invariant (l)). Cancel + primary still render as before; existing
  callers unaffected.
- `src/routes/Map.svelte` — mounts `<MapListPanel/>` above
  `<PoseCanvas/>`; threads a local `previewUrl` state so clicking a
  non-active row repaints the canvas with that map (back-compat
  default `/api/map/image` resolves through the active symlink).

#### Tests

- 35 vitest unit cases (was 29; +6 from `maps.test.ts`).
- 14 playwright e2e cases (was 11; +3 from `map.spec.ts`).
- `npm run lint` clean; `npm run build` produces ~22 kB gzipped.

### 2026-04-28 — PR-B: P0 frontend SPA

#### Added

- New top-level directory `godo-frontend/` (Vite 6 + Svelte 5 + TypeScript).
- `package.json` — pinned deps, scripts (`dev`/`build`/`preview`/
  `test:unit`/`test:e2e`/`lint`/`format`).
- `vite.config.ts` — Svelte plugin, dev proxy `/api → 127.0.0.1:8080`,
  path aliases.
- `src/lib/constants.ts` — 30+ SPA-internal Tier-1 constants.
- `src/lib/protocol.ts` — wire-shape mirror of `godo-webctl/protocol.py`.
- `src/lib/router.ts` — 30-line hash-router (per N9).
- `src/lib/api.ts` — `apiFetch/apiGet/apiPost/apiPatch` with auth header
  - 401 redirect + typed `ApiError`.
- `src/lib/sse.ts` — `SSEClient` with token-on-URL + Page Visibility
  handbrake + expired-token guard.
- `src/lib/auth.ts` — login/logout/refresh + decode-only `getClaims`.
- `src/lib/format.ts` — Korean-friendly formatters.
- `src/stores/{auth,lastPose,mode,theme}.ts`.
- `src/components/{TopBar,Sidebar,ModeChip,ServiceCard,PoseCanvas,
ConfirmDialog}.svelte`.
- `src/routes/{Dashboard,Map,Login,Local,NotFound}.svelte`.
- `src/styles/{tokens,global}.css` — Confluence-style: light default,
  sharp 2-4px corners, dense vertical spacing.
- `public/favicon.svg` — `:D` glyph (per FRONT_DESIGN §3 G-Q3).
- `tests/unit/{api,auth,sse}.test.ts` — 29 vitest cases.
- `tests/e2e/{login,dashboard,map,local}.spec.ts` — 11 playwright cases.
- `tests/e2e/_stub_server.py` — stdlib HTTP server, mirrors webctl wire.
- `tests/e2e/playwright.config.ts` — webServer auto-launches stub.
- `README.md`, `CODEBASE.md` (this file).

#### Tests

- 29 vitest unit cases, 11 playwright e2e cases. All green.
- `npm run lint` clean (eslint 9 + prettier 3).
- `npm run build` produces ~21 kB gzipped total (well under 200 kB target).

#### Deviations from plan (writer apply-notes)

- **Vite version**: plan called for "Vite 8.x". At writer time the
  highest Vite that has shipped is 6.x (5.4 LTS, 6.0 current). Using
  Vite 6.0 + `@sveltejs/vite-plugin-svelte@5.0` (only that combo
  installs without peer-dep warnings against Svelte 5.20).
- **Svelte version**: bumped to `~5.20` from the plan's `~5.0`. Svelte
  5.0.5 had a known bug where `<script lang="ts">` with `interface`
  declarations + `: T[]` type annotations in `const` declarations
  produced a `Not implemented type annotation EmptyStatement` esrap
  error. 5.20 fixes it.
- **`svelte-spa-router` replaced**: per N9. The package description still
  says "Router for SPAs using Svelte 4"; we wrote a 30-line hash-router.
- **`@types/node`** kept on Node 20 line (`~20.14.0`) since RPi 5 ships
  Node 20 from Debian Bookworm.
- **`SubmitEvent` type** in `Login.svelte` requires browser globals in
  ESLint config — added `globals.browser` via the `globals` package.

---

## 2026-04-29 — PR-DIAG (Track B-DIAG) — Diagnostics page

### Added

- `src/lib/protocol.ts` — wire shapes:
  - `interface JitterSnapshot` (mirrors C++ rt_types + format_ok_jitter).
  - `interface AmclIterationRate` (Mode-A M2 fold renamed scan_rate).
  - `interface Resources` (webctl-only — no C++ counterpart).
  - `interface DiagFrame` (multiplexed top-level keys: pose / jitter /
    amcl_rate / resources). `_arrival_ms` is a CLIENT-SIDE NON-WIRE
    field set on receipt by the diag store.
  - Field-order tuples `JITTER_FIELDS` / `AMCL_RATE_FIELDS` /
    `RESOURCES_FIELDS` / `DIAG_FRAME_FIELDS`.
  - `CMD_GET_JITTER` / `CMD_GET_AMCL_RATE` literals (anchor for the
    cross-language drift triple).
- `src/lib/constants.ts` — 9 new SPA-internal constants:
  `DIAG_SPARKLINE_DEPTH`, `DIAG_SPARKLINE_WIDTH_PX`,
  `DIAG_SPARKLINE_HEIGHT_PX`, `DIAG_FRESHNESS_MS`,
  `DIAG_POLL_FALLBACK_MS`, `LOGS_TAIL_MAX_N_MIRROR`,
  `LOGS_TAIL_DEFAULT_N`, `JITTER_PANEL_COLOR`,
  `AMCL_RATE_PANEL_COLOR`, `RESOURCES_PANEL_COLOR`.
- `src/stores/diag.ts` (NEW) — SSE-fed `Writable<DiagFrame | null>` +
  `Writable<DiagSparklineState>` (5 ring buffers of depth 60 frames =
  12 s @ 5 Hz lookback). Refcounted; SSE opens on first subscriber,
  closes on last. 1 Hz polling fallback when SSE drops. Stamps
  `_arrival_ms` on every received frame.
- `src/stores/journalTail.ts` (NEW) — manual-refresh state
  `Writable<JournalTailState>` + `refreshJournalTail(unit, n)`
  function. NOT polled; operator clicks Refresh.
- `src/components/DiagSparkline.svelte` (NEW, ~110 LOC) — canvas-based
  sparkline. Auto-scales y-axis to data range. No external chart lib —
  the FRONT_DESIGN §9 chart-library decision is still pending; this
  component lets PR-DIAG ship independently (OQ-DIAG-1).
- `src/components/JournalTail.svelte` (NEW, ~120 LOC) — allow-list
  dropdown + n-input + refresh button + monospace `<pre>` body.
  Hardcoded mirror of `services.ALLOWED_SERVICES`.
- `src/routes/Diagnostics.svelte` (NEW, ~210 LOC) — B-DIAG page. Four
  sub-panels in CSS-grid auto-fit (>=420 px columns):
  Pose / Jitter / AMCL rate + Resources / Journal tail. Stale-frame
  greying via `DIAG_FRESHNESS_MS` against
  `Date.now() - frame._arrival_ms`. Re-render tick once per second
  so the freshness gate evaluates without a new SSE frame.
- `src/routes.ts` — `/diag` → `Diagnostics` registered.
- `src/components/Sidebar.svelte` — added `/diag` nav row.
- `tests/e2e/_stub_server.py` — 5 new endpoint stubs:
  `/api/system/jitter`, `/api/system/amcl_rate`, `/api/system/resources`,
  `/api/diag/stream`, `/api/logs/tail`.

### Tests (new)

- `tests/unit/diag.test.ts` (8 cases — subscribe/unsub refcount,
  SSE open/close, no SSE without subscribers, \_arrival_ms stamping,
  sparkline ring depth, ring drops oldest at depth, polling fallback
  on SSE error, reset).
- `tests/unit/diagSparkline.test.ts` (5 cases — empty input, flat-line,
  polyline shape, label + chip render, "—" chip on empty input).
- `tests/unit/journalTail.test.ts` (4 cases — allow-list dropdown,
  loading-disables-button, empty-state, error-state).
- `tests/e2e/diagnostics.spec.ts` (5 cases — route renders, all four
  panels visible, jitter chip populates after login, allow-list
  dropdown count, journal Refresh fetches lines).

### Mode-A folds applied

- M2: `scan_rate` → `amcl_rate` everywhere — interface name, field
  tuple, DiagFrame key, store field.
- N4: SPA `_arrival_ms` pattern extended from Track D's LastScan to
  the multiplexed DiagFrame (one stamp per frame; sub-panels share it).
- OQ-DIAG-1: hand-rolled canvas sparkline (not uPlot / not SVG) —
  decoupled from FRONT_DESIGN §9 chart-library decision.
- OQ-DIAG-3: `JournalTail` allow-list hardcoded in SPA (not fetched
  from a new endpoint); drift detected by code review per invariant (q).
- OQ-DIAG-8: polling fallback at 1 Hz (not 5 Hz) — the choppier
  cadence is itself a useful operator signal that "SSE is broken".

### Total frontend test count

84 vitest cases (was 67 pre-PR-DIAG). 23 playwright e2e cases (was 18).
`npm run lint` clean; `npm run build` green; bundle 68.59 kB
(gzip 25.96 kB) — +1.1 kB raw vs pre-PR-DIAG.

## 2026-04-29 — Track B-CONFIG (PR-CONFIG-β): /config page

### Added

- `src/lib/protocol.ts` (extended) — `RELOAD_CLASS_HOT/_RESTART/_RECALIBRATE`
  literals + `ReloadClass` type, `VALID_RELOAD_CLASSES` set,
  `ConfigValueType` union, `ConfigSchemaRow`, `ConfigKV`,
  `ConfigGetResponse`, `ConfigPatchBody`, `ConfigSetResult`,
  `RestartPendingResponse`. Hand-mirrored from the Python NamedTuple
  in `godo-webctl/src/godo_webctl/config_schema.py`; drift catch by
  inspection per invariant (k).
- `src/stores/config.ts` — `Writable<ConfigState>` with
  `{schema, current, errors}`. `refresh()` parallel-fetches
  `/api/config/schema` + `/api/config`. `set(key, value)` does
  optimistic update + PATCH; on 400 rolls back the local value and
  populates `errors[key]` from the tracker's `detail` text. On
  success refetches `/api/config` for an authoritative read AND
  triggers `refreshRestartPending()` so the global banner updates
  immediately on `restart`/`recalibrate` edits.
- `src/stores/restartPending.ts` — `Writable<{pending, trackerOk}>`.
  `refresh()` joins `/api/system/restart_pending` with
  `/api/health.tracker`; the banner component differentiates the
  two failure modes (Mode-A S5 fold).
- `src/components/RestartPendingBanner.svelte` — top-of-app red
  banner with two failure-mode messages: "godo-tracker 재시작 필요"
  (tracker ok + flag set) vs "godo-tracker 시작 실패 — journalctl 확인"
  (tracker unreachable + flag set). Non-dismissable; the C++ boot
  clears the flag.
- `src/components/ConfigEditor.svelte` — main editor table. One row
  per schema entry; type-aware input (number / number / text per
  Int / Double / String). Submit on blur or Enter; Escape cancels.
  Reload-class glyph (✓ / ! / !!) with tooltip on the leftmost cell.
  Anonymous viewers see disabled inputs. On 400 the row's `error[key]`
  shows under the input.
- `src/routes/Config.svelte` — page composition: header + editor.
  The banner is global (App.svelte) so we DO NOT double-render here.
- `src/routes.ts` — register `/config` → `Config.svelte`.
- `src/components/Sidebar.svelte` — admin-only "Config" nav row.
- `src/App.svelte` — `RestartPendingBanner` mounted globally so it's
  visible on every page (DASH, MAP, DIAG, CONFIG, LOCAL).

### Tests

- New: `tests/unit/config.test.ts` (4 cases) — refresh + optimistic
  set + 400 rollback + network-error rollback.
- New: `tests/unit/restartPending.test.ts` (4 cases) — pending + ok,
  pending + tracker-down, flag-clear, dual-API-error fallback.
- New: `tests/unit/protocol.test.ts` (7 cases) — interface shape +
  reload-class string pins.
- New: `tests/e2e/config.spec.ts` (5 cases) — anonymous-disabled,
  admin nav-link + edit hot key, restart banner appears on
  `restart`-class edit, anon-no-nav, inline 400 error.
- Extended: `tests/e2e/_stub_server.py` — 4 stub schema rows (one per
  reload-class + type combo) + in-memory `RESTART_PENDING_FLAG`
  state; `do_PATCH` handler routes `/api/config`.

### Invariants

- (r) `/config` is admin-gated by Sidebar visibility ONLY (Track F:
  the page itself renders for anon, with disabled inputs). The PATCH
  is admin-gated server-side; SPA disablement is UX polish.
- (s) `RestartPendingBanner` is mounted at App.svelte ONLY (single
  source). Routes MUST NOT double-render the component — playwright
  strict mode catches this regression.
- (t) `config.set()` triggers `restartPending.refresh()` after PATCH
  success (fire-and-forget). The unit test pins this side-effect by
  verifying the head 4 calls match the synchronous PATCH+refetch
  sequence; restart-pending refresh happens after.
- (u) The TS interfaces in `lib/protocol.ts` are hand-mirrored from
  the Python NamedTuple at compile time. The runtime schema fetch
  populates the field DATA, but the field TYPES come from this file.
  Drift catch: `tests/unit/protocol.test.ts` constructor pins.

### (v) PR-SYSTEM — `/system` reuses the diag store; no second SSE

`routes/System.svelte` calls `subscribeDiag(fn)` (the same entry point
`Diagnostics.svelte` uses). The CPU-temperature sparkline reads from
`diagSparklines.cpu_temp_c`, not from a parallel ring. When both
`/diag` and `/system` are mounted (e.g. tabbed), `_getSubscriberCount
ForTests()` reports 2 but invariant (p) keeps the underlying SSE at 1.
`System.svelte` MUST capture the unsubscribe closure returned by
`subscribeDiag(fn)` and call it in `onDestroy` (mirror of
`Diagnostics.svelte:50-54`); failing to do so silently leaks a
subscriber and defeats invariant (p). A System-side resources-poll on
`/api/system/resources` is a code-review block.

Pinned by `tests/unit/system.test.ts::renders four panels, registers
one diag subscriber on mount, and unsubs on unmount` (subscriber count
== 1 after mount, == 0 after unmount).

### (x) Track D scale fix — resolution-aware scan overlay

`PoseCanvas.svelte`'s world↔canvas math reads from the
`$stores/mapMetadata` store (not a hardcoded `MAP_PIXELS_PER_METER`
constant). The store composes:

- `parseMapYaml(text)` over the body of `GET /api/maps/<name>/yaml`
  (resolution, origin, negate),
- the JSON shape of `GET /api/maps/<name>/dimensions` (width, height
  read from PGM header bytes — see godo-webctl invariant (y)).

The transform formula (Mode-A M2 fold pin — non-square width != height
exercised by `tests/unit/poseCanvasScale.test.ts §C-6`):

```
img_col = (wx - origin_x) / resolution
img_row = (height - 1) - (wy - origin_y) / resolution     // Y-flip
cx = canvas.width  / 2 + panX + (img_col - width  / 2) * zoom
cy = canvas.height / 2 + panY + (img_row - height / 2) * zoom
```

The single Y-flip lives in the `(height - 1) - ...` term. World +y
maps to a SMALLER canvas y (higher on screen), matching the ROS
map_server convention that `origin` is the world coord of the
bottom-left pixel.

The `MAP_PIXELS_PER_METER` constant was deleted as the structural
witness — no SPA code path can drift back to a hardcoded scale.

`mapImageUrl` prop changes trigger a reactive `$effect` that refetches
BOTH the bitmap and the metadata (Mode-A M3 fold). Pre-fix, only the
metadata refetched, so a `previewUrl` swap in MapListPanel painted
new coords on old pixels.

For non-zero `theta` in `origin[2]`, the canvas renders an in-canvas
warning banner ("이 맵은 회전 정보(theta)를 갖지만 SPA가 회전을
그리지 못합니다 — 좌표가 어긋날 수 있습니다") in the same DOM slot as
`mapLoadError` (Mode-A S6 fold) — a follow-up ticket will add the
sin/cos image rotation. The banner is operator-visible, not a silent
`console.warn`.

The scan overlay renders ONLY when `mapMetadata` is non-null AND the
freshness gate (Mode-A M2) passes. While metadata is loading, the
canvas falls back to a centred Cartesian frame so the pose dot still
renders (back-compat with the `/api/map/image` 404 path).

Pinned by:

- `tests/unit/mapYaml.test.ts` (6 cases),
- `tests/unit/mapMetadata.test.ts` (5 cases — including Mode-A T2
  cancellation race),
- `tests/unit/poseCanvasScale.test.ts` (8 cases — hand-computed
  literal integers per Mode-A T3, NOT formula-recomputed),
- `tests/unit/poseCanvasImageReload.test.ts` (Mode-A M3 reactive
  refetch — call count 1→2→3 on prop changes via a Svelte 5 host
  component),
- `tests/unit/poseCanvasFreshness.test.ts::Mode-A S5: scan stays
fresh when metadata resolves at t=400ms`,
- `tests/e2e/map.spec.ts::scan overlay survives wheel-zoom`.

### (w) PR-SYSTEM — sparkline window matches `DIAG_SPARKLINE_DEPTH × SSE_TICK_MS`

The System page sparkline label is computed from constants, not
hardcoded. Current value: `60 × 200 ms = 12000 ms = 12 s`.
FRONT_DESIGN §C describes B-SYSTEM as having a "5분 graph"; this is
a deliberate, documented deferral — bumping to 5 min requires growing
the central `DIAG_SPARKLINE_DEPTH` to 1500 (60 KB total store cost),
which is cheap but affects `/diag` simultaneously and so is left to
a deliberate follow-up. The System page MUST NOT carry its own
parallel deeper ring. Pinned by
`tests/unit/system.test.ts::sparkline label is derived from
DIAG_SPARKLINE_DEPTH × SSE_TICK_MS`.

## 2026-04-29 — PR-SYSTEM (Track B-SYSTEM): /system page

### Added

- `src/routes/System.svelte` (~210 LOC) — B-SYSTEM page. Four panels
  in CSS-grid auto-fit: CPU-temperature sparkline (panel-cpu-temp),
  Resources mem/disk numbers (panel-resources), Journal tail
  (panel-journal — reuses `<JournalTail/>`), Power buttons
  (panel-power — admin-gated reboot/shutdown wrapped by
  `<ConfirmDialog/>`). Subscribes to the existing `diag` store via
  `subscribeDiag` (invariant (v)); captures the unsub closure and
  calls it in `onDestroy` (invariant (v) + N3 fold). The anon-hint
  string is verbatim mirror of `routes/Local.svelte:169` ("제어 동작은
  로그인이 필요합니다.") per Mode-A M2 fold.
- `tests/unit/system.test.ts` (6 cases — see below).
- `tests/e2e/system.spec.ts` (3 cases — see below).

### Changed

- `src/routes.ts` — register `/system → System.svelte` (1 line +
  1 import).
- `src/components/Sidebar.svelte` — append `{ path: '/system', label:
'System' }` to the `items` array. The Sidebar generates
  `data-testid="nav-system"` automatically from the lowercased label.

### Tests

- New: `tests/unit/system.test.ts` (6 cases):
  - `renders four panels, registers one diag subscriber on mount, and
unsubs on unmount` — N3 fold pin (subscriber count round-trips
    0 → 1 → 0).
  - `sparkline label is derived from DIAG_SPARKLINE_DEPTH × SSE_TICK_MS`
    — T1 fold (no magic literal; survives a future depth bump).
  - `anon viewer sees disabled reboot + shutdown buttons and the
verbatim anon-hint` — M2 fold (string verbatim from
    `routes/Local.svelte:169`).
  - `admin viewer sees enabled reboot + shutdown buttons (no
anon-hint)` — anti-tautology partner of (3).
  - `reboot click opens the confirm dialog; cancel does NOT call
apiPost` — pivot-on-user-choice pin.
  - `reboot confirm-confirm calls apiPost('/api/system/reboot')
exactly once` — M3 fold (anti-typo pin: never `/shutdown`).
- New: `tests/e2e/system.spec.ts` (3 cases):
  - `system: happy path renders all four panels with SSE-fed
resources` — login first (SSEClient token gate), assert
    sparkline + mem/disk + journal-empty render. Sparkline selector
    scoped inside `panel-cpu-temp` per N1 fold.
  - `system: anon viewer sees disabled reboot button + verbatim hint`.
  - `system: sidebar nav link routes to /system`.
- `tests/e2e/_stub_server.py` — NO changes (N4 fold: the four
  endpoints `/api/system/resources`, `/api/logs/tail`,
  `/api/system/reboot`, `/api/system/shutdown` already exist at
  lines 825, 827, 872, 873 from PR-DIAG and PR-B).

### Mode-A folds applied

- M1: kept `DIAG_SPARKLINE_DEPTH = 60` (12 s window). FRONT_DESIGN §C
  "5분" → 12 s deviation called out explicitly; upgrade path is a
  deliberate one-line constant bump in a follow-up PR that updates
  both `/diag` and `/system` labels coherently.
- M2: anon-hint string is verbatim mirror of `routes/Local.svelte:169`.
- M3: confirm-success unit test added (test 6 — anti-typo pin).
- N1: e2e sparkline assertion scoped inside `panel-cpu-temp`.
- N3: `onDestroy` MUST call the `subscribeDiag` unsub closure;
  unit test 1 asserts subscriber count returns to 0 on unmount.
- N4: zero changes to `_stub_server.py` (pre-existing stubs verified).
- T1: sparkline label test reads constants, not literals.

### Bundle size

Pre-PR baseline: `dist/assets/index.js` 74.97 kB / gzip 28.07 kB.
After PR-SYSTEM: 79.27 kB / gzip 28.95 kB. Delta: +4.30 kB raw /
**+0.88 kB gzipped** — well under the 2 KB cap.

### Total frontend test count after PR-SYSTEM

`npm run test:unit` 99 → 105 cases. `npm run test:e2e` 30 → 33 cases
(31 of 33 pass; the pre-existing `config.spec.ts::config: anonymous
viewer does NOT see the Config nav row` failure from commit `265f5f6`
— where Config nav was made anon-visible without updating the test
— is unrelated to this PR and remains red).

### 2026-04-29 — Track B-BACKUP: map-backup history page (P2 Step 2)

#### Added

- `src/routes/Backup.svelte` — `/backup` page. Anon-readable table of
  every `<ts>` snapshot under `cfg.backup_dir`; admin-gated 복원
  button per row + `<ConfirmDialog/>` two-line body (per Mode-A N2
  fold). On success, banner shows `BACKUP_RESTORE_SUCCESS_TOAST`
  (mirrors Track E activate flow per Mode-A N1 fold). Mounts mirror
  `MapListPanel.svelte` structure verbatim.
- `src/lib/constants.ts` — 2 new SSOT constants per Mode-A TB1 fold:
  - `BACKUP_RESTORE_SUCCESS_TOAST` — the success toast wording;
    imported by both `Backup.svelte` AND `tests/unit/backup.test.ts`
    (no literal-string duplication).
  - `BACKUP_RESTORE_OVERWRITE_WARNING` — the dialog warning line.
- `src/lib/protocol.ts` — `BackupEntry`, `BackupListResponse`,
  `RestoreResponse` interfaces + 2 error-code mirrors
  (`ERR_BACKUP_NOT_FOUND`, `ERR_RESTORE_NAME_CONFLICT`). Mode-A M5
  fold: only 2 codes (`backup_dir_missing` was dropped — list returns
  `[]` uniformly).
- `tests/unit/backup.test.ts` — 6 vitest cases: list-newest-first,
  anon-disabled, admin-enabled, confirm flow POSTs once, success
  banner shows imported `BACKUP_RESTORE_SUCCESS_TOAST` (TB1 SSOT
  pin), 4xx surfaces inline `body.err`.
- `tests/e2e/backup.spec.ts` — 3 playwright cases: anon table renders
  with disabled restore, admin restore confirm flow + success toast,
  sidebar nav row routes to `/backup`.
- `tests/e2e/_stub_server.py` — list + restore handlers with in-memory
  `BACKUPS_STATE` (2 canonical-stamp entries seeded). Restore mirrors
  the backend wire shape: 422 on malformed `<ts>` + 404 on unknown +
  200 with `{ok, ts, restored}` on success.

#### Changed

- `src/routes.ts` — 1 new line: `'/backup': Backup`.
- `src/components/Sidebar.svelte` — 1 new row in `items`:
  `{ path: '/backup', label: 'Backup' }`.

#### Removed

- (none)

#### Tests

- 105 → 111 vitest unit cases (+6 from `backup.test.ts`).
- 31 → 34 playwright e2e cases (+3 from `backup.spec.ts`). One
  pre-existing failure (`config.spec.ts: anonymous viewer does NOT
see the Config nav row`) is unrelated — predated this PR (the
  earlier `265f5f6 fix(p4.5)` commit made the Config nav anon-visible
  but left this stale test on disk).
- `npm run lint` clean; `npm run build` produces 29.97 kB gzipped JS
  (was 28.95 kB; +1.02 kB delta — well under the +3 KB Mode-A N3
  budget).

#### No new invariants

Existing coverage suffices:

- (e) no magic numbers — `Backup.svelte` has none (every literal
  resolves to `lib/constants.ts`, a wire-side string in
  `lib/protocol.ts`, or a local iteration bound).
- (j) home-grown router — `/backup` is a static path.
- (l) `<ConfirmDialog/>` reused for restore confirm.

#### Mode-A folds applied

- M1: backend invariant added as `(t)`.
- M3: `FRONT_DESIGN.md:505` `viewer` → `anon` brought into alignment
  with Track F.
- M5: backend list endpoint returns 200 always; SPA expects empty
  `items` for both missing-dir and empty-dir cases.
- N1: success toast wording mirrors Track E (`MapListPanel.svelte:116`).
- N2: confirm dialog body is two-line (`'<ts>'` line + warning line).
- TB1: toast strings exported as constants in `lib/constants.ts`;
  `Backup.svelte` AND `tests/unit/backup.test.ts` import the same
  symbol.

## 2026-04-29 — Track B-SYSTEM PR-2: service observability

### Added

- `src/lib/serviceStatus.ts` (NEW) — `STATUS_TO_CHIP` map + `statusChipClass(s)`
  helper. Single source of the chip-class mapping; both `ServiceCard`
  and `ServiceStatusCard` import from here so visual drift is impossible.
- `src/components/ServiceStatusCard.svelte` (NEW) — read-only-or-admin
  twin of `ServiceCard.svelte`. Renders ActiveState chip + SubState +
  Korean uptime + PID + memory + a collapsible env-vars list. Shows
  Start/Stop/Restart buttons when `isAdmin` is true; POSTs to
  `/api/system/service/<name>/<action>`. 409 transition responses
  render `body.detail` in the lastError slot with auto-dismiss
  (`SERVICE_TRANSITION_TOAST_TTL_MS`). The dismiss timer is cleared
  in `onDestroy`.
- `src/components/EnvVarsList.svelte` (NEW) — collapsible
  `<details>` rendering KEY=VALUE lines. Redacted KEYs (value ===
  `REDACTED_PLACEHOLDER`) get a `(secret)` suffix label and a muted
  italic value class. Keys are sorted alphabetically for deterministic
  rendering.
- `src/stores/systemServices.ts` (NEW) — refcounted polling store.
  `subscribeSystemServices(fn)` opens a `setInterval` at
  `SYSTEM_SERVICES_POLL_MS = 1000` on first subscribe, clears it on
  last unsub. `_arrival_ms` stamped on every successful fetch.
  Last-good `services` array preserved on fetch error so the panel
  shows stale-but-visible (the stale banner triggers on the freshness
  gap).
- `src/lib/protocol.ts` — `SystemServiceEntry` interface,
  `SystemServicesResponse` interface, `SYSTEM_SERVICES_FIELDS` tuple,
  `apiSystemServiceAction(name, action)` path builder, error codes
  `ERR_SERVICE_STARTING` / `ERR_SERVICE_STOPPING`,
  `REDACTED_PLACEHOLDER = "<redacted>"` (mirror of webctl).
- `src/lib/constants.ts` — `SYSTEM_SERVICES_POLL_MS = 1000`,
  `SYSTEM_SERVICES_STALE_MS = 3000`, `SERVICE_TRANSITION_TOAST_TTL_MS
= 4000`.
- `src/lib/format.ts` — `formatUptimeKo(active_since_unix, now_unix)`
  Korean uptime ("1일 2시간"), `formatBytesBinaryShort(n)` base-1024
  short bytes ("51 MiB"). S4 fold rename (was `formatBytesShort`).

### Changed

- `src/components/ServiceCard.svelte` — uses `statusChipClass` from
  `$lib/serviceStatus`. New 409 `service_starting`/`service_stopping`
  branch in the action handler renders `body.detail` (Korean) with
  auto-dismiss after `SERVICE_TRANSITION_TOAST_TTL_MS`. The dismiss
  timer is cleared in `onDestroy`.
- `src/routes/System.svelte` — adds a 5th panel "GODO 서비스" rendering
  one `<ServiceStatusCard/>` per service from the `systemServices`
  store. Subscribes via `subscribeSystemServices` in `onMount`; calls
  the unsub closure in `onDestroy`. Stale-banner uses the existing
  `renderTick` heartbeat against `SYSTEM_SERVICES_STALE_MS`.

### Tests

- `tests/unit/format.test.ts` (NEW, 19 cases) — `formatRemaining` +
  `formatMeters` + `formatDegrees` (existing) + `formatUptimeKo`
  (10 cases including 0초/null/M분 S초/H시간 M분/D일 H시간 boundaries
  - clock-skew clamp) + `formatBytesBinaryShort` (5 cases including
    the S4 fold "51 MiB" corpus pin).
- `tests/unit/serviceStatus.test.ts` (NEW, 3 cases) — chip-class
  drift catch, mapped lookup, fallback for unknown words.
- `tests/unit/systemServices.test.ts` (NEW, 5 cases) —
  open/close on refcount, T4 fold (exactly 4 fetches in 3500 ms),
  T5 fold (timer count === 0 on unmount), `_arrival_ms` stamping,
  last-good preserved on error.
- `tests/unit/system.test.ts` — 5 new cases (services panel renders,
  env (secret) tag visible, admin sees action buttons, anon does not,
  clicking restart POSTs to `/api/system/service/<name>/restart`).
  Existing "renders four panels" updated to "renders five panels".
- `tests/e2e/system.spec.ts` — 3 new playwright cases (services panel
  shows 3 cards + env collapse reveals mixed redacted/non-redacted
  KEYs per T6 fold + admin clicks restart with stubbed 409 → Korean
  toast renders).
- `tests/e2e/_stub_server.py` — `_canned_system_services()` (3-row
  mixed-env corpus), `/api/system/services` GET route,
  `_route_system_service_action()` + POST route plumbing,
  `STUB_FLAGS["system_service_409"]` flag flipped via
  `?stub_svc_409=starting|stopping`.

### Total frontend test count

`npm run test:unit` 111 → 143 cases (+32). `npm run test:e2e`
unchanged at 36 passing (33 → 36 passing, +3 new system cases; the
1 pre-existing failure (`config.spec.ts: anonymous viewer does NOT
see the Config nav row`) is unrelated to this PR).

### Mode-A folds applied

- M1: backend invariants (v) + (w) + (x); SPA invariant (t).
- M2: `FRONT_DESIGN.md` §7.1 7-column row format.
- M3: Korean particle convention (Korean reading) — backend literal pin.
- M4: 7-field dataclass / interface mirror.
- M5: per-service degradation; no 503 wire path.
- N1: stale-banner threshold = 3 × poll cadence (3000 ms).
- N2: panel uses default `.panel` style; no sparkline.
- S4: `formatBytesBinaryShort` rename; base-1024 explicit.
- T4: vitest `vi.useFakeTimers()` asserts EXACTLY 4 fetches in 3500 ms.
- T5: `vi.getTimerCount() === 0` after last unsub.
- T6: playwright stub corpus mixes redacted + non-redacted KEYs.

## 2026-04-30 04:55 KST — PR-A SPA addendum: env_stale badge on Environment summary

### Added

- `EnvVarsList.svelte` accepts an optional `stale: boolean` prop. When
  true, the `<summary>` line renders a small amber "envfile newer —
  restart pending" badge alongside the `Environment (N)` count.
  Operator sees at a glance that they edited `/etc/godo/<svc>.env`
  after the service started, so the displayed env content reflects
  the staged file but the running process is still on the old values.
  CSS uses `--color-status-warn` + `--color-status-warn-bg` tokens
  (with hex fallbacks) so the badge respects theming.
- `protocol.ts::SYSTEM_SERVICES_FIELDS` extended to 8 entries with
  `env_stale`. `SystemServiceEntry` interface gains
  `env_stale: boolean`.

### Changed

- `ServiceStatusCard.svelte` — passes `service.env_stale` through
  to `<EnvVarsList>` as `stale`.
- `tests/unit/system.test.ts` + `tests/unit/systemServices.test.ts`
  + `tests/e2e/_stub_server.py` corpora seeded with `env_stale: False`
  on every `SystemServiceEntry` so the schema parity check stays green.

### Why a badge instead of a top-level "restart pending" pill

The staleness predicate is per-envfile; only the affected service
shows a marker. A top-level page-wide "restart pending" pill would
imply every service is affected. The badge sits next to the count it
qualifies, which keeps the signal local to its source.

### `ServiceStatusCard` lastError UX — auto-dismiss + active-state clear

The original Track B-SYSTEM PR-2 wired auto-dismiss only for the 409
transition gate (`service_starting` / `service_stopping`); every other
error code (`subprocess_failed`, `request_aborted`, network failures,
…) parked in `lastError` indefinitely until the next user click. PR-A
HIL surfaced the failure mode:

- `webctl` self-restart inevitably returns `subprocess_failed`: webctl
  invokes `systemctl restart godo-webctl`, the subprocess captures a
  non-zero exit (the new uvicorn replaces the old before the wait
  completes), and the SPA renders the error sticky-red even though
  the next poll shows the service back to `active(running)`.
- `tracker` restart sometimes outlasts the SPA fetch timeout (mlock +
  map load + AMCL kernel rebuild), surfacing as `request_aborted`
  even though the service comes up cleanly seconds later.

PR-A widens the auto-dismiss path to ALL error codes (5 s, the same
`SERVICE_TRANSITION_TOAST_TTL_MS` the 409 path used) and adds a
`$effect` that clears `lastError` immediately when a polling tick
reports the service `active` and the SPA is not mid-action. The
combination handles both the timer-fires-while-tab-hidden case and
the operator-clicks-and-walks-away case without ever showing a stale
error past the next successful poll.
