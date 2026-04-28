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
| `components/PoseCanvas.svelte`   | Canvas with pan/zoom/trail; world↔canvas conversion via `MAP_PIXELS_PER_METER`.                                                                                            |
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
