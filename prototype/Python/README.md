# GODO Phase 1 — LiDAR Python prototype

Phase 1 work for the GODO LiDAR-based camera position tracker lives here.
Scope: **data capture + noise characterization + analysis**, per
[`SYSTEM_DESIGN.md §10`](../../SYSTEM_DESIGN.md).

```text
src/godo_lidar/
├─ frame.py             Sample / Frame dataclasses
├─ capture/
│   ├─ raw_parser.py    Pure bytes→Sample decoder (PDF v2.8 derived)
│   ├─ raw.py           RawBackend: pyserial + raw_parser
│   └─ sdk.py           SdkBackend: pyrplidar (unofficial C1 wrapper — baseline only)
├─ io/
│   ├─ csv_dump.py      stdlib csv.writer on the capture hot path
│   └─ session_log.py   per-run .txt log with csv_sha256 integrity hash
└─ analyze.py           load_csv / per_direction_variance / compare_backends /
                        reflector_histogram / polar_plot / quality_histogram
```

## Windows quickstart

### 1. Prerequisites

- **Python 3.12+**, **UV** (`pip install uv` or `winget install --id=astral-sh.uv -e`).
- **SLAMTEC CP2102 USB-serial driver.** The RPLIDAR C1 ships with a CP2102N
  USB bridge. If Windows does not enumerate the board after plug-in, grab
  the driver from SLAMTEC's download page and reinstall. Without the driver
  the C1 does not appear as a COM port at all.

### 2. First-run smoke check

```powershell
cd C:\Users\User\Desktop\GODO\Python
uv sync
uv run pytest
uv run python scripts/capture.py --help
uv run python scripts/analyze.py --help
```

`uv sync` installs all deps in `.venv/`. `uv run pytest` runs the protocol /
CSV / frame unit tests with no hardware. The `--help` calls only parse
argparse and do not touch the serial port.

### 3. Find the COM port

In PowerShell:

```powershell
Get-WmiObject Win32_SerialPort | Select-Object DeviceID,Description
```

Typical output: `COM7` with description containing `CP210x` or `USB-Enhanced-SERIAL CH9102`.

### 4. Port busy — close other apps first

Windows locks a serial port per-process. **Before running a capture, close
SLAMTEC RoboStudio, Arduino Serial Monitor, any other terminal tied to the
port**, and make sure no VSCode session is still attached.

### 5. Capture a session

```powershell
uv run python scripts/capture.py `
    --backend raw `
    --port COM7 `
    --frames 100 `
    --tag bench1 `
    --notes "static position A, empty room"
```

Swap `--backend raw` for `--backend sdk` to use the pyrplidar wrapper.
Outputs land in `data/` (CSV, one row per sample) and `logs/` (session `.txt`).
Both directories are gitignored.

**Motor speed (`--rpm`) is accepted only with `--backend raw`.** The C1's
`MOTOR_SPEED_CTRL` (cmd `0xA8`) is not exposed by pyrplidar; the SDK
backend leaves motor speed at the firmware default. Passing `--rpm` with
`--backend sdk` fails fast with a clear error.

### 6. Analyze

```powershell
uv run python scripts/analyze.py --mode noise --csv data\...csv --out out/
uv run python scripts/analyze.py --mode compare `
    --csv data\<sdk>.csv --other-csv data\<raw>.csv --out out/
uv run python scripts/analyze.py --mode visualize --csv data\...csv --out out/
```

## Backend selection: SDK-wrapper vs Non-SDK

See [`SYSTEM_DESIGN.md §10.1`](../../SYSTEM_DESIGN.md) for the full rationale.
Short version:

- `--backend sdk` (pyrplidar) — fast empirical baseline. **Unofficial for
  the C1** per [`RPLIDAR/RPLIDAR_C1.md §4`](../../doc/RPLIDAR/RPLIDAR_C1.md). Treat
  as a reference, not as ground truth.
- `--backend raw` — `pyserial` + in-house protocol parser
  (`capture/raw_parser.py`, derived directly from SLAMTEC protocol v2.8
  PDF). Every byte is ours; framing errors are visible in the logs.

A three-way comparison against the official C++ `rplidar_sdk`
`ultra_simple` CLI is a Phase 1 **follow-up task**.

## Troubleshooting

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `SerialException: could not open port 'COMn'` (raw backend) | Another app holds the port, or wrong port number | Close RoboStudio / Arduino IDE; re-run `Get-WmiObject Win32_SerialPort` |
| `ConnectionError: failed to open serial port ...` (sdk backend) | Same as above — port wrong or busy | pyrplidar silently swallows the serial failure (prints `Failed to connect to the rplidar`); SdkBackend now detects and raises. Same fix. |
| Capture starts but yields 0 frames | Motor not spinning up | Ensure 5 V supply has enough headroom (≥ 1 A); RPi USB may be underpowered on cold start |
| Many "bad check bit" warnings from `raw` backend | Baud mismatch or sync loss | Verify `--baud 460800`; try reducing `--rpm` |
| `pyrplidar` import error | C1 unsupported in older versions | Upgrade: `uv add "pyrplidar@latest"` |
