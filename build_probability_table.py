"""
Phase 2: Aggregate game-state snapshots into a comeback probability lookup table.

Bins data by deficit size and time remaining, computes comeback rates with
Wilson confidence intervals.

Usage:
    uv run python build_probability_table.py
    uv run python build_probability_table.py --input data/game_states.parquet --output data/comeback_probs.csv
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


def wilson_ci(n_success, n_total, z=1.96):
    """Wilson score confidence interval for a binomial proportion."""
    if n_total == 0:
        return 0.0, 0.0
    p = n_success / n_total
    denom = 1 + z**2 / n_total
    center = (p + z**2 / (2 * n_total)) / denom
    spread = z * np.sqrt((p * (1 - p) + z**2 / (4 * n_total)) / n_total) / denom
    return max(0, center - spread), min(1, center + spread)


def bin_deficit(deficit):
    """Assign deficit to a bucket label."""
    if deficit <= 10:
        return str(int(deficit))
    elif deficit <= 15:
        return "11-15"
    elif deficit <= 20:
        return "16-20"
    elif deficit <= 25:
        return "21-25"
    elif deficit <= 30:
        return "26-30"
    else:
        return "31+"


def bin_deficit_sort_key(label):
    """Sort key for deficit bucket labels."""
    if label.isdigit():
        return int(label)
    elif label == "31+":
        return 31
    else:
        return int(label.split("-")[0])


def main():
    parser = argparse.ArgumentParser(description="Build comeback probability table")
    parser.add_argument("--input", default="data/game_states.parquet",
                        help="Input parquet file from parse_games.py")
    parser.add_argument("--output", default="data/comeback_probs.csv",
                        help="Output CSV file")
    parser.add_argument("--min-sample", type=int, default=30,
                        help="Minimum observations for a cell to be included (default: 30)")
    args = parser.parse_args()

    print(f"Loading {args.input}...")
    df = pd.read_parquet(args.input)
    print(f"  {len(df):,} rows, {df['unique_game_id'].nunique():,} games")

    # Filter to regulation only (exclude OT snapshots where seconds_remaining
    # is just OT clock — not comparable to regulation time)
    reg = df[df["period"] <= 4].copy()
    print(f"  Regulation-only rows: {len(reg):,}")

    # Create bins
    reg["minutes_remaining"] = reg["seconds_remaining"] / 60.0
    reg["time_bucket"] = reg["minutes_remaining"].apply(lambda m: int(m))  # floor to integer minute
    # Cap at 39 (0-39 represents 0-1min through 39-40min)
    reg["time_bucket"] = reg["time_bucket"].clip(upper=39)

    reg["deficit_bucket"] = reg["deficit"].apply(bin_deficit)

    # Aggregate
    print("Aggregating...")
    agg = (
        reg.groupby(["deficit_bucket", "time_bucket"])
        .agg(
            n_observations=("trailing_team_won", "count"),
            n_comebacks=("trailing_team_won", "sum"),
        )
        .reset_index()
    )

    agg["comeback_pct"] = agg["n_comebacks"] / agg["n_observations"]

    # Wilson confidence intervals
    ci = agg.apply(
        lambda row: wilson_ci(row["n_comebacks"], row["n_observations"]),
        axis=1,
        result_type="expand",
    )
    agg["ci_lower"] = ci[0]
    agg["ci_upper"] = ci[1]

    # Flag low sample sizes
    agg["adequate_sample"] = agg["n_observations"] >= args.min_sample

    # Sort for readability
    agg["_deficit_sort"] = agg["deficit_bucket"].apply(bin_deficit_sort_key)
    agg = agg.sort_values(["_deficit_sort", "time_bucket"]).drop(columns=["_deficit_sort"])

    # Save
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    agg.to_csv(output_path, index=False)
    print(f"Saved {len(agg):,} cells to {output_path}")

    # Print some highlights
    print("\n--- Highlights ---")

    # Overall comeback rate by deficit bucket
    by_deficit = (
        agg.groupby("deficit_bucket")
        .apply(lambda g: g["n_comebacks"].sum() / g["n_observations"].sum())
        .reset_index(name="comeback_pct")
    )
    by_deficit["_sort"] = by_deficit["deficit_bucket"].apply(bin_deficit_sort_key)
    by_deficit = by_deficit.sort_values("_sort").drop(columns=["_sort"])
    print("\nComeback rate by deficit size:")
    for _, row in by_deficit.iterrows():
        print(f"  {row['deficit_bucket']:>5} pts: {row['comeback_pct']:.1%}")

    # "Point of no return" — for each deficit, latest time where comeback < 5%
    print("\nPoint of no return (comeback < 5%):")
    for deficit_label in sorted(agg["deficit_bucket"].unique(), key=bin_deficit_sort_key):
        subset = agg[
            (agg["deficit_bucket"] == deficit_label)
            & (agg["adequate_sample"])
            & (agg["comeback_pct"] < 0.05)
        ]
        if not subset.empty:
            max_time = subset["time_bucket"].max()
            print(f"  {deficit_label:>5} pts: {max_time} min remaining")
        else:
            print(f"  {deficit_label:>5} pts: never drops below 5% (with adequate sample)")


if __name__ == "__main__":
    main()
