"""
Phase 2: Aggregate game-state snapshots into a comeback probability lookup table.

Bins data by deficit size and time remaining, computes comeback rates with
Wilson confidence intervals. Uses one observation per game per cell to ensure
statistical independence.

Usage:
    uv run python build_probability_table.py
    uv run python build_probability_table.py --input data/game_states.parquet --output data/comeback_probs.csv
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from utils import bin_deficit, bin_deficit_sort_key, time_bucket_label, time_bucket_sort_key


def wilson_ci(n_success, n_total, z=1.96):
    """Wilson score confidence interval for a binomial proportion."""
    if n_total == 0:
        return 0.0, 0.0
    p = n_success / n_total
    denom = 1 + z**2 / n_total
    center = (p + z**2 / (2 * n_total)) / denom
    spread = z * np.sqrt((p * (1 - p) + z**2 / (4 * n_total)) / n_total) / denom
    return max(0, center - spread), min(1, center + spread)


def main():
    parser = argparse.ArgumentParser(description="Build comeback probability table")
    parser.add_argument("--input", default="data/game_states.parquet",
                        help="Input parquet file from parse_games.py")
    parser.add_argument("--output", default="data/comeback_probs.csv",
                        help="Output CSV file")
    parser.add_argument("--min-sample", type=int, default=30,
                        help="Minimum unique games for a cell to be flagged adequate (default: 30)")
    args = parser.parse_args()

    print(f"Loading {args.input}...")
    df = pd.read_parquet(args.input)
    print(f"  {len(df):,} rows, {df['unique_game_id'].nunique():,} games")

    # Filter to regulation only (exclude OT snapshots where seconds_remaining
    # is just OT clock — not comparable to regulation time)
    if "periods_regulation" in df.columns:
        reg = df[df["period"] <= df["periods_regulation"]].copy()
    else:
        # Fallback for parquet files that predate the periods_regulation column
        reg = df[df["period"] <= 4].copy()
    print(f"  Regulation-only rows: {len(reg):,}")

    # Create bins
    reg["time_bucket"] = reg["seconds_remaining"].apply(time_bucket_label)
    reg["deficit_bucket"] = reg["deficit"].apply(bin_deficit)

    # --- Non-independence fix ---
    # Count raw observations (scoring plays) per cell for reference
    obs_count = (
        reg.groupby(["deficit_bucket", "time_bucket"])
        .agg(n_observations=("trailing_team_won", "count"))
        .reset_index()
    )

    # Deduplicate: one observation per game per (deficit_bucket, time_bucket) cell.
    # Within a single game and cell, trailing_team_won is the same for all plays
    # (it's determined by the game outcome, not the individual play).
    deduped = reg.drop_duplicates(subset=["unique_game_id", "deficit_bucket", "time_bucket"])
    print(f"  Deduped to {len(deduped):,} game-cell observations (from {len(reg):,} scoring plays)")

    # Aggregate on deduped data (independent observations)
    print("Aggregating...")
    agg = (
        deduped.groupby(["deficit_bucket", "time_bucket"])
        .agg(
            n_games=("trailing_team_won", "count"),
            n_wins=("trailing_team_won", "sum"),
        )
        .reset_index()
    )

    # Merge in raw observation counts
    agg = agg.merge(obs_count, on=["deficit_bucket", "time_bucket"], how="left")

    agg["trailing_team_win_pct"] = agg["n_wins"] / agg["n_games"]

    # Wilson confidence intervals (based on n_games, the independent sample)
    ci = agg.apply(
        lambda row: wilson_ci(row["n_wins"], row["n_games"]),
        axis=1,
        result_type="expand",
    )
    agg["ci_lower"] = ci[0]
    agg["ci_upper"] = ci[1]

    # Flag low sample sizes (based on unique games, not raw observations)
    agg["adequate_sample"] = agg["n_games"] >= args.min_sample

    # Sort for readability
    agg["_deficit_sort"] = agg["deficit_bucket"].apply(bin_deficit_sort_key)
    agg["_time_sort"] = agg["time_bucket"].apply(time_bucket_sort_key)
    agg = agg.sort_values(["_deficit_sort", "_time_sort"]).drop(columns=["_deficit_sort", "_time_sort"])

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
        .apply(lambda g: g["n_wins"].sum() / g["n_games"].sum())
        .reset_index(name="trailing_team_win_pct")
    )
    by_deficit["_sort"] = by_deficit["deficit_bucket"].apply(bin_deficit_sort_key)
    by_deficit = by_deficit.sort_values("_sort").drop(columns=["_sort"])
    print("\nTrailing team win rate by deficit size:")
    for _, row in by_deficit.iterrows():
        print(f"  {row['deficit_bucket']:>5} pts: {row['trailing_team_win_pct']:.1%}")

    # "Point of no return" — for each deficit, find the earliest time at which
    # the trailing team win rate drops below 5% and stays there
    print("\nPoint of no return (trailing team win rate < 5% sustained):")
    for deficit_label in sorted(agg["deficit_bucket"].unique(), key=bin_deficit_sort_key):
        subset = agg[
            (agg["deficit_bucket"] == deficit_label)
            & (agg["adequate_sample"])
        ].copy()
        subset = subset.sort_values(
            "time_bucket", key=lambda s: s.map(time_bucket_sort_key), ascending=False
        )

        # Walk from highest time bucket downward. Find the first bucket where
        # all buckets at this time or less are below 5%.
        point_of_no_return = None
        time_values = subset["time_bucket"].tolist()
        win_pcts = subset["trailing_team_win_pct"].tolist()

        for i, (tb, wp) in enumerate(zip(time_values, win_pcts)):
            # Check if all remaining buckets (this one and all with less time) are < 5%
            remaining_pcts = win_pcts[i:]
            if all(p < 0.05 for p in remaining_pcts):
                point_of_no_return = tb
                break

        if point_of_no_return is not None:
            print(f"  {deficit_label:>5} pts: {point_of_no_return} min remaining")
        else:
            print(f"  {deficit_label:>5} pts: never drops below 5% (with adequate sample)")


if __name__ == "__main__":
    main()
