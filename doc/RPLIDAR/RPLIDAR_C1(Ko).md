# RPLIDAR C1 — Phase 0 심층 분석

> **목적**: 본 프로젝트(LiDAR 기반 카메라 위치 트래킹)에서 사용할 SLAMTEC RPLIDAR C1의 모든 기술 스펙, 통신, SDK, 환경 적합성, 설계 함의를 SSOT(Single Source of Truth)로 정리.
>
> **출처 우선순위**: SLAMTEC 공식 데이터시트 v1.0 (로컬 사본) > SLAMTEC 공식 FAQ/SDK > 벤더 위키/블로그
>
> **최종 업데이트**: 2026-04-20

---

## 0. 한눈에 보는 요약

```
┌──────────────────────────────────────────────────────────────┐
│ SLAMTEC RPLIDAR C1M1-R2   (2023-10 출시)                     │
├──────────────────────────────────────────────────────────────┤
│ 측정 원리   │ Direct TOF (DTOF) + SL-DTOF fusion           │
│ 레이저      │ 905 nm NIR, Class 1, 20W peak / 1.4ns pulse  │
│ 거리        │ 0.05 ~ 12 m  (흰 70%) / 0.05 ~ 6 m (검 10%)  │
│ 정확도      │ ±30 mm   (단일 샘플)                          │
│ Resolution  │ 15 mm                                        │
│ Scan Rate   │ 8 ~ 12 Hz (typ. 10 Hz)                       │
│ Sample Rate │ 5 kHz   (각분해능 0.72° @ 10 Hz)              │
│ 주변광 한도 │ 40,000 lux                                   │
│ IP Rating   │ IP54                                         │
│ UART        │ 3.3 V TTL, 460,800 bps, 8N1                  │
│ 전원        │ 5 V ±4%, start 800 mA / run 230~260 mA       │
│ 크기/무게   │ 55.6 × 55.6 × 41.3 mm / 110 g                │
│ 동작온도    │ -10 ~ +40 °C                                 │
└──────────────────────────────────────────────────────────────┘
```

---

## 1. 측정 원리 및 광학

| 항목 | 값 | 비고 |
|---|---|---|
| 측정 원리 | **Direct TOF (DTOF)** | SLAMTEC 자체 "SL-DTOF fusion ranging" |
| 광원 | Modulated pulse NIR laser | - |
| 파장 | **905 nm** (typ), 895 ~ 915 nm | 근적외선 대역 |
| Peak Power | 20 W | 평균 전력은 훨씬 낮음 |
| Pulse Length | 1.4 ns (typ) | - |
| Laser Safety | **IEC-60825 Class 1** | 인체 안전, 차폐 불필요 |

### 설계 함의

- **DTOF**: 거리 증가에 따른 정확도 열화가 triangulation(A 시리즈)보다 작음
- **배경광 외란 강건**: 40,000 lux 실내조명 여유
- **905 nm NIR**: 가시광 무관 → 크로마 녹/청 자체는 문제 아님 (페인트 NIR 반사율이 변수)

---

## 2. 핵심 성능 스펙 (공식 데이터시트)

| 항목 | 값 |
|---|---|
| Distance Range (70% reflect) | 0.05 ~ 12 m |
| Distance Range (10% reflect) | 0.05 ~ 6 m |
| **Accuracy** | **±30 mm** (25 °C, 10 ~ 90% reflectance) |
| **Resolution** | **15 mm** |
| Sample Rate | 5 kHz (fluctuation < 1%) |
| Scanning Frequency | 8 ~ 12 Hz (typ. 10 Hz, fluctuation < 5%) |
| Angular Resolution | 0.72° @ 10 Hz |
| Scan Field Flatness | 0° ~ 1.5° (customizable) |
| Ambient Light Limit | 40,000 lux |
| IP Rating | IP54 |
| Working Temp. | -10 ~ +40 °C |
| Storage Temp. | -20 ~ +60 °C |
| Weight | 110 g |
| Dimensions | 55.6 × 55.6 × 41.3 mm |
| Mounting | 4 × M2.5, 나사깊이 ≤ 4 mm |

### 정밀도 계산 (중요)

- 각 샘플 간 각도 간격 0.72° → 거리 `r`에서 선형 간격 = `r × tan(0.72°)`
  - `r = 3 m` → ≈ 38 mm
  - `r = 5 m` → ≈ 63 mm
  - `r = 10 m` → ≈ 126 mm
- 단일 샘플 오차 ±30 mm는 **N회 평균 시 √N 배 축소** (화이트 노이즈 가정)
- 1-shot 정적 캘리브레이션을 **5~10초간 정지 스캔**으로 설계하면:
  - 프레임 수 ≈ 50~100 frame
  - 한 방향에 수백 개 샘플 쌓임
  - **이론상 mm 단위, 실측상 ≤10 mm 정확도 달성 가능**

---

## 3. 통신 프로토콜 및 데이터 포맷

### UART 설정

| 항목 | 값 |
|---|---|
| 인터페이스 | **TTL UART 3.3 V** |
| Baud Rate | **460,800 bps** |
| 프레임 | 8N1 (8 data / 1 stop / no parity) |
| Output High Voltage | 3.3 V typ (2.9 ~ 3.5) |
| Output Low Voltage | ≤ 0.4 V |
| Input High Voltage | 3.3 V typ (2.4 ~ 3.5) |
| Input Low Voltage | ≤ 0.4 V |

### 프레임 구조 기본

| 요소 | 값 |
|---|---|
| Request Start Byte | `0xA5` |
| Response Descriptor | `0xA5 0x5A` (2 bytes) |
| Checksum | XOR 기반 |
| Protocol 호환성 | A-Series Standard + S-Series Express/Ultra 모두 지원 |

### 샘플당 데이터 필드

| 필드 | 단위 | 설명 |
|---|---|---|
| Distance Value | mm | LiDAR 중심으로부터 거리 |
| Angle | degree | 샘플 각도 (0 ~ 360) |
| Start Signal | Boolean | 새 프레임 시작 flag |
| Quality | 0 ~ 255 (SDK 레벨) | 신호 세기/신뢰도 |
| Flag | bits | sync bit 등 |
| Checksum | — | 프레임 체크섬 |

### 좌표계

```
       x  (scanner 정면, θ=0°)
       ▲
       │
       │   θ (0~360°, clockwise)
       │
  ─────┼─────────► y
       │
   [RPLIDAR C1]   ← 회전축 = 좌표계 원점 (Left-hand)
```

---

## 4. SDK 및 Python 바인딩

### 공식 SDK — [Slamtec/rplidar_sdk](https://github.com/Slamtec/rplidar_sdk)

| 항목 | 내용 |
|---|---|
| 지원 OS | x86 Windows, x86 Linux, macOS, ARM Linux |
| 언어 | C++ |
| 라이선스 | SDK: BSD 2-clause / 데모: GPLv3 |
| C1 공식 지원 | ✅ (A1/A2/A3/S1/S2/S3/**C1**/T1) |
| 주요 API | `grabScanDataHq()`, `getAllSupportedScanModes()` |
| 데모 | `ultra_simple`, `simple_grabber`, `frame_grabber` (Win 전용) |
| RoboStudio Plugin | **Framegrabber** 제공 (디버깅/시각화) |

### Python 바인딩 비교

| 라이브러리 | C1 공식지원 | 속도 | 비고 |
|---|---|---|---|
| `rplidar` (SkoltechRobotics) | ❌ (A1/A2만) | 낮음 | 가장 널리 쓰이지만 프레임 드롭 잦음 |
| `pyrplidar` (Hyun-je) | ❌ | 중 | generator 기반, 비동기 처리 |
| `Adafruit_CircuitPython_RPLIDAR` | ❌ | 낮음 | 버그 多, 학습용 |
| `FastestRplidar` (SWIG) | ⚠ A2 주대상 | 높음 | C++ SDK 래핑, C1 포팅 필요할 수 있음 |
| **공식 SDK + pybind11/ctypes** | ✅ | 최고 | **본 프로젝트 권장** |

---

## 5. "Raw Python 데이터는 지저분" 현상의 원인

**관찰**: 기본 RoboStudio/SDK에서는 스캔이 깔끔, Python으로 받으면 노이즈가 많음.

### 원인 분석 (영향도 순)

| # | 원인 | 영향도 | 해결 방법 |
|---|---|---|---|
| 1 | Quality 필드 무시 (필터 없이 사용) | ★★★★ | quality ≥ 80 이상만 사용 |
| 2 | Standard vs Express/Ultra 모드 혼동 | ★★★★ | SDK의 Scan Mode API로 최적 모드 선택 |
| 3 | Checksum-fail 프레임 재조립 오류 | ★★★ | 공식 SDK 사용 |
| 4 | Frame sync bit 해석 오류 (반주기 프레임) | ★★★ | 공식 SDK 사용 |
| 5 | USB-Serial 버퍼링으로 인한 타이밍 drift | ★★ | 수신 버퍼 키우기 |
| 6 | 모터 동기화 실패 → 각도 drift | ★★ | 시동 후 0.5s 대기 |
| 7 | Python GC/GIL로 인한 프레임 드롭 | ★★ | C++ 래핑 또는 멀티프로세스 |

### 권장 Phase 1 방침

1. **공식 C++ SDK의 `ultra_simple`로 raw 데이터 덤프** → Python에서 분석
2. 직접 Python 파싱이 필요하면: `pyrplidar` 기반 + Express 모드 수동 구현, 또는 FastestRplidar의 C1 포팅
3. 실시간 처리는 **C++ SDK 직접 호출** (RPi 5 on Linux)

---

## 6. MCU / SBC 직결 가능성

### 물리 인터페이스 — XH2.54-5P 커넥터

| 핀 | 색상 | 신호 | 설명 | 전압 |
|---|---|---|---|---|
| 1 | 빨강 | VCC | 전원 입력 | 4.8 ~ 5.2 V DC |
| 2 | 노랑 | TX | UART TX (out) | 3.3 V TTL |
| 3 | 녹색 | RX | UART RX (in) | 3.3 V TTL |
| 4 | 검정 | GND | 접지 | 0 V |
| 5 | — | (NC/Shield) | 미사용 | — |

**⚠ 중요**: C1에는 **MOTOCTL(PWM) 핀이 외부 노출되어 있지 않음**. 모터 속도는 시리얼 명령으로만 제어. (A1의 큰 차이점)

### 전원 요구사항

| 항목 | 값 | 주의 |
|---|---|---|
| Power Voltage | 4.8 ~ 5.2 V (typ 5.0) | 미달 시 측정 부정확 |
| Power Ripple | ≤ 150 mV | 초과 시 레이저 방출 불안정 |
| **Start Current (peak)** | **800 mA** | **콜드 스타트 순간** |
| Normal Current | 230 ~ 260 mA (@ 10 Hz) | 정상 동작 |

### MCU/SBC 호환성 매트릭스

| Device | UART 직결 | 전원 | Baud 460800 | 종합 |
|---|---|---|---|---|
| Arduino UNO/R3 (5V) | ⚠ 레벨 시프터 권장 (RX 5→3.3V 분압 필수) | USB 500 mA로 start 800 mA 부족 → 외부 전원 | 오차 ~3.5%, 비권장 | ✗ 비추 |
| **Arduino R4 WiFi** | 3.3V 수신 OK | VIN에 5V/1A 외부전원 | 48 MHz, OK | ✅ 가능 |
| **RPi Pico / Pico W** | **직결 OK** (3.3V 로직) | C1에 별도 5V/1A 공급 필요 | 125 MHz + PIO, 매우 여유 | ✅ 최적 (소형) |
| **RPi 5** | USB-CP2102N (현재) 또는 GPIO UART 직결 | USB 5V 충분 | 문제 없음 | ✅ 최고 유연성 |

### SPI 지원 여부

**지원하지 않음.** C1은 UART 전용.

---

## 7. 스튜디오 환경 적합성

> 공식 자료 부족 부분은 **물리학적 추론** 및 **NIR 반사율 일반론** 기반. Phase 1에서 실측 검증 필수.

| 대상 | 905 nm NIR 반사율 (추정) | 유효 거리 | 리스크 |
|---|---|---|---|
| 크로마 녹색 벽 (paint) | 40 ~ 60% | ≥ 10 m | 낮음 (페인트별 편차 존재) |
| 크로마 청색 벽 | 40 ~ 60% | ≥ 10 m | 낮음 |
| **검정 흡수체 (velvet)** | **< 5%** | **≤ 3 m** | **⚠ 매우 높음 — 데이터 손실 가능** |
| 금속 장비 (TV 트롤리) | 거울 반사 (specular) | 각도 의존 | 다중 반사 / missing return |
| 모니터/TV 화면 | specular + 얇은 glass | 정면각 불안정 | 중간 |
| 사람 옷/피부 | 10 ~ 40% | 6 ~ 10 m | 낮음 (LiDAR 아래에서 움직임) |
| 스튜디오 문 | 30 ~ 50% | 안정 | 낮음 (움직이는 피처로만 관리) |
| HMI/LED 조명 | 가시광 → 문제 무관 | 40,000 lux 한도 내 | 낮음 |

### 주의 사항

1. **크로마 페인트의 NIR 반사율은 제조사마다 다름** — Phase 1 실측 필수
2. **모니터/거울의 specular 반사**는 ICP/wall-fitting에서 outlier 제거 대상 (quality + RANSAC)
3. **검정 흡수체가 회전축 가까이 있으면** 해당 방향 정보 손실 → 기준 스캔 피처에서 배제
4. **크레인 암의 self-occlusion** → 기준 스캔에 미리 포함해서 상쇄, 또는 크레인 pan yaw 기반 마스킹

---

## 8. SLAMTEC 라인업 내 C1 포지셔닝

| 모델 | 기술 | 거리 | Sample Rate | 각분해능 | 가격대 | 주 용도 |
|---|---|---|---|---|---|---|
| A1 | Triangulation | 0.15 ~ 12 m | 8 kHz | 0.36 ~ 0.9° | 저렴 | 홈로봇 기초 |
| A2 | Triangulation | 0.2 ~ 16 m | 16 kHz | 0.225° | 중 | 일반 SLAM |
| A3 | Triangulation | 0.2 ~ 25 m | 16 kHz | 0.225° | 중상 | 실내외 |
| **C1** | **Fusion DTOF** | **0.05 ~ 12 m** | **5 kHz** | **0.72°** | **저렴** | **홈/소형로봇** |
| S1 | TOF | 0.1 ~ 40 m | 8 ~ 15 kHz | 0.391° | 상 | 실내외 장거리 |
| S2 | TOF | 0.05 ~ 30 m | 10 kHz | 0.12° | 상 | 고정밀 SLAM |
| S3 | TOF | 0.05 ~ 40 m | 10 ~ 20 kHz | 0.1125° | 최상 | 프리미엄 |

### C1의 본 과제 적합성

**강점**
- ✅ DTOF → 거리 전 구간에서 정확도 균일
- ✅ 5 cm 블라인드 → 크레인 암 바로 아래 장착 가능
- ✅ Class 1 + 경량 110 g → 크레인 장착 무리 없음
- ✅ 저렴 + 저전력 + Windows/macOS/Linux/ARM Linux 모두 지원

**약점**
- ⚠ 각분해능 0.72°는 S 시리즈 대비 거침 → 다중 프레임 평균 필수
- ⚠ Sample Rate 5 kHz는 S 시리즈의 1/2~1/4
- ⚠ 단일 샘플 ±30 mm는 실사용상 다중 평균 없이 1~2 cm 목표 달성 불가

### 재검증 결과

본 과제 특성 — **1-shot 정적 측정, 12 m 이내 스튜디오, 1~2 cm 허용 오차, 사람 키 위 설치** — 에 비추어 **C1로 충분**. S2/S3는 비용 과잉.

---

## 9. 본 과제 설계 결정 함의

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. Phase 1 프로토타입:                                             │
│    공식 C++ SDK(ultra_simple)로 raw 덤프 → Python에서 분석        │
│    "Python 데이터 지저분" 문제를 뿌리에서 해결                     │
│                                                                  │
│ 2. 좌표계 설정(B축) 방침: Reference-scan + ICP 권장               │
│    0.72° 각분해능이라 wall-fitting만으로는 거칠어,                │
│    ICP가 "전체 면 모양" 정합이라 더 robust                        │
│                                                                  │
│ 3. 연산 파이프라인(C축) 1순위: RPi 5                               │
│    공식 SDK가 ARM Linux 1급 지원, ICP/Python/C++ 모두 편함         │
│    → (RPi 5 계산) + (UDP로 offset 송신) 조합 가장 깔끔            │
│                                                                  │
│ 4. 정확도 달성 전략:                                              │
│    "1-shot" = 5~10초 정적 스캔 = 50~100 프레임                    │
│    한 방향에 수백 개 샘플 → √N 평균으로 ≤10 mm 가능               │
│                                                                  │
│ 5. 환경 대비:                                                    │
│    검정 흡수체 방향 배제, 모니터/거울은 RANSAC outlier 제거       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 10. 경험적 검증이 필요한 항목 (Phase 1 과제)

1. **크로마 녹/청 페인트의 905 nm 실측 반사율 및 유효 거리**
2. **공식 SDK raw vs Python lib 노이즈 정량 비교**
3. **3~10 초 정적 스캔의 위치 재현성** (1 cm 달성 가능 여부)
4. **크레인 암의 self-occlusion 영향 범위 및 마스킹 전략**
5. **USB-CP2102N 현재 구성에서 Linux 최대 안정 샘플 레이트**

---

## 11. 참고 자료 (Sources)

### 로컬 사본 (본 저장소)

- [SLAMTEC RPLIDAR C1 Datasheet v1.0 (2023-10-13)](./sources/SLAMTEC_rplidar_datasheet_C1_v1.0_en.pdf) — **1차 출처**
- [SLAMTEC RPLIDAR S&C Series Protocol v2.8](./sources/SLAMTEC_rplidar_protocol_v2.8_en.pdf) — 패킷 레벨 레퍼런스

### 외부 링크

- [SLAMTEC RPLIDAR C1 Product Page](https://www.slamtec.com/en/c1)
- [SLAMTEC RPLIDAR FAQ (baud rate table 포함)](https://wiki.slamtec.com/display/SD/RPLIDAR+FAQ)
- [Slamtec/rplidar_sdk (GitHub, 공식 SDK)](https://github.com/Slamtec/rplidar_sdk)
- [RPLIDAR C1 Waveshare Wiki](https://www.waveshare.com/wiki/RPLIDAR_C1)
- [pyrplidar (Python 라이브러리)](https://github.com/Hyun-je/pyrplidar)
- [FastestRplidar (SWIG C++ wrapper)](https://github.com/thehapyone/FastestRplidar)
- [SLAMTEC LiDAR 라인업 비교 — Génération Robots](https://www.generationrobots.com/blog/en/slamtec-lidar-a-practical-comparison-for-easy-decision-making/)
