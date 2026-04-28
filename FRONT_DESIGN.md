# FRONT_DESIGN.md — GODO 프론트엔드 설계 SSOT

> **용도**: GODO 프로젝트의 두 프론트엔드(RPi5 로컬 execution window + 외부 web client) 설계
> 문서. 사용자/팀원이 읽는 SSOT, 한국어 + 영어 engineering term 혼용. 구현 세부는
> `godo-webctl/CODEBASE.md` 및 (예정) `godo-frontend/CODEBASE.md` 참조.
>
> **분리 이유**: 프론트엔드 영역이 커서 `SYSTEM_DESIGN.md`에서 분리. SYSTEM_DESIGN은
> RT pipeline / AMCL / FreeD / 매핑 같은 백엔드+제어 측면에 집중.
>
> 결정 일자: 2026-04-28 (사용자 결정 fold-in).

---

## 1. Scope

GODO에는 **두 종류의 프론트엔드**가 있다:

1. **Local execution window** — `news-pi01`(RPi 5) 자체에서 띄우는 데스크탑 앱. 운영자가
   현장에서 시스템 상태(트래커/웹서버/IRQ pin 등)를 직관적으로 확인하고, 문제가 생기면
   즉시 kill/start 할 수 있게 하는 **orchestrator + status panel** 역할.
2. **Web client** — 외부(스튜디오 PC, 스튜디오 모바일, 사무실 Mac 등)에서 브라우저로
   접속하는 운영 콘솔. 매핑 결과 확인, calibrate 트리거, config 편집, 진단 모니터링.

두 프론트는 **공통 Svelte+Vite 코드베이스**를 쓰지만 **로컬 모드에서만 보이는 추가 페이지(B-LOCAL)**가 있다.
공유 코드 = SSOT. 로컬 전용 페이지는 IP 화이트리스트(`127.0.0.1`/`::1`)로만 표시.

## 2. Stack — 결정됨 (`.claude/memory/frontend_stack_decision.md`)

| 영역 | 선택 |
|---|---|
| 빌드 | Vite (8.x) |
| 프레임워크 | Svelte |
| 라우팅 | SPA (svelte-spa-router) |
| 차트 | (P1에서 결정 — uPlot 후보) |
| Map 렌더 | Canvas 2D |
| Realtime transport | **SSE** + polling fallback (분석 §4.1) |
| Auth | JWT (localStorage), bcrypt password |
| i18n | 한국어 단일, engineering term은 영어 잔존 (CPU/Temp/AMCL 등) |
| 폰트 | 시스템 폰트 (Pretendard 우선, fallback Noto Sans KR) |
| **UI 스타일** | **Confluence/Atlassian 스타일** — 깔끔한 사각/약한 라운드(2-4px), 직선 레이아웃, 정보 밀도 위주. **둥근 약품통 같은 큰 라운드 버튼 / glassmorphism / soft-UI 트렌드 안 씀**. 테이블·카드·세로 spacing이 명확하고 운영용으로 한 화면에 정보가 많이 들어가는 디자인. |

**서빙 모델**: 단일 FastAPI 프로세스(`godo-webctl`)가 SPA bundle을 `/`에 mount + JSON API를
`/api/*`에 mount. Admin 콘솔 / 클라이언트 viewer를 별 프로세스로 분리하지 않음 — 한 프로세스가
auth role에 따라 가시성을 제어. (Multi-process 분리는 보안/부하 둘 다 이득 없음, complexity만 증가.)

## 3. 결정 로그 — 사용자 답변 fold-in

### A. 두 프론트 관계

**선택: A2 하이브리드 (orchestrator + 공통 Svelte 앱)**

User 의도: A1(단일 앱 + Chromium kiosk)은 "백엔드 프로세스가 실제로 떠있는지" 직관 확인이
어렵다. 따라서:

- **Local window가 orchestrator 역할** — godo-tracker / godo-webctl / godo-irq-pin 3개
  systemd 서비스의 status를 시각적으로 보여주고 start/stop 버튼 제공. Single-instance
  discipline은 systemd가 이미 보장 (Restart=on-failure, BindToMachineID 등).
- 부팅 시 자동 시작 (systemd `WantedBy=graphical.target`).
- **Kiosk 모드는 불필요** — 일반 데스크탑 윈도우로 띄움.
- 외부 client에서는 **B-LOCAL 페이지가 안 보임** (IP 체크).

이 구조의 장점: 로컬 운영자가 한 화면에서 (a) 시스템 동작 여부 (b) 모드 토글 같은 정상 운영
둘 다 처리. systemd가 실 process 관리 → orchestrator는 read+control UI일 뿐.

### B. 페이지 셋

```text
P0 (1차 구현):
  - B-DASH    Dashboard (모드 chip, quick actions, 최근 활동, last-pose 요약, health)
  - B-MAP     Map view (PGM + 실시간 pose marker + 1초 trail + (선택) particle cloud)
  - B-AUTH    Login / 토큰 카운터
  - B-LOCAL   ★ Local-only orchestrator 패널 (서비스 상태 + start/stop/restart + 로그 tail)

P1 (2차):
  - B-DIAG    Diagnostics (AMCL std/iter/converged + 시스템 metric + journald tail)
  - B-CONFIG  Config editor (~30 Tier-2 키, reload-class 표시 §D-Q2)

P2 (3차, Phase 4.5):
  - B-MAPEDIT Map editor (사람/크레인 마스킹 — §I-Q1 결정 후)
  - B-SYSTEM  System (CPU/mem/disk/journald + 셧다운/재부팅 버튼)
  - B-BACKUP  Backup history (list + restore)
```

User 답변 (B-Q1/Q2): 우선순위 OK, **낮은 layer부터 가자**. 페이지 셋 추가/삭제 없음.

### C. 페이지별 기능 세부

**B-DASH**: 모드 chip + Calibrate / Live toggle / Backup quick actions + 최근 5개 활동 + last-pose 한 줄 + health (CPU temp / 서비스 상태).

**B-MAP**:
- PGM 캔버스 (서버측 PNG 변환, 클라이언트는 `<img>` decode)
- AMCL pose marker: 점 + heading 화살표
- **1초 trail** (C-Q1 결정) — 1 Hz 갱신 가정 시 1점, 5 Hz 시 5점. trail 길어지면 직선처럼 보여 의미 적음.
- **Particle cloud (조건부 도입)** — C-Q2 분석:
  - particle cloud = AMCL의 N=500 particle (가설 pose 후보들). 맵과 별개.
  - 부하 분석: 500점 × (x, y, weight) × 4 bytes = 6 KB per frame. 1 Hz 도입 시 6 KB/s, 5 Hz 시 30 KB/s. **트래커 부하: AMCL은 이미 particle을 가지고 있으니 추가 비용은 직렬화 + 전송만 (~0.1 ms CPU/frame)**. → **부하 거의 없음, 도입 권장**.
  - 단 P0가 아닌 P1(B-DIAG)로 옮겨서 첫 구현 부하 줄일 것 추천. 결정: P1로 이동.
- pan/zoom (마우스 휠 + 드래그, 모바일 pinch H-Q4).
- 좌표 hover 표시.

**B-AUTH**: username + password 폼 + JWT 토큰 발급. 세션 timeout 6h (F-Q2). 상단 바 우측 "Logged in as <name> · 세션 5h 32m 후 만료" 표시. 페이지 클릭(라우트 이동) 시 토큰 갱신 (refresh token endpoint).

**B-LOCAL** (로컬 모드 전용):
- 3개 서비스 카드: godo-tracker / godo-webctl / godo-irq-pin
  - 상태 chip (active=green / failed=red / inactive=grey)
  - Start / Stop / Restart 버튼 (auth 필요)
  - 마지막 30줄 journald tail
- "Reboot Pi" / "Shutdown Pi" 버튼 (auth + confirm dialog)
- 시스템 health 요약 (CPU temp, RT jitter)

**B-DIAG**: AMCL get_last_pose 5 Hz SSE (E-Q1) — x/y/yaw + std + iter + converged + forced + sparkline. 시스템 metric (CPU temp, RT jitter from `godo_jitter` 또는 tracker exposed). journald tail (`/api/logs/tail?unit=godo-tracker&n=50`).

**B-CONFIG**: Tier-2 키 테이블, 각 행에 (key, current, edit, **reload-class 표시**). reload-class별 표시 (D-Q2):
- `hot` 클래스: 즉시 반영, 회색 ✓ 아이콘
- `restart` 클래스: 변경 후 "godo-tracker 재시작 필요" 메시지 + **붉은 ! 아이콘**
- `recalibrate` 클래스: "재시작 + 재캘리브레이션 필요" + 붉은 ‼ 아이콘
- 사용자가 적용 안 된 키를 한 눈에 식별 가능

**B-MAPEDIT** (P2, §I-Q1 분석 후 결정).

**B-SYSTEM**: CPU temp 5분 graph + 메모리 + 디스크 + journald + Reboot/Shutdown (auth + 원격 OK per C-Q3).

**B-BACKUP**: `/var/lib/godo/map-backups/<UTC ts>/` 리스트 + restore 버튼.

### D. Config 변경 적용 방식

**선택: D3 — Hybrid (RAM 즉시 + atomic file write 동기 + 실패 reject)**

Tracker 측 흐름:
```text
webctl PATCH /api/config {key: value}
  ↓
tracker UDS set_config {key, value}
  ↓
tracker validates value
  ↓
tracker atomic-writes /etc/godo/tracker.toml (tmpfile + rename)
  ↓
tracker updates RAM Config
  ↓
reload-class에 따라:
  - hot → 즉시 효과 (예: deadband_mm 변경)
  - restart → flag만 RAM에 set, 효과는 다음 systemctl restart에서
  - recalibrate → flag만 set, OneShot 재트리거 시 효과
  ↓
UDS reply ok / err (atomic-write 실패 시 reject, RAM도 안 바뀜)
```

**D-Q2 결정 fold-in**: 
- restart/recalibrate 클래스의 자동 재시작은 안 함 (방송 중 위험).
- B-CONFIG에서 변경된 restart/recalibrate 키 옆에 붉은 ! 아이콘 + "재시작 필요" 메시지.
- 운영자가 적당한 시점에 B-LOCAL의 "Restart godo-tracker" 버튼 클릭.

### E. 진단 데이터 표시

**선택: E3 — 둘 다 (브라우저 B-DIAG + CLI `pose_watch.py`)**

**갱신 주기 5 Hz, transport SSE** (E-Q1):

- 5 Hz는 사람 눈에 매끄럽게 보이는 최소치. 1 Hz는 끊겨 보이고, 10 Hz는 모바일 배터리 부담.
- get_last_pose 5 Hz × 180B reply ≈ 900 B/s = 7 Kbps per client. 부하 0.

### F. 인증 / 권한

**선택: F2 — multi-user (username + password)**

- 사용자 테이블 (`/var/lib/godo/auth/users.json` 또는 SQLite). 각 user: username + bcrypt(password) + role (`admin` / `viewer`).
- **viewer**: 모든 페이지 read-only. 수정 버튼 disabled.
- **admin**: 모든 작업 가능 (calibrate / config / mapedit / shutdown).
- **F-Q2**: 토큰 만료 6h. JWT payload에 `exp` 필드. 페이지 라우트 이동 시 백엔드 `/api/auth/refresh` 호출 → 새 토큰 발급. 상단 바에 "**Logged in as <name>** · 5h 32m 후 만료" 카운트다운.
- **F-Q3**: 모든 데이터 (config 값, 시스템 metric, journald) 다 노출. 보안 격리 안 함 — 운영팀 신뢰 모델.
- 비밀번호 변경: B-LOCAL에 "사용자 관리" 패널 (admin만), `/api/auth/users/<name>` PATCH로 password reset. RPi5 측 CLI helper도 제공:
  ```bash
  ssh news-pi01
  sudo -u ncenter godo-webctl-passwd  # interactive prompt
  sudo systemctl reload godo-webctl
  ```
- **첫 부팅 시 default admin 1개 (`ncenter` / `ncenter`)** — **첫 로그인 시 변경 강제 안 함**. 운영팀 내부 정책으로 비밀번호 관리. 외부 anonymous 접근 방지용 안전장치 수준 (악의적 외부인 차단 ≠ 강력한 보안).

### G. UI 디테일

| ID | 결정 |
|---|---|
| G-Q1 사이드바 | collapsible (>1024px 폭에서 펼침 default), 모바일 hamburger |
| G-Q2 브레드크럼 | 표시 (페이지 깊이 2단계) |
| G-Q3 favicon | `:D` SVG (32×32 + 192×192 PNG fallback for older browsers) |
| G-Q4 다크/라이트 | **라이트 default**, **회색 톤** (`#f5f5f7` background, `#2c2c30` text — 완전 백색 #fff 아님), 토글로 다크 모드, 사용자 선택 localStorage 저장 |
| G-Q5 i18n | 한국어 단일, engineering term은 영어 잔존 — 사전: `CPU`, `Temp`, `AMCL`, `LiDAR`, `OneShot`, `Live`, `Idle`, `RT`, `IRQ`, `jitter`, `std`, `iterations`, `converged`, `pose`, `latency`, `Hz`, `bps` 등 |
| G-Q6 폰트 | 시스템 폰트 우선 (`-apple-system, BlinkMacSystemFont, "Pretendard", "Noto Sans KR", sans-serif`) — 외부 web font 안 씀 (오프라인 + 빠름) |

### H. Map 뷰어

| ID | 결정 |
|---|---|
| H-Q1 렌더링 | Canvas 2D |
| H-Q2 transport | **SSE primary + polling fallback** (분석 §4.1 — WS는 우리 use case에 불필요). 크롬 메모리 절약 모드에서 탭 활성화 시 즉시 1회 polling 후 SSE 재연결. |
| H-Q3 trail | **1초** (5 Hz × 1s = 5점) — C-Q1 결정과 일치 |
| H-Q4 pinch-zoom | 지원 (모바일 우선; 라이브러리: hammerjs 또는 minimal pointer event 핸들러) |

### I. Map editor — §4.2 분석 후 결정

User 답변 (I-Q1): 구현 시간보다 **production 부하**와 **맵 변경 적용 속도/정확성**이 결정 기준.
아래 §4.2 분석에 따라 **I2 + hot reload**가 둘 다 우위. 채택.

---

## 4. Open question 분석

### 4.1 SSE vs WebSocket — H-Q2 추가 질의

User 질의 요지: "계속 페이지에서 접속하여 확인할 것인데 WS가 더 안정적일까?"

| 비교 | SSE | WebSocket |
|---|---|---|
| 방향 | Server → Client only | Bidirectional |
| 프로토콜 | HTTP + `text/event-stream` (HTTP/1.1 또는 H2) | TCP upgrade frame |
| 자동 재연결 | 브라우저 `EventSource`가 **기본 제공** (재시도 간격 noticeable) | 수동 구현 필요 (timer + reconnect logic) |
| FastAPI 측 | `StreamingResponse` 한 줄 | `websockets` 라이브러리 추가 |
| Proxy / 방화벽 | HTTP 그대로 통과 | 일부 corp proxy가 WS upgrade 차단 |
| 디버깅 | `curl` 가능, 로그가 텍스트 라인 | 바이너리 frame, 도구 필요 |
| 대역폭 오버헤드 | HTTP keep-alive (~50B header per session) | WS frame 6B/메시지 |
| Tab 비활성화 시 | 브라우저가 connection 닫으면 EventSource가 자동 재연결 | 닫히면 수동 재연결 작성 필요 |

**우리 use case 분석**:
- 데이터 흐름 = **server → client only** (pose, AMCL diagnostics, journald tail)
- client → server 통신은 모두 **POST endpoint** (calibrate trigger, config PATCH 등) — 별도 streaming 안 필요
- "안정성"의 정의가 "장시간 끊기지 않음"이라면 **SSE가 더 안정적** — 자동 재연결 built-in
- 부하 측면: 동등 (양쪽 다 1 keep-alive connection × N clients)

**결론: SSE 채택** (이미 §3.E/H에 반영). WS는 우리 use case에 over-engineered.

**Polling fallback 전략**:
- 페이지 load 시 1회 즉시 `/api/last_pose` GET → 화면 즉시 채움
- 그 다음 SSE `/api/last_pose/stream`로 전환, 5 Hz push 받음
- 탭 비활성화 (Page Visibility API hidden) → SSE 자동 끊김
- 탭 활성화 → 1회 polling으로 즉시 최신 표시 → SSE 재구독

### 4.2 I1 (live masking) vs I2 (post-edit) — Map editor

User 질의 요지: "production 부담", "맵 변경 적용 시간 + 정확성".

#### Production 부하 비교

| 항목 | I1 라이브 마스킹 | I2 사후 PGM 편집 |
|---|---|---|
| Cold path 매 scan 처리 | mask layer 룩업 360 ray × 10 Hz = 3,600 lookup/s | **0 (편집기는 webctl에서만 동작)** |
| Tracker 메모리 | mask grid 추가 (~100 KB) | 0 |
| Tracker C++ 변경 | cold_writer + UDS endpoint + mask 갱신 | 0 |
| Webctl 측 | 마스크 갱신 broker 역할 + 시간-가변 mask 직렬화 | numpy + Pillow로 PGM 편집 |
| RT jitter 영향 | mask lookup이 cache miss 유발 가능 (위험성 있음) | 0 |
| Phase 5 진입 조건 | C++ 신규 모듈 (테스트 + Mode-B + 검증 필요) | 작은 webctl 추가 |

→ **I2가 production 부담 0 (cold path 손 안 댐)**

#### 맵 변경 적용 시간 비교

| 시나리오 | I1 | I2 (no reload class) | I2 + hot reload class |
|---|---|---|---|
| 운영자가 마스크/edit 적용 → tracker가 인식까지 | 다음 scan (~100 ms) | tracker restart (~5s) | 즉시 (~10-100 ms) |

I2에 **hot reload class를 도입**하면 webctl이 PGM 저장 → tracker가 inotify로 감지 → AMCL의
occupancy_grid를 RAM에서 swap (atomic shared_ptr swap 같은 패턴) → 다음 scan부터 새 맵 사용.
여기서 시간은 inotify latency (~10ms) + 맵 로드 (occupancy_grid 수 MB라면 ~100ms) 정도.

→ **I2 + hot reload는 I1과 거의 동등한 적용 속도** (인지 가능한 차이 ≤ 100ms)

#### 정확성 비교

| 항목 | I1 | I2 |
|---|---|---|
| 운영자가 보고 결정 | "지금 사람이 거기 있을 거야" 예측 | **실제 매핑된 PGM**을 보고 식별 |
| 잘못 마스킹 시 영향 | 진짜 벽도 reject → AMCL 발산 위험 | backup에서 restore (안전한 fallback) |
| 반복 transient (매 방송 같은 위치 크레인) | 운영자가 매번 마스크 다시 그려야 함 (지속성 없음) | 한 번 편집 + restore 안 하면 영구 |
| transient의 "그림자" 처리 | 마스킹된 ray만 무시. 잔여 ghost 가능 | PGM 직접 편집 → 깨끗 |

→ **I2가 정확성에서도 우위** (실제 맵을 보고 작업 + safer failure mode)

#### 종합

| 차원 | I1 | I2 + hot reload |
|---|---|---|
| Production 부하 | 작지만 0은 아님 + RT jitter 위험 | **0** |
| 적용 속도 | ~100 ms | ~10-100 ms (동등) |
| 정확성 | 예측 의존, 잘못하면 발산 위험 | **실제 맵 기반, 안전** |
| 구현 비용 | 큼 (C++ + 시간-가변 mask + 검증) | 작음 (Python only) |
| 향후 확장 | 라이브 마스크는 I2 위에 쌓을 수 있음 | I2 먼저 → I1 필요 시 추가 |

**결론: I2 + hot map reload class 채택.** I-Q1 결정 fold-in.

세부 결정:
- **I-Q2 도구셋**: erase brush + polygon select + flood fill (3개 모두 numpy로 단순. 스튜디오에서 운영자가 "지금 그 영역만 지우고 싶어" 케이스 다양함)
- **I-Q3 brush 단위**: N×N (N은 운영자가 슬라이더로 조정 1~50 cell). 기본 5 (= 25 cm).
- **자동 backup**: 매 edit 직전에 `/var/lib/godo/map-backups/<UTC ts>_pre_edit/`에 원본 보관. /api/map/backup 인프라 재사용.
- **hot reload class** 도입: tracker가 `/etc/godo/maps/<map>.pgm` inotify watch + AMCL occupancy_grid 안전 교체. 별도 SYSTEM_DESIGN §5/§11 갱신 필요.

---

## 5. Top-level scaffold reorganization (2026-04-28 결정)

User 결정 fold-in: 새 frontend 도입을 계기로 top-level 디렉토리를 정리:

```text
변경 전 (현재)                    변경 후 (Phase 4.5 시작 시)
─────────────                    ──────────────────────────
/                                /
├─ production/RPi5/              ├─ production/RPi5/        (그대로 유지 — RT C++)
├─ godo-webctl/         ◄── 이동 ├─ godo-frontend/     ★신규 (Vite + Svelte)
├─ godo-mapping/        ◄── 이동 ├─ godo-backend/      (godo-webctl rename + 확장)
├─ XR_FreeD_to_UDP/              ├─ XR_FreeD_to_UDP/         (그대로 — 레거시 fallback)
├─ doc/                          ├─ doc/
├─ prototype/                    ├─ prototype/
│   └─ Python/                   │   ├─ Python/             (Phase 1-2 prototype)
│                                │   ├─ godo-webctl-min/    ★Phase 4-3 minimal 보관
│                                │   └─ godo-mapping/       ★Docker mapping 보관
├─ CLAUDE.md                     ├─ CLAUDE.md (§5 dir tree 갱신)
├─ SYSTEM_DESIGN.md              ├─ SYSTEM_DESIGN.md
├─ FRONT_DESIGN.md ★신규         ├─ FRONT_DESIGN.md
└─ PROGRESS.md                   └─ PROGRESS.md
```

이유:
- `godo-webctl`은 Phase 4-3 minimal scope (3 endpoint)으로 의도적으로 작게 만들었음. Phase 4.5+ 확장 시 새 `godo-backend`로 rename + 재구성하는 것이 SSOT 명확. 옛 minimal 버전은 prototype으로 보관 (참고용 + rollback 안전망).
- `godo-mapping`은 1년에 몇 번만 쓰는 one-off Docker tool. Top-level 차지하는 게 부담. `prototype/godo-mapping/`로 옮겨도 사용 시점은 동일하게 (`bash prototype/godo-mapping/scripts/run-mapping.sh ...`).
- **이동에 따른 영향**: systemd unit 파일의 `WorkingDirectory` / `ExecStart` 경로 갱신, README 모든 path 업데이트, CLAUDE.md §5 갱신, 기존 PR (Track B #7) 리베이스. → **별도 PR로 하나씩 분리**해서 진행 안전.

이동 시점: Phase 4.5 frontend planner 가동 직전. 일단 다음 세션에서 (a) Track B PR #7 머지 → (b) hotfix-c1-launch 머지 → (c) scaffold 정리 PR → (d) frontend planner 가동 순.

## 6. Architecture overview

### 6.1 프로세스 토폴로지 (A2 hybrid)

```text
┌─────────────────── RPi 5 (news-pi01) ───────────────────────┐
│                                                              │
│  systemd targets:                                            │
│  ┌─────────────────────────┐                                 │
│  │ godo-tracker.service    │ ← RT C++ 바이너리              │
│  │ godo-webctl.service     │ ← FastAPI + SPA serve          │
│  │ godo-irq-pin.service    │ ← oneshot at boot              │
│  │ godo-local-window.service│ ← Chromium window (autostart) │
│  └─────────────────────────┘                                 │
│                  │                                           │
│                  │ systemctl status / journalctl            │
│                  │ (read by webctl B-LOCAL via subprocess)  │
│                  ▼                                           │
│  ┌──────────────────────────────────────────────┐           │
│  │ godo-webctl FastAPI (port 8080)              │           │
│  │  ├ /              SPA bundle                  │           │
│  │  ├ /api/*         JSON endpoints              │           │
│  │  └ /api/*/stream  SSE streams                 │           │
│  └────────┬─────────────────────────────────────┘           │
│           │                                                  │
│  ┌────────▼─────────┐         ┌─────────────────────┐       │
│  │ Local Chromium   │         │ External browsers   │       │
│  │ window (X11/wayland)       │ (스튜디오 PC, 모바일,│       │
│  │ → http://127.0.0.1:8080    │   사무실 Mac)       │       │
│  │                  │         │ → http://news-pi01:8080     │
│  │ B-LOCAL 페이지 표시│         │ B-LOCAL 페이지 안 보임      │
│  │ (IP=127.0.0.1)   │         │ (IP=非 loopback)    │       │
│  └──────────────────┘         └─────────────────────┘       │
└──────────────────────────────────────────────────────────────┘
```

**핵심 원칙**:
- **systemd가 actual process manager**. 단일 인스턴스, auto-restart, boot 순서.
- **B-LOCAL은 webctl의 페이지일 뿐** — 별도 native 앱 아님. IP 화이트리스트로만 표시.
- **godo-local-window.service** = `chromium --app=http://127.0.0.1:8080 --window-size=1280,800` autostart.
- 외부 client는 B-LOCAL이 안 보이고, B-SYSTEM의 reboot 버튼만 (auth 필요).

### 6.2 라우팅 (SPA)

```text
/                         → B-DASH
/map                      → B-MAP
/diag                     → B-DIAG
/config                   → B-CONFIG
/map-edit                 → B-MAPEDIT  (P2)
/system                   → B-SYSTEM   (P2)
/backup                   → B-BACKUP   (P2)
/local                    → B-LOCAL    (loopback only)
/login                    → B-AUTH
```

### 6.3 API endpoint 추가 list (Phase별)

기존 (Phase 4-3 + Track B):
- `GET  /api/health`
- `POST /api/calibrate`
- `POST /api/map/backup`
- `GET  /api/last_pose` (Track B로 추가됨)

추가될 (Phase별):

**P0**:
- `POST /api/auth/login` — body {username, password} → {token, exp}
- `POST /api/auth/logout`
- `GET  /api/auth/me`
- `POST /api/auth/refresh`
- `POST /api/live` — Live mode toggle (set_mode {Live/Idle})
- `GET  /api/last_pose/stream` — SSE
- `GET  /api/map/image` — 현재 활성 맵의 PGM → PNG 변환
- `GET  /api/activity?n=5` — 최근 활동 로그 (webctl 자체 관리)
- `GET  /api/local/services` — systemctl status 3개 (loopback only)
- `POST /api/local/service/<name>/<action>` — start|stop|restart (loopback only, auth)
- `GET  /api/local/journal/<name>?n=30` — journald tail (loopback only)
- `POST /api/system/reboot` / `/shutdown` (auth admin)

**P1**:
- `GET  /api/diag/stream` — SSE for AMCL pose + system metrics 5 Hz
- `GET  /api/system/jitter` — godo_jitter snapshot
- `GET  /api/system/scan_rate` — /scan 토픽 rate (tracker exposed)
- `GET  /api/system/resources` — CPU temp / mem / disk
- `GET  /api/logs/tail?unit=<svc>&n=50` — journald tail
- `GET  /api/config` — Tier-2 키 전체
- `PATCH /api/config` — body {key: value, ...} → tracker UDS set_config
- `GET  /api/config/schema` — 키 메타 (description, reload_class, type, range)

**P2**:
- `POST /api/map/edit` — body {ops: [{type: erase|fill|flood, mask: [[x,y]...]}]}
- `GET  /api/map/backup/list`
- `POST /api/map/backup/<ts>/restore`
- `POST /api/auth/users` (admin) — body {username, password, role}
- `PATCH /api/auth/users/<name>/password` (admin or self)
- `DELETE /api/auth/users/<name>` (admin)

### 6.4 Tracker C++ 측 변경 (전체 영향 정리)

| 결정 | C++ 변경 |
|---|---|
| D3 (config PATCH) | UDS `set_config / get_config` 명령 + atomic TOML write + reload-class 처리 |
| C-DIAG jitter exposure | RT thread가 jitter 통계를 seqlock에 publish + UDS `get_jitter` |
| C-DIAG scan rate | LiDAR 모듈이 scan rate를 publish + UDS `get_scan_rate` |
| I2 + hot reload | inotify watch on /etc/godo/maps/*.pgm + occupancy_grid atomic swap |

→ Track B처럼 별도 hotfix/feature 단위로 PR 단위 분리 추천.

### 6.5 Realtime (SSE) 채널

| 채널 | URL | rate | payload |
|---|---|---|---|
| Last pose | `/api/last_pose/stream` | 5 Hz | `LastPose` JSON (Track B schema) |
| Diagnostics combined | `/api/diag/stream` | 5 Hz | `{pose, jitter, scan_rate, resources}` |
| Service status | `/api/local/services/stream` | 1 Hz | systemctl status 3개 |
| Journal tail | `/api/logs/<svc>/stream` | event-driven | journalctl --follow output |

### 6.6 Auth flow

```text
1. 사용자가 /login 페이지에서 username + password 입력
2. POST /api/auth/login
   ├ 서버: bcrypt 검증 + JWT 발급 (exp = now + 6h, role 포함)
   └ localStorage.setItem('godo_token', jwt)
3. 모든 SPA fetch에 Authorization: Bearer <token> 헤더
4. 서버 미들웨어가 JWT 검증 + role 체크
5. 페이지 라우트 변경 시 → POST /api/auth/refresh → 새 토큰
6. 6h 미사용 시 만료 → 자동 logout
```

JWT secret: `/var/lib/godo/auth/jwt_secret` (서버 첫 부팅 시 random 생성, 600 perms).

---

## 7. API endpoint table (LIVING — 백엔드 ↔ 프론트 SSOT)

> **이 표는 living document**. 새 endpoint 추가 / 변경 / 폐기 시마다 같은 PR에서 갱신.
> 프론트와 백엔드는 이 표에 합의된 wire schema만 사용한다. CODEBASE.md
> (`godo-backend/CODEBASE.md` + `godo-frontend/CODEBASE.md`) 의 invariant로 핀.

### 7.1 HTTP endpoints

| Method · Path | 권한 | Phase | 페이지 | Request body | Reply body | 설명 |
|---|---|---|---|---|---|---|
| `GET /api/health` | public | 4-3 (있음) | DASH | — | `{ok: bool, mode: str}` | UDS get_mode round-trip |
| `POST /api/calibrate` | admin | 4-3 (있음) | DASH | — | `{ok: bool}` | UDS set_mode {OneShot} |
| `POST /api/map/backup` | admin | 4-3 (있음) | BACKUP | — | `{ts: str, path: str}` | atomic 두-단계 copy |
| `GET /api/last_pose` | viewer | TrackB (있음) | MAP, DIAG | — | `LastPose` (Track B schema) | get_last_pose UDS round-trip |
| `POST /api/auth/login` | public | P0 (있음) | AUTH | `{username, password}` | `{token, exp, role}` | bcrypt 검증 + JWT 발급 |
| `POST /api/auth/logout` | viewer | P0 (있음) | AUTH | — | `{ok}` | localStorage 만료 (서버는 stateless JWT) |
| `GET /api/auth/me` | viewer | P0 (있음) | (전 페이지 상단) | — | `{username, role, exp}` | 토큰 검증 + 만료까지 남은 초 |
| `POST /api/auth/refresh` | viewer | P0 (있음) | (auto) | — | `{token, exp}` | 라우트 이동 시 토큰 갱신 |
| `POST /api/live` | admin | P0 (있음) | DASH | `{enable: bool}` | `{ok, mode}` | UDS set_mode {Live\|Idle} |
| `GET /api/map/image` | viewer | P0 (있음) | MAP | (query: `?map=<name>`) | PNG image binary | PGM → PNG (Pillow), 캐시 5분 |
| `GET /api/activity?n=<int>` | viewer | P0 (있음) | DASH | — | `[{ts, type, detail}]` | webctl 자체 활동 로그 |
| `GET /api/local/services` | admin (loopback) | P0 (있음) | LOCAL | — | `[{name, active, since}]` | systemctl status 3개 |
| `POST /api/local/service/<name>/<action>` | admin (loopback) | P0 (있음) | LOCAL | — | `{ok, status}` | start \| stop \| restart |
| `GET /api/local/journal/<name>?n=<int>` | admin (loopback) | P0 (있음) | LOCAL | — | `[str]` | journalctl tail |
| `POST /api/system/reboot` | admin | P0 (있음) | LOCAL, SYSTEM | — | `{ok}` | shutdown -r now (5s grace) |
| `POST /api/system/shutdown` | admin | P0 (있음) | LOCAL, SYSTEM | — | `{ok}` | shutdown -h now (5s grace) |
| `GET /api/system/jitter` | viewer | P1 | DIAG, SYSTEM | — | `{p50, p99, max}` | RT thread jitter snapshot |
| `GET /api/system/scan_rate` | viewer | P1 | DIAG | — | `{hz, last_scan_ts}` | LiDAR scan rate |
| `GET /api/system/resources` | viewer | P1 | SYSTEM | — | `{cpu_temp, mem_used, disk_used}` | psutil + /sys read |
| `GET /api/logs/tail?unit=<svc>&n=<int>` | viewer | P1 | DIAG, SYSTEM | — | `[str]` | journalctl --no-pager |
| `GET /api/config` | viewer | P1 | CONFIG | — | `{key: value, ...}` | Tier-2 키 전체 |
| `GET /api/config/schema` | viewer | P1 | CONFIG | — | `{key: {type, range, reload_class, desc}}` | UI 메타 |
| `PATCH /api/config` | admin | P1 | CONFIG | `{key: value, ...}` | `{applied: [str], pending_restart: [str]}` | UDS set_config + atomic TOML |
| `POST /api/map/edit` | admin | P2 | MAPEDIT | `{ops: [{type, mask}]}` | `{ok, backup_ts}` | numpy/Pillow + auto-backup |
| `GET /api/map/backup/list` | viewer | P2 | BACKUP | — | `[{ts, files, size}]` | /var/lib/godo/map-backups/ scan |
| `POST /api/map/backup/<ts>/restore` | admin | P2 | BACKUP | — | `{ok}` | cp + reload |
| `POST /api/auth/users` | admin | P2 | LOCAL | `{username, password, role}` | `{ok}` | 사용자 추가 |
| `PATCH /api/auth/users/<name>/password` | admin or self | P2 | LOCAL | `{old, new}` | `{ok}` | password reset |
| `DELETE /api/auth/users/<name>` | admin | P2 | LOCAL | — | `{ok}` | 사용자 삭제 |

### 7.2 SSE streams

| Path | 권한 | Phase | 페이지 | Frame | 설명 |
|---|---|---|---|---|---|
| `GET /api/last_pose/stream` | viewer | P0 (있음) | MAP | `LastPose` JSON @ 5 Hz | get_last_pose 폴링 → push |
| `GET /api/diag/stream` | viewer | P1 | DIAG | `{pose, jitter, scan_rate, resources}` @ 5 Hz | 통합 진단 |
| `GET /api/local/services/stream` | admin (loopback) | P0 (있음) | LOCAL | `[{name, active, since}]` @ 1 Hz | 서비스 상태 변화 |
| `GET /api/logs/<svc>/stream` | viewer | P1 | DIAG, SYSTEM | journalctl --follow line-by-line | journald event-driven |

### 7.3 UDS commands (tracker side)

| Command | Phase | webctl endpoint | C++ 변경 |
|---|---|---|---|
| `ping` | 4-3 (있음) | `/api/health` (sub) | — |
| `set_mode {Idle\|OneShot\|Live}` | 4-3 (있음) | `/api/calibrate`, `/api/live` | — |
| `get_mode` | 4-3 (있음) | `/api/health`, polled | — |
| `get_last_pose` | TrackB (있음) | `/api/last_pose`, SSE | — |
| `get_config` | P1 신규 | `/api/config` | tracker exposes Config struct as JSON |
| `set_config {key, value}` | P1 신규 | `PATCH /api/config` | atomic TOML write + RAM update + reload-class flag |
| `get_jitter` | P1 신규 | `/api/system/jitter` | RT thread publishes jitter via seqlock |
| `get_scan_rate` | P1 신규 | `/api/system/scan_rate` | LiDAR module publishes rate |

### 7.4 UI / 프론트 측 wire SSOT

- 모든 wire string (CMD_*, FIELD names, status enum)은 `godo-frontend/src/lib/protocol.ts`에 단일 mirror
- `godo-backend`는 `godo-webctl/protocol.py` pattern 그대로 유지 (LAST_POSE_FIELDS 같은 패턴 확장)
- 두 측의 string drift는 cross-test로 catch (현재 godo-webctl `test_protocol.py` pattern 확장)

### 7.5 갱신 규칙

- 새 endpoint 추가 시: 본 §7 표 + `godo-backend/src/...` 코드 + `godo-frontend/src/lib/api.ts` 동시 수정 (한 PR 안에서)
- Schema 변경 시: 동일 PR + cross-test 갱신
- 폐기 시: 행에 ~~취소선~~ + "deprecated 2026-XX-XX, replaced by ..." 메모 추가, 한 release 후 삭제
- 버전 번호 안 둠 (단일 in-house product) — 대신 git history가 권위 있음

## 8. Phase plan

### Phase 1 — Frontend planner kick-off (다음 세션 시작)

- code-planner agent에게 §3 결정 + §4 분석 + §5 architecture 전달
- planner output: P0 페이지 셋의 task breakdown, file-level change spec
- expected scaffold:
  ```text
  /godo-frontend/                  ← 신규 top-level dir, Vite project
    ├─ vite.config.ts
    ├─ package.json
    ├─ src/
    │   ├─ main.ts
    │   ├─ App.svelte
    │   ├─ routes/                 ← Dashboard, Map, Auth, Local
    │   ├─ lib/
    │   │   ├─ api.ts              ← fetch wrapper + JWT
    │   │   ├─ sse.ts              ← EventSource manager
    │   │   └─ auth.ts
    │   └─ stores/                 ← svelte stores (token, mode, etc.)
    ├─ public/                     ← favicon (:D SVG)
    └─ CODEBASE.md
  
  /godo-webctl/                    ← 기존, 추가 endpoints
    └─ src/godo_webctl/
        ├─ auth.py                 ← 신규, JWT + bcrypt
        ├─ sse.py                  ← 신규, StreamingResponse helpers
        └─ app.py                  ← P0 endpoints 추가
  ```

### Phase 2 — P0 구현 (Track C-1)

- B-DASH / B-MAP / B-AUTH / B-LOCAL
- webctl P0 endpoints
- godo-local-window.service systemd unit
- 1차 머지

### Phase 3 — P1 구현 (Track C-2)

- B-DIAG / B-CONFIG
- tracker D3 (set_config) + jitter/scan_rate exposure
- C++ Mode-B 통과 후 머지

### Phase 4 — P2 구현 (Track C-3, Phase 4.5)

- B-MAPEDIT / B-SYSTEM / B-BACKUP
- /api/map/edit (numpy + Pillow)
- I2 hot reload class (tracker inotify + occupancy_grid swap)

### Phase 5 — Field integration

- 실 스튜디오 운영 + UE 연동 + 8h 안정성 테스트

### Phase 4.5+ Track D — Live LIDAR overlay (P0.5, 2026-04-28 user 요청)

운영자가 B-MAP 페이지에서 **현재 RPLIDAR가 보고 있는 raw scan**을 맵 underlay 위 오버레이로 토글해서 볼 수 있게. localization / FreeD UDP 송출은 **0 영향** (seqlock read-only path).

**모티베이션**: still 맵 + 추정 pose만 보면 "내 위치 추정이 맞나?"를 운영자가 검증할 수 없음. 라이다가 실제로 보는 점들을 같은 좌표계에 겹쳐 그리면 — pose가 맞으면 scan 점들이 벽선 위에 정확히 떨어지고, 어긋나면 시각적으로 즉시 보임. AMCL 수렴 디버깅에도 직접 사용.

**스코프**:
- tracker C++: scan thread는 이미 AMCL용 seqlock 운영 중 → `get_last_scan` UDS handler 추가 (seqlock read 1회, μ초 단위, hot-path 0 영향). `protocol.md`에 `get_last_scan` reply schema 추가 (`{ranges:[float], intensities:[float], angle_min, angle_increment, scan_time, header_seq}`).
- webctl: `uds_client.get_last_scan` + `/api/last_scan` 단발 GET + `/api/last_scan/stream` SSE @ 5 Hz. 한 frame ~3-6 KB JSON, 5 Hz → ~30 KB/s SSE 부하 (감수 가능). FRONT_DESIGN §7.1/§7.2 갱신.
- SPA: `PoseCanvas`에 scan layer 추가 (3rd layer: pgm 맵 / scan 점들 / pose marker), `Map.svelte`에 toggle 버튼 ("LIDAR scan 보기"), polar→직교 변환은 pose의 yaw 사용해 world frame으로.

**UX 결정**: 새 LIDAR 탭을 만들지 않고 **B-MAP 오버레이 토글**로. 같은 데이터를 두 화면에 보이는 SSOT 위반 회피 + "내 추정 위치에서 라이다가 뭘 보고 있나?" 라는 운영자의 mental model에 직접 매핑.

**예상 작업량**: tracker C++ ~80 LOC + webctl ~150 LOC + SPA ~120 LOC + tests, ≈1 PR-사이즈 작업. PR-B (P0 SPA) 머지 후 Track D로 단독 진행.

---

## 9. 보류 / 추후 결정

- **차트 라이브러리**: P1 진입 시 결정 (uPlot 후보, lightweight + Canvas 기반).
- **B-MAP particle cloud**: P0가 아닌 P1로 옮김 (B-DIAG와 함께). 부하는 0이지만 첫 구현 부하 줄임.
- **I1 추가 도입 여부**: I2가 실 운영에서 부족하다고 판명되면 (예: 매 방송마다 같은 transient 반복) Phase 5 이후에 평가.
- **mobile native app**: 추후 결정. PWA로 충분할 수도.

---

## 10. 참고 링크

- [SYSTEM_DESIGN.md](./SYSTEM_DESIGN.md) — RT pipeline / AMCL / FreeD / 매핑 (백엔드)
- [PROGRESS.md](./PROGRESS.md) — 일별 진행 상태
- [doc/history.md](./doc/history.md) — Phase-level decision history (한국어)
- [godo-webctl/CODEBASE.md](./godo-webctl/CODEBASE.md) — webctl module map
- (예정) `godo-frontend/CODEBASE.md` — frontend module map (Phase 1 진입 시 생성)
- `.claude/memory/frontend_stack_decision.md` — Vite + Svelte 결정 기록
