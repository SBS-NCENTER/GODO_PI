# RPi 5 GPIO UART 직결 migration plan (RPLIDAR C1)

> **Status**: deferred. issue#17 후보. CP2102N USB 어댑터 stale-state 문제가 운영을 자주 방해하면 ship.
> Linked memory: `.claude/memory/project_gpio_uart_migration.md`.
> Author: 2026-05-02 KST (operator HIL on news-pi01 surfaced cp210x stale state during issue#14 mapping pipeline)

---

## 1. 배경

issue#14 mapping pipeline HIL에서 **CP2102N USB-to-UART 어댑터의 stale state**가 반복적으로 mapping container의 RPLIDAR 통신을 차단:

```
dmesg: cp210x ttyUSB1: failed set request 0x12 status: -110
       (USB CDC SET_LINE_CODING timeout)
rplidar_node ERROR: code 80008004 (RESULT_OPERATION_TIMEOUT)
```

원인 chain:
1. godo-tracker 종료 → SDK가 `stop()` + 200ms wait + `setMotorSpeed(0)` + close 정상 수행
2. 그러나 cp210x driver 내부 USB CDC handle이 immediate cleanup 안 됨
3. 곧바로 mapping container가 같은 device 열려 하면 SET_LINE_CODING command가 응답 없음 → `-110 ETIMEDOUT`
4. RPLIDAR 모터는 정상 회전하지만 호스트 측에서 데이터 수신 불가

**증상**: tracker stop 직후 mapping start 시도 → 80008004 timeout → "Failed". 약 10초 기다리면 정상 동작. operator 운영 환경에서는 이 race가 빈번.

**단기 mitigation (issue#16, 1단계)**: webctl이 mapping start 전 cp210x readable check + 필요시 driver unbind/rebind + Pre-check gate (Start 버튼 활성화 조건 명시).

**장기 mitigation (이 문서, issue#17, 2단계)**: USB CDC layer 자체 제거 — RPLIDAR C1을 Pi 5 GPIO UART에 직결.

---

## 2. CP2102N vs GPIO UART 직결 비교

| 항목 | CP2102N USB | Pi 5 GPIO UART 직결 |
|---|---|---|
| **Stale state 가능성** | 있음 (issue#14 운영 발생) | 없음 (PL011 직접) |
| **추가 layer** | USB CDC + cp210x driver | PL011 hardware UART |
| **Latency** | 5-15 ms (USB poll-bulk) | < 1 ms |
| **어댑터 단일 실패점** | 있음 (CP2102N 자체 고장 가능) | 없음 |
| **Hot-plug** | ✅ 가능 | ❌ Pi 끄고 작업 |
| **진단 도구** | 풍부 (lsusb, dmesg, usbreset) | 빈약 (kernel UART log만) |
| **Pi 전원 부담** | 없음 (어댑터가 5V 공급) | C1 cold-start 800 mA peak를 Pi 5V rail에서 |
| **운영 복잡도** | 낮음 (plug-and-play) | 중간 (config.txt + dts overlay) |
| **운영 시나리오 적합도** | LiDAR cable 자주 빼고 옮기는 환경 | LiDAR 한 번 설치 후 고정 운영 |

**operator 운영 환경 (chroma studio TS5)**: LiDAR가 크레인 베이스 pan-axis 중심에 mount, 한 번 설치 후 거의 분리 안 함. → **GPIO 직결이 더 적합**.

---

## 3. UART 현황 (이미 ttyAMA0 사용 중)

`/dev/ttyAMA0` (PL011 UART0) = **이미 FreeD 수신용**:
- `/var/lib/godo/tracker.toml`: `freed_port = "/dev/ttyAMA0"`
- `production/RPi5/src/core/config_defaults.hpp`: `FREED_PORT = "/dev/ttyAMA0"`
- `/boot/firmware/config.txt`: `enable_uart=1` + `dtparam=uart0=on`
- 물리적 연결: GPIO 14 (TXD0) / 15 (RXD0) 통해 YL-128 RS422→TTL 어댑터에 연결, 어댑터 입력은 SHOTOKU 크레인 FreeD D1 출력

→ C1 LiDAR는 **다른 PL011 인스턴스**를 새로 활성화해야 함. Pi 5는 PL011 6개 보유 (UART0~5).

### 사용 가능한 PL011 인스턴스

| UART | TX pin (BCM) | RX pin (BCM) | dtoverlay | 비고 |
|---|---|---|---|---|
| UART0 | GPIO 14 | GPIO 15 | `uart0` | **FreeD 사용 중** |
| UART2 | GPIO 4  | GPIO 5  | `uart2-pi5` | I2C-1과 충돌 가능성 (사용 안 하면 OK) |
| UART3 | GPIO 8  | GPIO 9  | `uart3-pi5` | SPI-0 CE0/MISO와 핀 공유 |
| UART4 | GPIO 12 | GPIO 13 | `uart4-pi5` | PWM-0/1과 핀 공유 (godo는 PWM 미사용) |
| UART5 | GPIO 16 | GPIO 17 | `uart5-pi5` | 일반적으로 free |

**권장**: UART4 (`uart4-pi5`, GPIO 12/13). 이유:
- I2C / SPI / I2S 핀과 안 겹침
- godo project가 PWM 미사용
- physical position이 GPIO header 가장자리로 케이블 라우팅 깔끔

device file: `/dev/ttyAMA4` (또는 자동 enumeration된 ttyAMA*)

---

## 4. 전원 분석

### C1 power requirement (`doc/RPLIDAR/RPLIDAR_C1.md` §6)

| Item | Value |
|---|---|
| Voltage | 4.8–5.2 V (typ. 5.0) |
| Ripple tolerance | ≤ 150 mV |
| **Cold-start peak** | **800 mA** (~1 ms transient) |
| Steady-state | 230–260 mA @ 10 Hz |

### Pi 5 5V rail capacity

| PSU | USB-C input | Pi 자체 사용 | 5V rail 잔여 | C1 cold-start 800mA 대응 |
|---|---|---|---|---|
| 27W official PSU | 5V/5A (PD) | ~1.5A | ~3.5A | ✅ 충분 |
| 15W official PSU | 5V/3A | ~1.5A | ~1.5A | ⚠ 마진 작음 |
| 일반 5V/2A 어댑터 | 2A | ~1.5A | ~0.5A | ❌ 부족 (cold-start 시 droop) |

**필수**: Pi 5 27W 공식 PSU 사용 (operator는 이미 이걸 사용 중일 가능성 높음 — 확인 필요).

### Pi 5 5V rail 자체 보호 회로

- **PMIC (DA9091)**: USB-C input의 over-voltage protection + PD negotiation
- **5V rail**: bulk capacitance ~470 µF (board level)
- ❌ **Inrush current 제한 회로 없음** — GPIO 5V pin은 raw 5V rail 직결
- ❌ **Per-pin current limit 없음** — pin 자체에 fuse / PTC 없음

→ C1 cold-start 800 mA peak가 microsecond 단위로 5V rail에 droop 일으킬 수 있음. Pi 자체는 onboard cap이 흡수하지만, 다른 peripheral (HDMI, USB downstream 등)이 동시에 startup이면 5V rail 잠시 4.7V까지 droop 가능 → C1 ripple > 150 mV 우려.

### External decoupling cap 권장

C1 VCC pin (Red wire) ↔ GND (Black wire) 사이에 부착:

| Cap | 용도 | 위치 |
|---|---|---|
| **1000 µF electrolytic** (16V) | Bulk — cold-start spike 흡수 | C1 connector 가까이 (≤ 5 cm) |
| **0.1 µF ceramic** (X7R, 10V) | High-freq decoupling — UART noise 차단 | C1 connector pin 직접 |

총 부품비 ~500원. 소형 protoboard 또는 직접 납땜 가능.

---

## 5. 마이그레이션 단계 (when triggered)

### 5.1. Hardware

1. **PSU 확인**: 27W 공식 PSU 사용 확인. 아니면 교체.
2. **케이블 작업**:
   - C1 native 4-pin XH2.54 connector → Pi GPIO header 점퍼 와이어
   - VCC (Red) → Pi pin 4 (5V) — pin 2도 5V지만 4가 GPIO header 더 가까이
   - TX (Yellow) → Pi pin 33 (GPIO 13 / RXD4)
   - RX (Green) → Pi pin 32 (GPIO 12 / TXD4)
   - GND (Black) → Pi pin 6 (GND)
3. **Decoupling cap**: 1000 µF + 0.1 µF를 C1 connector 직전에 부착 (VCC ↔ GND).

### 5.2. Software — config.txt

`/boot/firmware/config.txt`에 추가:

```
# GODO: PL011 UART4 for RPLIDAR C1 direct connection (issue#17)
dtoverlay=uart4-pi5
```

기존 `enable_uart=1` + `dtparam=uart0=on` (FreeD용) 유지.

```bash
sudo nano /boot/firmware/config.txt   # add line above
sudo reboot
ls /dev/ttyAMA*                        # /dev/ttyAMA4 가 새로 보여야 함
```

### 5.3. tracker.toml

```bash
sudo sed -i 's|lidar_port = .*|lidar_port = "/dev/ttyAMA4"|' /var/lib/godo/tracker.toml
```

또는 SPA Config 탭에서 `serial.lidar_port` 편집.

### 5.4. godo-mapping container

`production/RPi5/systemd/godo-mapping@.service`의 `--device=${LIDAR_DEV}`는 그대로 동작 (envfile에 `/dev/ttyAMA4` 들어가면 자동 통과).

container 내부 `launch/map.launch.py`도 변경 불필요 (env 그대로 read).

### 5.5. 검증

```bash
# 1. tracker로 sanity check
sudo systemctl restart godo-tracker  # 또는 SPA System tab Restart
# Map > Calibrate → 정상 converged 확인

# 2. mapping pipeline
# SPA → tracker stop → mapping start → preview 갱신 + scan 정상

# 3. CP2102N 어댑터 + USB 케이블 분리, 보관
```

### 5.6. issue#10 deprecation

GPIO 직결 후에는 `/dev/ttyUSB*` enumeration 변동 자체가 없음. issue#10 (udev `/dev/rplidar` 심링크)은 **불필요**. NEXT_SESSION TL;DR에서 issue#10 제거.

---

## 6. 작업 추정 시간

| 단계 | 시간 | 비고 |
|---|---|---|
| 케이블 작업 (점퍼 + cap 납땜) | 30분 | 소형 protoboard 사용 시 |
| config.txt 변경 + 재부팅 | 5분 | |
| tracker.toml 갱신 + 검증 | 10분 | tracker Live mode 정상 확인 |
| mapping pipeline 검증 | 20분 | scenarios A-G 핵심만 |
| **총** | **~1시간** | |

---

## 7. Trade-off 요약

| 측면 | 권장 결정 |
|---|---|
| **Mapping 안정성** | GPIO 직결 (cp210x stale state 자체가 사라짐) |
| **운영 단순성** | GPIO 직결 (USB 케이블 race 없음) |
| **Latency / 정확성** | GPIO 직결 (USB CDC layer 제거) |
| **변경 작업 부담** | CP2102N 유지 (현재 동작 OK + issue#16 단기 mitigation으로 충분) |
| **Hot-plug** | CP2102N 유지 (자주 LiDAR 분리/교체하는 환경이면) |

**operator 환경 (TS5 chroma studio, LiDAR 한 번 설치 후 고정)**: 장기 안정성 우선 → **GPIO 직결 권장**.

다만 issue#16 (1단계) 먼저 ship + 운영 모니터링 → cp210x stale state 빈도가 issue#16 mitigation으로 충분히 줄어들면 GPIO migration 보류 가능.

---

## 8. 관련 문서

- `doc/RPLIDAR/RPLIDAR_C1.md` §6 — MCU/SBC compatibility matrix, electrical spec
- `production/RPi5/src/core/config_defaults.hpp` — `LIDAR_PORT` default (변경 시 동기화)
- `production/RPi5/systemd/godo-mapping@.service` — `--device=${LIDAR_DEV}` 사용
- `.claude/memory/project_gpio_uart_migration.md` — 의사결정 컨텍스트 (이 문서의 요약)
