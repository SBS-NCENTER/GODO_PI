"""Post-hoc analysis of captured CSV dumps.

Everything here runs off disk; pandas / numpy are OK on this path (unlike
the capture path, which is stdlib-only per SYSTEM_DESIGN.md §10.2).

Functions are grouped by the Phase 1 test sequence in §10.4:

    Step 1 — backend parity:   :func:`compare_backends`
    Step 2 — noise:            :func:`per_direction_variance`
    Step 3 — reflector:        :func:`reflector_histogram`
    Step 4 — chroma / visual:  :func:`polar_plot`, :func:`quality_histogram`
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from godo_lidar.io.csv_dump import COLUMNS

# Per SYSTEM_DESIGN.md §10.4 Step 3, 1° bins. Coarser bins mask the 0.72°
# angular resolution of the C1.
DEFAULT_BIN_WIDTH_DEG: Final[float] = 1.0


def load_csv(path: Path) -> pd.DataFrame:
    """Load a capture CSV. Columns are pinned to :mod:`godo_lidar.io.csv_dump`.

    Quality filtering is NOT applied here — every caller decides its own
    threshold (e.g. §10.4 Step 3 uses quality ≥ 200, Step 2 uses no filter).
    """
    df = pd.read_csv(path)
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"CSV {path} missing columns: {sorted(missing)}")
    return df


def per_direction_variance(
    df: pd.DataFrame,
    *,
    bin_width_deg: float = DEFAULT_BIN_WIDTH_DEG,
    min_quality: int = 0,
    min_samples_per_bin: int = 5,
) -> pd.DataFrame:
    """Compute per-angle-bin variance of `distance_mm`.

    Returns a DataFrame indexed by bin lower-edge (degrees) with columns:

        n            — sample count in the bin
        mean_mm      — mean distance
        std_mm       — sample stddev of distance
        median_q     — median quality
        sqrt_n_bound — predicted stddev of the bin mean: std_mm / sqrt(n).

    §10.4 Step 2 uses this to verify the √N rule: aggregating N scans should
    reduce variance by √N.
    """
    if bin_width_deg <= 0:
        raise ValueError(f"bin_width_deg must be > 0; got {bin_width_deg!r}")

    f = df[df["quality"] >= min_quality].copy()
    f["bin"] = (f["angle_deg"] // bin_width_deg) * bin_width_deg

    agg = f.groupby("bin").agg(
        n=("distance_mm", "size"),
        mean_mm=("distance_mm", "mean"),
        std_mm=("distance_mm", "std"),
        median_q=("quality", "median"),
    )
    agg = agg[agg["n"] >= min_samples_per_bin].copy()
    # std / sqrt(n) is the 1-sigma bound on the bin mean for white noise.
    agg["sqrt_n_bound"] = agg["std_mm"] / np.sqrt(agg["n"])
    return agg


def compare_backends(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    *,
    bin_width_deg: float = DEFAULT_BIN_WIDTH_DEG,
    min_quality: int = 0,
) -> pd.DataFrame:
    """Per-bin distance and quality delta between two backend dumps.

    §10.4 Step 1 — expected to reveal cases where the SDK wrapper silently
    filters by quality (RPLIDAR_C1.md §5 cause 1) while the raw parser does
    not.
    """
    a = per_direction_variance(
        df_a, bin_width_deg=bin_width_deg, min_quality=min_quality
    )
    b = per_direction_variance(
        df_b, bin_width_deg=bin_width_deg, min_quality=min_quality
    )
    joined = a.join(b, lsuffix="_a", rsuffix="_b", how="inner")
    joined["delta_mean_mm"] = joined["mean_mm_a"] - joined["mean_mm_b"]
    joined["delta_median_q"] = joined["median_q_a"] - joined["median_q_b"]
    return joined


def reflector_histogram(
    df: pd.DataFrame,
    *,
    quality_bins: int = 64,
) -> tuple[np.ndarray, np.ndarray]:
    """Quality histogram — high tail indicates retro-reflective returns.

    Returns (counts, bin_edges). §10.4 Step 3 threshold target: reflector
    samples ≥ 200 quality, background ≤ 100.
    """
    if quality_bins < 2:
        raise ValueError(f"quality_bins must be >= 2; got {quality_bins!r}")
    counts, edges = np.histogram(
        df["quality"].to_numpy(),
        bins=quality_bins,
        range=(0, 256),
    )
    return counts, edges


def quality_histogram(df: pd.DataFrame) -> Figure:
    """Matplotlib figure: quality histogram for a quick visual check."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 4))
    counts, edges = reflector_histogram(df)
    ax.bar(edges[:-1], counts, width=edges[1] - edges[0], align="edge")
    ax.set_xlabel("quality")
    ax.set_ylabel("sample count")
    ax.set_title("Quality distribution")
    fig.tight_layout()
    return fig


def polar_plot(
    df: pd.DataFrame,
    *,
    max_range_mm: float = 12_000.0,
    min_quality: int = 0,
) -> Figure:
    """Polar scatter of (angle, distance). §10.4 Step 4 visual baseline.

    Samples outside [1, max_range_mm] are dropped (0 means "invalid",
    PDF Figure 4-5).
    """
    import matplotlib.pyplot as plt

    f = df[
        (df["quality"] >= min_quality)
        & (df["distance_mm"] > 0)
        & (df["distance_mm"] <= max_range_mm)
    ]
    theta = np.deg2rad(f["angle_deg"].to_numpy())
    r = f["distance_mm"].to_numpy()
    q = f["quality"].to_numpy()

    fig = plt.figure(figsize=(6, 6))
    ax = fig.add_subplot(111, projection="polar")
    sc = ax.scatter(theta, r, c=q, s=2, cmap="viridis", vmin=0, vmax=255)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)  # clockwise, per RPLIDAR_C1.md §3
    ax.set_rmax(max_range_mm)
    fig.colorbar(sc, ax=ax, label="quality", pad=0.1)
    ax.set_title("LiDAR polar scan")
    fig.tight_layout()
    return fig
