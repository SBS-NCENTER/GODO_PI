#!/usr/bin/env bash
# Regenerate the synthetic 4-metre-square test map.
#
# Output:
#   synthetic_4x4.pgm  — 80×80 cells, 8-bit P5, 0.05 m / cell
#   synthetic_4x4.yaml — slam_toolbox-shaped metadata
#
# Wall layout: 1-cell-thick border around the perimeter (occupied=0),
# everything inside is free (255). Origin is (0, 0) at the lower-left.
# This keeps the EDT correctness test deterministic — the closest obstacle
# from any interior cell is just min(x, y, W-1-x, H-1-y).

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WIDTH=80
HEIGHT=80
RES=0.05

python3 - <<EOF
import os
W, H = ${WIDTH}, ${HEIGHT}
data = bytearray()
for y in range(H):
    for x in range(W):
        if x == 0 or y == 0 or x == W - 1 or y == H - 1:
            data.append(0)        # occupied (border)
        else:
            data.append(255)      # free
header = f"P5\n{W} {H}\n255\n".encode("ascii")
with open(os.path.join("${DIR}", "synthetic_4x4.pgm"), "wb") as f:
    f.write(header)
    f.write(bytes(data))
EOF

cat >"${DIR}/synthetic_4x4.yaml" <<EOF
image: synthetic_4x4.pgm
resolution: ${RES}
origin: [0.0, 0.0, 0.0]
occupied_thresh: 0.65
free_thresh: 0.196
negate: 0
EOF

echo "Regenerated synthetic_4x4 fixture (${WIDTH}x${HEIGHT} @ ${RES} m/cell)."
