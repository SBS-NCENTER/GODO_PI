"""Analyze script — loads captured CSVs and dumps stats / plots.

Modes map to SYSTEM_DESIGN.md §10.4 steps:

    --mode noise       : per-direction variance, √N table
    --mode compare     : SDK-wrapper vs Non-SDK per-bin delta (needs --other-csv)
    --mode reflector   : high-quality tail counts for reflector distinguishability
    --mode chroma_nir  : polar plot + quality histogram for chroma-wall surveys
    --mode visualize   : polar plot + quality histogram (generic)

Outputs go under `--out DIR` as PNG (plots) and CSV (stats).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from godo_lidar.analyze import (
    compare_backends,
    load_csv,
    per_direction_variance,
    polar_plot,
    quality_histogram,
    reflector_histogram,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze GODO LiDAR capture CSVs.",
    )
    parser.add_argument(
        "--mode",
        choices=("noise", "compare", "reflector", "chroma_nir", "visualize"),
        required=True,
    )
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument(
        "--other-csv",
        type=Path,
        default=None,
        help="Second CSV (required for --mode compare)",
    )
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument(
        "--min-quality",
        type=int,
        default=0,
        help="Drop samples with quality below this threshold",
    )
    parser.add_argument(
        "--bin-width-deg",
        type=float,
        default=1.0,
        help="Angular bin width for per-direction aggregation",
    )
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    df = load_csv(args.csv)

    if args.mode == "noise":
        stats = per_direction_variance(
            df,
            bin_width_deg=args.bin_width_deg,
            min_quality=args.min_quality,
        )
        out_csv = args.out / f"{args.csv.stem}_noise.csv"
        stats.to_csv(out_csv)
        print(f"wrote {out_csv}")
        print(
            "summary: mean std_mm = "
            f"{stats['std_mm'].mean():.2f}, "
            f"mean sqrt_n_bound = {stats['sqrt_n_bound'].mean():.2f} mm"
        )
        return 0

    if args.mode == "compare":
        if args.other_csv is None:
            parser.error("--mode compare requires --other-csv")
        other = load_csv(args.other_csv)
        cmp_df = compare_backends(
            df,
            other,
            bin_width_deg=args.bin_width_deg,
            min_quality=args.min_quality,
        )
        out_csv = (
            args.out / f"{args.csv.stem}__vs__{args.other_csv.stem}.csv"
        )
        cmp_df.to_csv(out_csv)
        print(f"wrote {out_csv}")
        print(
            "summary: mean |delta_mean_mm| = "
            f"{cmp_df['delta_mean_mm'].abs().mean():.2f} mm, "
            f"mean delta_median_q = "
            f"{cmp_df['delta_median_q'].mean():.2f}"
        )
        return 0

    if args.mode == "reflector":
        counts, edges = reflector_histogram(df)
        hist = pd.DataFrame(
            {
                "bin_low": edges[:-1],
                "bin_high": edges[1:],
                "count": counts,
            }
        )
        out_csv = args.out / f"{args.csv.stem}_qhist.csv"
        hist.to_csv(out_csv, index=False)
        high_q = int(np.sum(counts[edges[:-1] >= 200]))
        low_q = int(np.sum(counts[edges[1:] <= 100]))
        print(f"wrote {out_csv}")
        print(f"samples >= 200 quality: {high_q}")
        print(f"samples <= 100 quality: {low_q}")
        return 0

    if args.mode in ("chroma_nir", "visualize"):
        polar = polar_plot(df, min_quality=args.min_quality)
        polar_path = args.out / f"{args.csv.stem}_polar.png"
        polar.savefig(polar_path, dpi=150)
        qhist = quality_histogram(df)
        qhist_path = args.out / f"{args.csv.stem}_qhist.png"
        qhist.savefig(qhist_path, dpi=150)
        print(f"wrote {polar_path}")
        print(f"wrote {qhist_path}")
        return 0

    raise AssertionError(f"unreachable mode {args.mode!r}")


if __name__ == "__main__":
    raise SystemExit(main())
