# godo-frontend

GODO 운영자 SPA. Vite + Svelte 5 + TypeScript. 빌드 결과물(`dist/`)은
`godo-webctl`이 동일 origin에서 정적으로 서빙한다.

## Quickstart (개발 머신, Mac/Linux)

```bash
cd godo-frontend
npm install              # 첫 1회 (~30s)
npm run dev              # vite dev server: http://127.0.0.1:5173
                         # /api/* → http://127.0.0.1:8080 (godo-webctl) 프록시
```

godo-webctl이 별도로 떠 있어야 `/api/*`가 응답한다. 로컬 개발 시:

```bash
# 별 터미널에서
cd godo-webctl
GODO_WEBCTL_HOST=127.0.0.1 GODO_WEBCTL_PORT=8080 uv run python -m godo_webctl
```

## 빌드 + 배포

```bash
npm run build            # → godo-frontend/dist/
```

`dist/`는 SPA 번들 + 정적 자산(SVG favicon 등). `godo-webctl`이 환경변수
`GODO_WEBCTL_SPA_DIST`로 이 경로를 가리키면 자동으로 `/`에 마운트된다.

```bash
# news-pi01 (RPi 5)
sudo systemctl edit godo-webctl
# [Service]
# Environment=GODO_WEBCTL_SPA_DIST=/home/ncenter/projects/GODO/godo-frontend/dist
sudo systemctl restart godo-webctl
```

환경변수가 없으면 godo-webctl은 기존 `static/index.html` (Phase 4-3 vanilla
status page)을 서빙한다 — rollback 안전망.

## Tests

| 종류             | 명령                | 환경                     |
| ---------------- | ------------------- | ------------------------ |
| Unit (vitest)    | `npm run test:unit` | jsdom + 모든 OS          |
| E2E (playwright) | `npm run test:e2e`  | dev 머신 (Mac/Linux x86) |
| Lint             | `npm run lint`      | 모든 OS                  |
| Format           | `npm run format`    | 모든 OS                  |

E2E는 dev 머신 전용 (N8 punt). aarch64 Chromium 바이너리 분배 부담을 피하려고
RPi 5 CI는 vitest unit + 백엔드 pytest만 돌린다. 첫 e2e 실행 시 chromium이
약 170 MB 다운로드된다 (`~/.cache/ms-playwright/`).

## Default seed credentials

godo-webctl이 `users.json`을 lazily seed한다:

```
username: ncenter
password: ncenter
role:     admin
```

첫 로그인 강제 변경은 안 한다 (FRONT_DESIGN.md §3.F). 운영팀 정책으로 관리.
변경하려면:

```bash
ssh news-pi01
sudo /home/ncenter/projects/GODO/godo-webctl/scripts/godo-webctl-passwd
```

## Local kiosk window (`godo-local-window.service`)

부팅 시 RPi 5 GUI에 Chromium을 자동 실행해서 `http://127.0.0.1:8080/#/local`을
띄운다. Profile dir는 tmpfs (`/run/user/$UID/godo-chromium-profile`) — 재부팅마다
초기화되어 디스크에 누적되지 않는다 (N3). `--kiosk` 플래그로 navigation lock을
건다 (N4). 자세한 설치는 `godo-webctl/systemd/install.md` 참조.

## Architecture summary

```text
┌──────────────────┐  ┌──────────────────┐
│ External browser │  │ Local Chromium   │
│ (스튜디오 PC,    │  │ (news-pi01 GUI)  │
│  사무실 Mac)     │  │                  │
└────────┬─────────┘  └─────────┬────────┘
         │ HTTP                  │ HTTP (loopback)
         ▼                       ▼
   ┌──────────────────────────────────┐
   │ godo-webctl (FastAPI, port 8080) │
   │  ├ /             SPA dist/       │
   │  └ /api/*        JSON + SSE      │
   └──────────────────────────────────┘
```

## Bundle size

빌드 후 gzipped 크기 (참고치, 200 KB 이하 유지):

```
dist/index.html             0.32 kB
dist/assets/index-*.css     2.11 kB
dist/assets/index-*.js     18.36 kB
─────────────────────────  ─────────
total                       ~21 kB gzipped
```

## 더 읽기

- `CODEBASE.md` — 모듈 맵, invariants, 디자인 토큰, build flow.
- `../FRONT_DESIGN.md` — 전체 SPA 설계 SSOT (페이지/컴포넌트/SSE/auth).
- `../godo-webctl/CODEBASE.md` — 백엔드 측 invariants (auth seam, SSE, loopback gate).
