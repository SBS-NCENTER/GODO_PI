# godo-mapping — SLAM 매핑 도구

GODO LiDAR 기반 카메라 위치 추적 시스템의 **2D occupancy-grid 지도**를
생성하는 Docker 기반 SLAM 툴체인입니다. RPLIDAR C1을 들고 컨트롤룸을 약 1분
정도 천천히 걸으면 `maps/<map_name>.{pgm,yaml}` 파일이 만들어지며, 이 파일은
`production/RPi5`의 `occupancy_grid.cpp::load_map`이 그대로 읽어들입니다.

ROS 2 의존성은 전부 컨테이너 안에 격리되어 있어 호스트 RPi 5에는 ROS를
설치하지 않습니다.

## 사전 준비

### 호스트 요구사항

- Linux (RPi 5 / 일반 dev box)
- Docker
- (실행 시에만) RPLIDAR C1 + USB CP2102 동글
- (선택) `bash`, `python3` — `verify-no-hw.sh --quick`에 필요

### 1회용 셋업

```bash
git clone <repo> GODO
cd GODO/godo-mapping
bash scripts/verify-no-hw.sh --quick     # ~1초, Docker 데몬 불필요
bash scripts/verify-no-hw.sh --full      # ~5분, ~800 MB pull, Docker 데몬 필요
```

`--full`은 `godo-mapping:dev` 이미지를 빌드하고 `--help` smoke 테스트까지
끝냅니다. 이미지가 캐시된 뒤에는 LiDAR가 연결된 운영 환경에서 추가 네트워크
없이 매핑을 시작할 수 있습니다.

## 운영 절차 (5단계)

LiDAR가 USB로 꽂혀 있고 `godo-mapping:dev` 이미지가 빌드된 상태를 전제합니다.

```bash
cd /path/to/GODO
bash godo-mapping/scripts/run-mapping.sh control_room_v1
```

1. 위 명령을 실행하면 컨테이너가 뜨면서 `slam_toolbox`와 `rplidar_ros`가
   `/scan` 토픽을 시작합니다.
2. RPLIDAR C1을 손에 들고 매핑할 공간을 **천천히 (~30 cm/s)** 한 바퀴 돕니다.
   가능하면 시작점으로 돌아와 loop closure가 일어나도록 합니다.
3. 약 1분 정도 (스튜디오 면적 기준) 걸린 뒤 터미널에서 `Ctrl+C`를 누릅니다.
4. `entrypoint.sh`의 trap이 `nav2_map_server map_saver_cli`를 호출해
   `godo-mapping/maps/control_room_v1.pgm` + `.yaml`을 저장합니다.
5. 두 파일을 `/etc/godo/maps/`로 복사하면 production tracker가 다음 부팅에서
   읽어들입니다.

```bash
sudo cp godo-mapping/maps/control_room_v1.{pgm,yaml} /etc/godo/maps/
sudo systemctl restart godo-tracker
```

### 환경 변수 오버라이드

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `LIDAR_DEV` | `/dev/ttyUSB0` | LiDAR가 다른 USB 포트로 잡힐 때 사용 |
| `IMAGE_TAG` | `godo-mapping:dev` | 다른 이미지 태그를 쓸 때 |

```bash
LIDAR_DEV=/dev/ttyUSB1 bash godo-mapping/scripts/run-mapping.sh studio_v2
```

## 첫 매핑 후 검증 (필수, plan F11)

저장된 YAML 키 집합이 `production/RPi5/src/localization/occupancy_grid.cpp`의
허용 집합과 일치해야 tracker가 부팅 시 throw하지 않습니다.

```bash
cat godo-mapping/maps/control_room_v1.yaml
```

콜론 좌측의 모든 키를 `occupancy_grid.cpp:148-154`의 union 집합과
대조합니다.

```text
required    = { image, resolution, origin, occupied_thresh,
                free_thresh, negate }
warn_accept = { mode, unknown_thresh }
```

이 집합 밖의 키 (예: `cost_translation_table`)가 보이면:

- ❌ `entrypoint.sh`에서 YAML을 후처리하지 마세요.
- ✅ Path (a) ONLY: `production/RPi5/src/localization/occupancy_grid.cpp::warn_accept`에
  키를 추가하는 follow-up 이슈를 만듭니다. C++ allowlist이 SSOT입니다.
- 본 작업은 Track A 범위 밖이며, Parent에게 보고 후 별도 세션에서 처리합니다.

## 트러블슈팅

### `LiDAR device '/dev/ttyUSB0' not found`

다른 USB 포트로 잡혔을 가능성이 큽니다. `dmesg | tail` 또는 `ls /dev/ttyUSB*`로
확인 후 `LIDAR_DEV` 환경변수로 오버라이드합니다.

### `container 'godo-mapping' is already running`

이전 실행이 정상 종료되지 않았습니다.

```bash
docker stop godo-mapping
docker rm godo-mapping        # --rm으로 시작했지만 강제 종료된 경우
```

### `'maps/<name>.pgm' already exists`

같은 이름으로 두 번 매핑하려 하고 있습니다. 의도적이라면 기존 파일을
백업한 뒤 삭제하거나, 새 이름을 사용합니다.

```bash
mv godo-mapping/maps/control_room_v1.pgm godo-mapping/maps/control_room_v1.pgm.bak
mv godo-mapping/maps/control_room_v1.yaml godo-mapping/maps/control_room_v1.yaml.bak
```

### Stale dev images

오래된 dev 이미지를 정리하거나 처음부터 다시 빌드하려면:

```bash
docker image prune --filter label=godo-mapping
# 또는 강제 재빌드:
docker rmi godo-mapping:dev && bash scripts/verify-no-hw.sh --full
```

### `MAP_NAME env-var is required`

내부에서만 발생합니다. `scripts/run-mapping.sh`를 우회해 직접 `docker run`을
한 경우이며, `-e MAP_NAME=<name>`을 추가해야 합니다.

### Ctrl+C 후 지도 파일이 비어 있음 / 만들어지지 않음

매핑 시작 후 너무 빨리 (`launch graph` 가 다 뜨기 전에) Ctrl+C 했을 가능성이
큽니다. 약 5초 정도 기다렸다가 매핑 동작을 시작하세요.

### Hardware-free 검증

LiDAR가 연결되지 않은 dev 박스에서 코드 수정 직후 lint:

```bash
bash godo-mapping/scripts/verify-no-hw.sh --quick   # ~1초
bash godo-mapping/scripts/verify-no-hw.sh --full    # ~5분 (Docker 데몬 필요)
```

## 디렉터리 구조

```text
godo-mapping/
├─ Dockerfile                    # FROM ros:jazzy-ros-base + 3개 ros 패키지
├─ launch/map.launch.py          # rplidar_c1 + slam_toolbox async 노드
├─ config/slam_toolbox_async.yaml # base_frame=laser, save_map_timeout=10.0
├─ entrypoint.sh                 # SIGINT/SIGTERM trap → map_saver_cli
├─ scripts/
│   ├─ run-mapping.sh            # 호스트 docker-run 래퍼
│   └─ verify-no-hw.sh           # --quick / --full
├─ tests/test_entrypoint_trap.sh # bare-bash trap mock 테스트
├─ maps/                         # *.pgm, *.yaml 결과물 (gitignored)
├─ README.md                     # ← 이 문서
└─ CODEBASE.md                   # 모듈 맵 + invariants + change log
```

## 참고

- 컨테이너 내부 ROS 분리: `production/RPi5/`와 `godo-webctl/`는 ROS를 import하지
  않습니다 (`grep -rn 'rclcpp\|ament' production/RPi5/src/` returns 0).
  `--network=host`는 안전합니다.
- 매핑 결과 SSOT: `production/RPi5/src/localization/occupancy_grid.cpp::load_map`
  (PGM P5 8-bit + flat key:value YAML).
- 본 도구는 매핑 전용입니다. localization (AMCL)은 production tracker가 매핑된
  지도를 입력 받아 별도로 처리합니다.
