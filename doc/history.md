# GODO 작업 히스토리

> **용도**: 사람이 읽는 날짜별 작업 기록. 기술적 상세는 [PROGRESS.md](../PROGRESS.md) (영문) / [SYSTEM_DESIGN.md](../SYSTEM_DESIGN.md) 참조.
>
> **규칙**:
> - 최신 항목이 위로 오도록 역순 정렬.
> - 세션당 1개 블록. 같은 날 여러 세션이면 `(새벽/오전/오후/저녁/심야)` 등으로 구분.
> - 기술 용어는 영어 원문 유지 (예: seqlock, hot path, SCHED_FIFO — 번역 금지).
> - 구현 세부는 PROGRESS.md 영문 항목과 교차 참조. 여기는 "왜 / 무엇을 결정했는가" 중심.

---

## 2026-04-28 (저녁·심야)

### 한 줄 요약

**Track E (Multi-map management) 파이프라인 완주 — PR-B 콜드 머지 + PR-13 딜리버리. 5 endpoints + atomic symlink swap + admin-gated SPA panel. 30 files / 256 pytest / 37 vitest / 14 playwright. Phase 4.5 P0 운영 surface 사실상 완성, LAN 검증만 남김.**

> 기술적 상세는 [PROGRESS.md 2026-04-28 evening 블록](../PROGRESS.md#session-log) 참조.

### 왜 이렇게 결정했는가

#### PR-B 콜드 머지 — LAN 라운드트립 비용 vs. 검증 marginal

오전 NEXT_SESSION.md 계획은 "LAN PC에서 Chrome HTTPS-First 인터셉트 검증 후 머지" 였음. 실제로는 사용자가 Tailscale + `192.168.3.22:8080` 양쪽에서 dev box 직접 동작 확인 → SPA UX는 이미 end-to-end 검증, HTTPS-First는 클라이언트 한정 동작이라 추가 LAN 라운드트립의 marginal value 없다고 판단 → cold merge.

이 판단은 PR-13에는 적용 안 함. Track E 는 새 storage architecture (`/var/lib/godo/maps/` + symlink) + 새 admin-gated UI (3-button ConfirmDialog + non-loopback 버튼 hide) + systemd `ReadWritePaths` 추가가 끼어 있어 LAN 환경에서의 새 검증이 의미 있음 → "내일 아침 LAN 체크 후 머지" 로 보류.

#### Track E 파이프라인 — 4-라운드 풀가동의 이유

Track E 의 위협 모델이 충분히 다양했음 — path traversal, TOCTOU on symlink swap, concurrent activate, cache stale, legacy back-compat. 5개 다른 종류의 실수 표면이라 양쪽 reviewer 라운드 모두 가치 있었음.

planner → Mode-A reviewer → Parent fold → writer → Mode-B reviewer → Parent fold 6단계 모두 거쳤고, Mode-A 가 5 majors + 6 nits + 3 test-bias 잡아냄:
- M1: `realpath` containment 가 모든 public function 진입에서 (defence-in-depth), `assert` 금지 (production `-O` 에서 사라짐)
- M2: two-syscall create+replace 만 (`tempfile.mkstemp` 는 잠재 EXDEV 리스크)
- M3: `set_active` 시작 시 매번 `.active.*.tmp` sweep (이전 크래시 잔재 청소)
- M4: `window.location.hostname` 비-loopback → restart 버튼 hide (UI 가 거짓말하는 상황 방지)
- M5: systemd `ReadWritePaths` 문서화

전부 writer 호출 전 plan 에 인라인 fold.

Mode-B 는 1 major + 5 nits + 2 test-bias. Major 만 fold 하고 4 nits 는 의도적 deferral:
1. `cfg.map_path is None` dead-code branch — Settings 타입(`Path`, `Path | None` 아님) 때문에 unreachable, follow-up cleanup
2. e2e stub server 의 Track F 정렬 누락 (`/api/last_pose` etc. 가 여전히 `_claims_or_401`) — pre-PR-B drift, Track E 회귀 아님
3. e2e shared global stub state — `workers=1` 한정 OK, 향후 병렬화 시 조치
4. concurrent-flock 테스트 40 ms wall-clock 여유 — `threading.Event` 패턴이 더 견고

4개 다 fold 하면 PR-13 사이즈 + 추가 검증 round 가 붙는데 실제 위험은 M4 하나뿐. 진짜 위험만 fold, 나머지는 Track D 또는 별도 follow-up 에 묶기로 결정.

#### Atomic symlink swap — 핵심 디자인 디시플린

`os.symlink` + `os.replace` 두 syscall 로 끝. `tempfile.mkstemp` 안 씀 (생성 위치가 다른 디렉토리면 EXDEV 로 rename 실패; 같은 디렉토리 내 `secrets.token_hex(8)` 임시 이름만). `flock(LOCK_EX)` 로 activate 직렬화 + 시작 시 stale `.active.*.tmp` sweep. POSIX `rename(2)` atomic 이라 reader (image endpoint) 가 도중 상태를 못 봄.

cache invalidation 도 같이: `map_image.py` 의 cache key 를 `(path, mtime_ns)` → `(realpath, target_mtime_ns)` 로 변경. symlink swap 시 realpath 가 바뀌니 같은 mtime 도 stale 안 됨.

#### M4 단위 테스트 — Svelte 5 `mount()` 직접 호출

Mode-B M4 는 "M4 의 hide 동작이 e2e 만 검증되고 단위 테스트 없음" 지적. `@testing-library/svelte` 의존성 추가 대신 Svelte 5 빌트인 `mount(...)` 으로 jsdom 에 실제 컴포넌트를 마운팅하는 vitest 추가. `vitest.config.ts` 별도로 두고 (`style: false` 전처리 + `resolve.conditions = ['browser']`) production svelte.config.js 와 충돌 회피. 비-loopback 에서 hide / loopback `127.0.0.1` 에서 render 양쪽 다 검증 (anti-tautology).

### 운영 현황 (news-pi01, 2026-04-28 심야 종료 시점)

- main = `1f5f3c4` — PR-A + PR-B + Track F + FRONT_DESIGN §8 모두 머지 완료
- PR-13 push 완료, 다음 날 LAN 체크 후 머지 예정
- webctl `0.0.0.0:8080` 동작 중, studio_v2 맵 서빙 (PR-13 머지 후 `cfg.maps_dir` 설정 + `godo-maps-migrate` 1회 실행 필요)
- godo-tracker 미구동 (의도된 상태 — banner 정상 표시)
- 다음 세션: PR-13 LAN 체크 + 머지 → Track D (Live LIDAR overlay) 풀 파이프라인. `get_last_scan` UDS handler 가 Track B 이후 첫 cross-language touch.

---

## 2026-04-28

### 오늘의 한 줄 요약

**Phase 4.5 P0 프론트엔드 — 백엔드 PR-A 머지 + SPA PR-B 오픈 + Track F (anon read 모델) fold + Track D/E 명세 확정. Vite+Svelte 5 SPA가 21KB로 떨어졌고 운영자가 LAN 브라우저로 라이브 데이터 모니터링 + 로그인 후 제어가 됨.**

> 기술적 상세는 [PROGRESS.md 2026-04-28 블록](../PROGRESS.md#session-log) 참조.

### 왜 이렇게 결정했는가

#### "anonymous read / login-gated mutation" — 운영 현실에서 나온 요구

당초 PR-A의 auth 모델은 "모든 endpoint require_user, mutation은 require_admin" 이었음. 사용자가 PR-B SPA 라이브 검증 중 확인: "로그인 안 해도 모니터링은 돼야 한다 — 운영자가 자리에서 잠깐 보러 올 때마다 로그인하는 건 비현실적." 이게 Track F의 모티브.

세 가지 선택지:
- (a) 로그인 후에만 모든 화면 보임 — 채택 안 함 (위 모티브)
- (b) 일부만 anon, 핵심은 require_user — 절반의 절차, 절반의 보호 (양쪽 모두 손해)
- (c) **모든 read endpoint anon, mutation은 admin** ★ — read는 LAN 보안 (loopback 게이트는 그대로), mutation은 1차 방어선 (LAN-exposed credential-stuffing 방지엔 bcrypt(12) ≈ 300ms). 채택.

세 가지 게이트가 이제 직교한다:
1. **Loopback 게이트** (`/api/local/*`) — 키오스크 본체에서만 보임, 인증 무관
2. **Auth 게이트** (mutation) — admin 토큰 필요, anon은 401
3. **Role 게이트** — 미래 viewer 사용자 분리 (P2)

backend invariant (n)에 명시 + parametrized test로 모든 mutation endpoint anon 401 검증.

#### Track E를 별도 PR로 분리 — 스코프 디시플린

사용자가 "맵 여러 버전 관리 + 활성 맵 지정 + 삭제 GUI" 요청. 가능한 두 가지 모양:
- (a) PR-B에 fold — UI는 같은 Map 페이지라 자연스러움
- (b) **별도 Track E PR** ★ — 채택

이유: PR-B는 이미 Mode-B 통과한 P0 SPA. Track E는 ~650 LOC + 새 storage architecture (`/var/lib/godo/maps/` + `active.pgm` symlink) + 새 systemd `ReadWritePaths` + 매핑 Docker 컨테이너 volume mount 변경 + tracker 재시작 흐름. 다른 PR 단위. 머지 사이즈 깨끗.

planner agent가 ~620줄 plan 생성 (path-traversal 위협 모델, atomic symlink swap 프로토콜, concurrent-activate flock, cache invalidation 키 변경, back-compat 마이그레이션 모두 포함). Mode-A reviewer 재실행 중 — 다음 세션에 결과 받음.

#### Track D (Live LIDAR overlay) — Phase 2 디버그 도구로서의 정체

사용자 요청: B-MAP 페이지에서 "라이다가 지금 보고 있는 점들"을 오버레이 토글로. 새 LIDAR 탭 안 만들고 같은 화면에 통합 결정 — "내 위치 추정이 맞나?"라는 운영자의 mental model에 직접 매핑됨. Pose가 맞으면 scan 점들이 벽선에 정확히 떨어지고, 어긋나면 시각적으로 즉시 보임. **AMCL 수렴 디버깅 도구로서의 가치가 더 큼** — 오늘 사용자가 v2 맵에서 직선만 보이는 걸 직접 확인한 것과 직결.

tracker C++ 변경은 `get_last_scan` UDS handler 추가뿐 (seqlock read 1회, μs-level, hot-path 0 영향). 별도 Track D로 진행, Track E 머지 후.

#### AMCL 수렴 실패 — 시각으로 확인한 root cause

오전 매핑 직후의 AMCL 첫 실 테스트 결과 (xy_std 5.9 m, 10 000 particles × 200 iter 비수렴) 가 오늘 SPA로 시각화된 맵을 통해 확인됨. studio_v2 (107s walk + loop closure) 도 직선 위주, fine feature 부족. T자형 + 거의 직사각형 벽 → likelihood surface 가 평탄 → 거울대칭 위치들이 모두 동등 후보. yaw 가 매번 wildly 다른 값으로 수렴한 이유.

Phase 2 lever (NEXT_SESSION.md 그대로):
- ICP-based initial pose seed (가장 효과 클 듯)
- Retro-reflector landmarks at step corners
- 더 천천히 + 여러 번 walk + slam_toolbox loop_closure_threshold 낮추기
- LiDAR 20cm offset → pivot center 재정렬 (필수)

알고리즘 작업은 LiDAR 재정렬 후 본격 진입. 오늘은 운영 surface에 집중.

### 운영 현황 (news-pi01, 2026-04-28 종료 시점)

- webctl `0.0.0.0:8080` 구동 중, studio_v2 맵 서빙
- `~/.local/state/godo/auth/` 에 JWT secret + users.json (sudo 불필요한 dev 셋업)
- godo-tracker 미구동 (의도된 상태) — banner 정상 표시
- PR-B (#12) push 완료, 사용자 LAN 검증 후 머지 예정
- Track E plan + Mode-A reviewer 백그라운드 진행 중

---

## 2026-04-27

### 오늘의 한 줄 요약

**Track A (Docker SLAM 툴체인) 머지 → Track B (AMCL 진단 readout + repeatability harness + pose_watch) 완성. 진단 surface "always-on, on-demand" 원칙 정식 채택.**

> 기술적 상세는 [PROGRESS.md 2026-04-27 두 블록](../PROGRESS.md#session-log) 참조.

---

### 이른 — Track A 잔여 작업 머지 + news-pi01 Docker bring-up

- 어제(2026-04-26) 닫은 cold-start brief(`NEXT_SESSION.md`)에 따라 Track A부터 진행. `track-a-mapping` 브랜치에 plan v1 → Mode-A REWORK(15 finding) → plan v2 → Mode-A v2 → writer → Mode-B REWORK(1 Major + 4 Minor) 풀 파이프라인 완주.
- **Major 버그 (Mode-B가 잡음)**: `entrypoint.sh`의 `MAP_SAVER_CMD` 기본값에서 `-f ${MAP_OUT_BASE}` 플래그가 빠져있었음. production에서 `nav2_map_server map_saver_cli`가 자기 default(`./map`)로 폴백 → 컨테이너 내부 `/godo-mapping/map.{pgm,yaml}`로 silent write → 운영자는 bind-mounted `maps/`가 비어있는 채로 `Ctrl+C` 깨끗하게 떨어진 줄 알고 종료. 세 군데(`entrypoint.sh:40-42` 코멘트, `CODEBASE.md:181-184` 문서)는 의도된 동작을 정확히 적어놨는데 실제 default 한 줄만 어긋나 있었음. Parent가 narrow one-shot fix로 직접 수정 (3 Edit, 약 10줄).
- **PR #6 self-merge (rebase)** → `news-pi01`에서 Docker 설치(`apt install docker.io` + `usermod -aG docker ncenter`) → 재부팅 후 `docker run hello-world`(arm64v8) 정상 → `verify-no-hw.sh --full` 통과(292초, ~800 MB 풀, 18개 테스트 + docker build + image `--help` smoke). Track A 정식 closeout.
- **subagent reviewer API 안정성 이슈** 두 번 연속 발생 — Mode-A v2 confirmation pass가 `API Error: Unexpected end of JSON input`으로 33분 → 3.6시간 매달리다 실패. Parent가 직접 v2 verification matrix 작성(15/15 ✅) 후 진행. 이후 Track B의 Mode-A v2도 같은 패턴(파이프라인 단축)으로 생략 결정 — Track A precedent으로 굳어짐.

### 낮 — Track B planner + pose-readback 결정

- NEXT_SESSION에 적힌 Track B 가정("standalone Python script")이 깨짐. Tracker의 `get_mode` 응답이 `mode`만 돌려주고 AMCL pose는 cold writer 내부 seqlock에만 publish됨 → 외부에서 읽을 surface가 아예 없음. 4가지 transport 옵션 평가:
  1. **UDS 명령 신설** (`get_last_pose`) — C++ ~80 LOC additive. 기존 `set_mode/get_mode/ping` dispatch 패턴, seqlock 재사용.
  2. webctl `/api/last_pose` HTTP 라우트 — webctl이 어차피 트래커에서 pose 읽어와야 하므로 C++ 변경은 동일하게 필요 + HTTP surface 추가됨.
  3. tracker가 `/run/godo/last_pose.json` 주기 write — 매 publish마다 fsync 비용 + 새 persistence surface.
  4. `get_mode` reply 확장 — schema-drift 위험. user의 "no schema drift" 원칙과 정확히 반대.
- **Option 1 채택** — 가장 작은 blast radius. user의 "the latter (option 2) is cleaner" 직감은 "C++ 안 건드리는 길이 있다"는 가정에 기반했지만, 분석해보니 어떤 옵션도 C++ 변경을 피할 수 없음.
- 사용자 핵심 질문: **"우리 진단 툴은 production에선 비활성화하고 dev/문제 발생 시만 켜는 설계인가?"** — 답: 아니다. **"관측 surface는 always-on, 소비는 on-demand"** 패턴 정식 채택. `get_last_pose` UDS endpoint는 production에서도 항상 노출 (cost ~30 ns/AMCL iter; 호출 없으면 0). 무엇이 on/off 되는가는 *consumer* 선택 — frontend 진단 패널, CLI watch 도구, repeatability harness 모두 얇은 consumer. Prometheus / OpenTelemetry 류 패턴. 방송 중 "지금 발산이었나?" 진단할 surface가 그 순간 이미 존재해야 함 — compile-flag로 gate하면 쓸모 없음.

### 낮 → 오후 — Mode-A REWORK + plan v2

- Reviewer Mode-A v1 결과 6 must-fix:
  1. `LastPose` 크기 산수 틀림 (40 B 주장 → 실제 56 B with `published_mono_ns`).
  2. Cross-language SSOT가 Python에 3 replica → 1 mirror로 정리 필요.
  3. "godo_webctl import 금지" + `pytest.importorskip` 모순 — runtime 금지 vs test-time SSOT 핀을 분리해야 함.
  4. `--shots 1`이면 `statistics.stdev`가 `StatisticsError` raise → exit 1 갈림(legitimate happy path를 bad-CLI exit으로 오염).
  5. `last_pose_seq` ordering 핀이 5개 `g_amcl_mode = Idle` store site 중 어느 것에 적용되는지 모호 — only L302 (OneShot success path)으로 명확화.
  6. cold_writer 시그니처 변경이 기존 테스트 10개 사이트로 cascade — file-level change spec에 빠짐.
- 6개 모두 v2에 fold + Should/Nit 14개도 한꺼번에 fold. Track A precedent 따라 Mode-A v2 재검토 생략, 곧바로 Writer 진행.

### 오후 → 저녁 — Option B vs C + writer

- 사용자 질문: "진단 툴을 frontend에서 켜고 끄거나 cmd 창 띄워서 받을 수 있는가?" — yes, Track B가 첫 진단 endpoint 자체를 만들고 frontend 패널/CLI watch 도구는 위에 올라가는 얇은 consumer. 그 중 cmd watch 도구를 Track B 범위에 포함할지가 결정 포인트:
  - **Option B**: `repeatability.py`에 `--watch` 모드 추가 (한 스크립트, 두 모드).
  - **Option C**: 별도 `pose_watch.py` 스크립트 + 공통 `_uds_bridge.py` 헬퍼 모듈.
- **Option C 채택** — Single Responsibility (측정 ≠ 모니터링; 시간 압박과 운영 audience가 다름). 1년 후 Grafana exporter나 healthcheck script 추가할 때도 같은 분리 패턴이 자연스러움. 새 invariant (g) "godo-mapping/scripts/ 의 모든 UDS 클라이언트는 `from _uds_bridge import UdsBridge` MUST — copy-paste 금지" 등록.
- **Writer 4개 deviation** 보고 → Mode-B가 모두 accept:
  - 테스트 call site 카운트 drift (plan 7 → actual 4): 모든 surviving 사이트에 `Seqlock<LastPose>` thread.
  - `verify-no-hw.sh --quick` pytest 2-tier resolver (system pytest → uv fallback): F20 spec의 superset, Docker dep 도입 안 함.
  - 추가 테스트 케이스 (`test_busy_tracker_returns_3`): 양성 coverage 추가.
  - **(critical) `run_live_iteration`도 `last_pose_seq` publish**: F5 race는 OneShot→Idle 전환에만 존재. Live는 매 AMCL iter마다 Idle로 가지 않으므로 race 없음. `forced=1/0` 플래그로 OneShot vs Live 구분. **이게 없으면 `pose_watch.py`가 Live mode 중 stale pose에 freeze** — 이 도구 만든 이유 자체가 사라짐.
- Mode-B는 **APPROVE-WITH-NITS** (3 cosmetic — CODEBASE.md trailing blank line × 3, README drift caveat 한 문장, 출력 예시 timestamp 동일 cosmetic). Parent가 직접 fold(narrow fix → 3 Edit + 1 sed truncate).

### 저녁 → 심야 — 문서 정비 + closeout

- **PROGRESS.md** Track A + Track B 두 블록 추가 (영문 세부, "current state + next-up" 체크리스트).
- **doc/history.md** 이 파일에 한국어 + 결정 narrative 추가 (현재 작성 중).
- **SYSTEM_DESIGN.md** §7 (UDS 프로토콜)에 새 `get_last_pose` 명령 + reply 스키마 + "진단 surface always-on" 원칙 추가 예정.
- 사용자가 history.md 위치(`doc/history.md`) + 한국어/영어 혼용 컨벤션을 명시 → memory에 reference entry 등록 (`reference_history_md.md`). 이 파일이 존재한다는 사실 자체가 future session에서 PROGRESS.md만 보고 끝내는 실수를 막아줌.
- branch `track-b-repeatability`에 3개 commit (feat / docs(memory) / docs closeout). Track A precedent 따라 PR로 push → user self-merge → news-pi01에서 `--quick` 재검증.

### 오늘 푸시된 커밋 요약

(closeout commit + push 후 추가 예정)

### 다음 세션 시작 시 확인할 것

1. **LiDAR 재연결** (월요일 예정) → `repeatability.py --shots 100`으로 Phase 1 재현성 측정 + first hardware audit (occupancy_grid.cpp:148-154 YAML key 비교).
2. **Track A live mapping run** — `bash run-mapping.sh control_room_v1` → `maps/control_room_v1.{pgm,yaml}` 생성 → `/etc/godo/maps/`로 복사 → 트래커 시작 시 `occupancy_grid::load_map` 통과 확인.
3. **Frontend planning** (NEXT_SESSION 원래 Track C) — 남겨둔 5 bucket 논의: 페이지 셋, 실시간 데이터 source, 메커니즘(polling/SSE), 맵 렌더링(Canvas 2D), 디자인(다크모드).
4. **Track A `verify-no-hw.sh --full`이 발견한 `nav2_map_server` Jazzy YAML 키 목록**과 `occupancy_grid.cpp:148-154` 비교는 실제 매핑 1회 후가 의미 있음.
5. systemd install on news-pi01 (`production/RPi5/systemd/install.sh`) — 이미 어제 끝났음, 재확인만.

---

## 2026-04-24

### 오늘의 한 줄 요약

**RPi5에서 RPLIDAR C1 실기 구동 확인 → Phase 4-1 (RT hot path) 전체 파이프라인 완주 → 오늘 총 15개 커밋 `origin/main` 푸시.**

---

### 이른 오전 — RPi5 하드웨어 구동 검증

- 전날 환경 설정·깃 설정 완료한 `news-pi01`(RPi5, Debian 13 Trixie aarch64)에서 첫 실물 테스트.
- 2D LiDAR가 바닥 기울기에 민감한 점 논의 — **지도 제작 시 5 m 이동하면 0.01°의 미세 tilt로도 원래 물체가 사라진 것처럼 보이는 현상**이 발생 가능함을 지적. 정확도 우선 원칙에 따라 Phase 1에 (8) 바닥 tilt 측정, (9) 레벨링 마운트 설계 두 항목을 추가하기로 결정. 문서는 Plan A로 완성(`doc/hardware/floor_tilt_survey_TS5.md` + `leveling_mount.md`), 현장 방문은 추후로 보류.
- RPi5로 옮긴 김에 C++ SDK 직접 구동까지 확인하기로. `godo_smoke` 바이너리를 ultra_simple과 동시 실행 가능한 상태로 먼저 착수 (Plan B).

### 오전 — Phase 3 완주 + C1 first light

- Plan B 구현체(`/production/RPi5/`) 완성. `godo_smoke` 5프레임 캡처 시 `grabScanDataHq` 첫 호출이 모터 spin-up 도중 timeout으로 실패하는 현상 관찰. `ultra_simple`은 조용히 재시도로 넘어가는 패턴이었음.
- **일시적 timeout을 최대 5회 연속까지 허용하도록 수정** (`lidar_source_rplidar.cpp`, 약 14줄 변경). 커밋 `49fdc2b`.
- 30프레임 / 500프레임 테스트 통과. 3회 반복 재현성 확인:
  - **godo_smoke steady-state: 10.02 / 10.03 / 10.52 Hz** (spec 10 Hz 맞음)
  - ultra_simple: 4,768 / 4,848 / 4,770 SPS (스펙 5,000 SPS의 ~96 %)
  - godo_smoke: 5,108 / 5,109 / 5,108 SPS
- 결론: **우리 post-processing(validate + CSV write + session log) 오버헤드는 사실상 0**. 30프레임 테스트에서 평균 7 Hz처럼 보였던 것은 startup transient(1.5s / 3s 총 시간)가 통계를 왜곡한 것뿐.
- 시각화: `rate_compare.png` + `xy_scan.png` × 3 iter. xy scan에서 studio 벽면 윤곽이 세 번 모두 거의 완벽히 중첩되는 것을 육안으로 확인 (약 mm 수준 재현성).

### 낮 — SYSTEM_DESIGN.md 대폭 개정

- 아키텍처 핵심 결정 3개를 도식화 + 문서화:
  1. **Hot/Cold path 분리**: 59.94 Hz FreeD→UDP 경로는 hard deadline (~16.7 ms), LiDAR+AMCL 경로는 최대 1 s 지연 허용. 두 경로 사이는 `std::atomic<Offset>`(초기 안) → **`Seqlock<T>` 템플릿**(v3 수정안)으로 교차.
  2. **Offset smoother 선형 램프 (방식 A)**: AMCL 결과가 도착하면 `live_offset`이 `target_offset`으로 `T_ramp` 동안 선형 보간. UE 화면에 눈에 보이는 step change 방지. EMA / rate-limit 대비 전환 시간 예측 가능성으로 선택.
  3. **Yaw wrap을 두 지점에 명시**: smoother 내부 `lerp_angle`(최단 호), FreeD pan 재인코딩 `wrap_signed24`(signed 24-bit lsb fold). 레거시 `XR_FreeD_to_UDP`는 pan 산술을 안 했기 때문에 wrap 함수가 없었다는 점을 문서화.
- Trigger UX (Q6) 해결: 물리 버튼(GPIO) + HTTP POST(godo-webctl). 두 경로 모두 같은 `std::atomic<bool> calibrate_requested`로 수렴.
- FastAPI vs 커스텀 C++ 웹: **FastAPI 별도 프로세스 강력 권장**. RT 바이너리에 HTTP 스택을 넣으면 alloc/락 간섭 위험이 제로가 아니기 때문.

### 낮 → 오후 — Mode-A 리뷰 → 설계 재정비

- code-reviewer Mode-A 첫 리뷰 결과 **REWORK 판정**. 블로커 5개:
  1. aarch64에서 24~29바이트 struct의 `std::atomic<T>`는 lock-free 아님 (LSE2 없이는).
  2. smoother의 `target != target_new` float 비교는 AMCL 노이즈로 매 틱 fire.
  3. Phase 4-3에 map editor UI까지 끼어있음 — Phase 5급 스코프.
  4. Q6 primitive가 세 군데에서 "queue" / "atomic<bool>"로 불일치.
  5. AMCL divergence clamp가 `live` 기준이라 큰 재-localization 시 stale offset 교착.
- **v3 개정으로 5개 전부 해결**:
  1. `Seqlock<T>` 템플릿 명시 (single-writer + N-reader, 64-byte alignment).
  2. seqlock의 **generation counter**(정수) 기반 edge detection + `frac ≥ 1.0` 시 `live ← target` 값 복사.
  3. Phase 4-3 스코프 축소 → 3 endpoint (`/health`, `/map/backup`, `/calibrate`); map editor는 Phase 4.5로 분리.
  4. `std::atomic<bool> calibrate_requested` 한 곳으로 통일, queue 승격 경로는 미래 작업으로 명시.
  5. Clamp 기준을 `live`가 아니라 **직전 accepted target**으로, 명시적 calibrate_now 시 bypass.
- AMCL 정적 노이즈 대응으로 사용자 제기 → **cold path deadband filter** 신설 (기본 10 mm / 0.1°). gen counter + deadband 조합으로 ramp가 완주할 수 있음.
- 런타임 튜닝 가능한 값(IP, 포트, T_ramp 등) 관리 전략 합의: **Tier 1 (constexpr in `core/constants.hpp`) + Tier 2 (TOML 기반 `Config`, env 오버라이드)**. 추후 React 설정 페이지에서 편집 가능하도록 **reload-class 분류**(hot / restart / recalibrate)도 미리 명시.
- Mode-A v3 verification → **PASS-WITH-NOTES** (서브섹션 넘버링 §12.x → §11.x 글리치 하나만 즉시 수정).

### 오후 — FreeD 전송 경로 결정

- RPi5의 **RP1 I/O 컨트롤러** 이야기 — 자체 IRQ 컨트롤러와 DMA 엔진을 가진 PCIe-attached 남교(south bridge). IRQ 분리가 구조적으로 쉬워져서 RT 관점에서 유리.
- FreeD 수신을 USB-CDC(`/dev/ttyACM0`)에서 **하드웨어 PL011 UART0 (`/dev/ttyAMA0`)** 로 전환. USB bulk 폴링 주기(~8 ms)의 jitter 제거.
- 크레인 FreeD 출력(RS-232 ±12 V)은 **YL-128 (MAX3232) 모듈**로 3.3 V TTL 변환 후 GPIO15(pin 10)에 직결. 사용자의 Arduino R4 필드 교훈 두 가지 중요:
  1. **YL-128 VCC는 반드시 Pi 3V3 (핀 1 or 17)** — 5 V 주면 TTL 출력이 5 V가 되어 Pi GPIO 파괴 위험.
  2. **저항 분압 금지** — 이전 빌드에서 intermittent framing error 원인이었음. 3.3 V / 3.3 V 직결이 정답.
- SYSTEM_DESIGN.md §6.3에 배선 + 부팅 설정(`enable_uart=1`, `dtparam=uart0=on`, `cmdline.txt`에서 `console=serial0,115200` 제거) 체크리스트 반영.

### 저녁 — Phase 4-1 플래너 v1 → Mode-A → v2

- code-planner로 **Phase 4-1 = RT hot path만**(LiDAR/AMCL/webctl 제외) 계획 생성. 13 task, ~9 엔지니어 일수 규모.
- Mode-A 리뷰 결과 6 must-fix + 4 should-fix 발견:
  - `doc/freed_wiring.md` 태스크 누락
  - `serial_reader.cpp`에 8O1 termios 플래그 명시 필요
  - `P4-1-10`의 yaw blocker 직접 명시 누락
  - `test_seqlock_roundtrip.cpp` 위치 모순
  - 리스크 행 부족 (콘솔 owner race, 비-D1 패킷)
  - invariant (e) 실효성 확보
- 전부 반영한 **Plan v2** 산출. Writer 착수 가능한 상태로 확정.

### 저녁 → 심야 — Writer 실행 + Mode-B 리뷰 + cleanup

- code-writer가 **13개 태스크를 모두 구현** (약 34분간 백그라운드). 6개 incremental commit:
  - `f28abe7` tomlplusplus v3.4.0 submodule
  - `8363465` core + yaw + smoother + rt-setup foundation
  - `96319e4` freed parser + serial reader + UDP sender
  - `7f63f90` godo_tracker_rt + godo_jitter 바이너리
  - `95c9991` 10개 hardware-free 테스트 타겟
  - `72f4c28` wiring 문서 + scripts + CODEBASE invariant (e)
- 16/16 hardware-free 테스트 green (Phase 3 6개 회귀 + Phase 4-1 10개 신규).
- Writer가 명시한 **4개 deviation** 전부 CODEBASE.md에 문서화:
  1. `std::span` → `(ptr, size)` (C++17 한정 문법)
  2. `mlockall`을 RLIMIT_MEMLOCK 체크 후 호출 (dev host에서 thread_create 실패 방지)
  3. PTY 환경에서 8O1 flags가 EINVAL이라 tcsetattr는 warn-and-continue + `O_NONBLOCK` 폴백
  4. `[rt-alloc-grep]`이 UdpSender 생성자 내 `std::string(...)` 하나 감지 — 시작-once, hot path 아님
- **Jitter baseline (news-pi01, RT 권한 없이)**: p50=58 µs, p99=2028 µs, max=5338 µs. setup-pi5-rt.sh 적용 후 재측정이 "진짜" 숫자.
- Mode-B 리뷰 → **APPROVE-WITH-NOTES**. Must-fix 0개, should-fix 4개(문서/클린업). 전부 cleanup 커밋 `49f874d`에 반영:
  - `yaw::wrap_signed24` 코멘트를 pan + X/Y 양쪽 용도로 확장 문서화
  - `serial_reader`의 `O_NONBLOCK`을 termios 실패(PTY) 경로에만 적용 — 실제 PL011에서는 blocking read 유지
  - `test_rt_replay` 축소-assertion을 deviation #5로 추가
  - Magic number(`1000.0`, `64.0`, `32768.0`) → `FREED_POS_LSB_PER_M` / `FREED_PAN_LSB_PER_DEG` 명명 상수
  - Main startup 순서를 SYSTEM_DESIGN §6.2와 동일화 + 3-arg POSIX `main` 사용
- 8개 커밋 전부 `origin/main`(SBS-NCENTER/GODO_PI)에 푸시 완료.

### 심야 — 문서 정비

- RPi5 공식 PDF 4종을 `doc/hardware/RPi5/sources/`에 로컬 보관:
  - `raspberry-pi-5-product-brief.pdf` (1.1 MB)
  - `raspberry-pi-5-mechanical-drawing.pdf` (175 kB)
  - `rp1-peripherals.pdf` (3.5 MB — GPIO/UART/SPI/I²C 레지스터 레벨 참조)
  - `raspberry-pi-uart-connector.pdf` (241 kB — 참고용)
- **중요한 발견**: Raspberry Pi는 **Pi 5부터 공식 schematic PDF를 공개하지 않음**. Pi 4B / Pi 3 / Pi 2B / Pi 1 / Zero 전부 공개돼 있는데 Pi 5만 mechanical drawing + STEP 파일까지만 공개. 보드 전기 디자인이 필요하면 RP1 peripherals 매뉴얼 + 상용 공개되어있는 compliance 테스트 리포트 수준에서 충분.
- `doc/hardware/RPi5/README.md`에 40-pin 핀맵 + GODO 전용 배선(YL-128 결선) + 주의사항 정리.
- `PROGRESS.md`의 Current phase / Next up 재구성. Phase 4-1 closeout(hardware 셋업 + jitter 재측정) + Phase 4-2 queue(LiDAR + AMCL) + Phase 4-3 minimal(godo-webctl 3 endpoint) + Phase 4.5 deferred(map editor + React) + Phase 5(현장 통합).
- 이 파일(`doc/history.md`) 신설. 앞으로 날짜별 세션 기록은 여기에 한국어로, `PROGRESS.md`는 "현재 상태 + 남은 작업" 영문 체크리스트 용도로 분리 유지.

### 오늘 푸시된 커밋 요약 (origin/main: 49f874d)

```
49f874d fix(rpi5-rt): Mode-B follow-ups — constants, wrap semantics,
                     serial reader, main ordering
72f4c28 docs(rpi5): Phase 4-1 wiring doc + scripts + CODEBASE invariant (e)
95c9991 test(rpi5-rt): 10 hardware-free targets covering Phase 4-1 surface
7f63f90 feat(rpi5-rt): godo_tracker_rt binary + godo_jitter harness
96319e4 feat(rpi5-rt): FreeD parser + serial reader + UDP sender
8363465 feat(rpi5-rt): core + yaw + smoother + rt-setup foundation
f28abe7 feat(rpi5-rt): add tomlplusplus v3.4.0 submodule for config loader
879f950 docs(system): pin FreeD transport to PL011 UART0 via YL-128
807e210 docs(system): fix subsection numbering §12.x → §11.x
c6ee335 docs(system): v3 addressing Mode-A blockers + constants scaffold
30edbf1 docs(system): hot/cold path split, smoother, yaw wrap, Q6 resolved
49fdc2b fix(rpi5): tolerate transient grabScanDataHq failures during spin-up
72f4c28 docs(rpi5): Phase 4-1 wiring doc + scripts + CODEBASE invariant (e)
95a69c1 docs(hardware): tilt survey + leveling mount methodology (Plan A)
3436d96 feat(rpi5): add production C++ scaffold + godo_smoke binary (Plan B)
```

### 다음 세션 시작 시 확인할 것

1. RPi5 물리 셋업 (setup-pi5-rt.sh + YL-128 결선 + cmdline.txt) 실행 여부.
2. `godo_jitter` post-setup 재측정 결과 (`test_sessions/TS<N>/jitter_summary.md`).
3. 크레인 FreeD 실물 결선 후 `godo_tracker_rt` end-to-end 동작 로그.
4. 상기 결과에 따라 Phase 4-2 (LiDAR + AMCL + deadband) 플래너 착수.

---

## 2026-04-23

### 한 줄 요약
floor tilt survey + leveling mount 방법론 문서화 (Plan A) + RPi5 C++ Phase 3 scaffold 구축 (`godo_smoke` + 3-way 비교 워크플로우) (Plan B).

### 메모
- 두 Plan 병렬 진행. PROGRESS.md 충돌 방지 위해 **Plan B 먼저 커밋, Plan A 나중에 append** 순서로 정리.
- Phase 3 scaffold는 invariants (a)(b)(c)(d) 4개 pin.
  - (a) no ABC — duck-typed `LidarSourceRplidar` vs `LidarSourceFake`
  - (b) test-include split — `test_csv_writer_readback`는 production include path 제외
  - (c) hot-path allocation 허용 범위(smoke 스코프)
  - (d) setlocale("C")은 main에서만
- Python 프로토타입과의 **byte-identical CSV parity** 테스트 `test_csv_parity` 통과 (uv run + cmp -s).

---

## 2026-04-21

### 한 줄 요약
알고리즘 방향 확정 (Approach B + O3 → O4) + RPi5 + 네이티브 C++ 단일 바이너리 결정 + SHOTOKU FreeD Pan 의미 정확화 + 에이전트 파이프라인 공식화.

### 메모
- FreeD Pan = **base-local** (pan-head 엔코더, 바퀴 평행 규칙 덕분에 사실상 world-frame과 동일).
- AMCL이 `(x, y, yaw)` 3-DOF를 동시에 출력 → yaw 별도 보정 불필요.
- Docker + ROS 2 Jazzy + slam_toolbox는 **지도 제작 시에만** 한 번 사용, 런타임은 네이티브 C++.
- Q7 해결: FreeD 수신·변환·송신 전부 RPi5 C++ 바이너리 내부.

---

## 2026-04-20

### 한 줄 요약
Phase 0 완료 — RPLIDAR C1 deep dive + CLAUDE.md 9-section 구조화.

### 메모
- `doc/RPLIDAR/RPLIDAR_C1.md` 작성 (측정 원리, 스펙, UART 프로토콜, SDK 분석, chroma studio 적합성).
- 원본 PDF 2개 (`C1 datasheet v1.0`, `S&C-series protocol v2.8`) → `doc/RPLIDAR/sources/`에 오프라인 참조용 보관.
- 프로젝트 전체 재시작 가능성을 위해 `PROGRESS.md` 신설.
