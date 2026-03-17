"""
Phase 3: Visualize comeback probability data.

Produces:
  1. Heatmap: deficit vs time remaining, colored by comeback probability
  2. Win probability curves: selected deficits over time
  3. (Bonus) Single-game win probability chart for the most improbable comeback

Usage:
    uv run python visualize.py
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns


def deficit_sort_key(label):
    if label.isdigit():
        return int(label)
    elif label == "31+":
        return 31
    else:
        return int(label.split("-")[0])


def make_heatmap(probs_df, output_dir, min_sample=30):
    """Create the primary heatmap: comeback probability by deficit and time remaining."""
    # Filter to adequate samples
    df = probs_df[probs_df["adequate_sample"]].copy()

    # Pivot for heatmap
    pivot = df.pivot_table(
        index="deficit_bucket",
        columns="time_bucket",
        values="comeback_pct",
        aggfunc="first",
    )

    # Sort rows by deficit
    sorted_idx = sorted(pivot.index, key=deficit_sort_key)
    pivot = pivot.loc[sorted_idx]

    # Sort columns (time remaining) descending: 39 -> 0
    pivot = pivot[sorted(pivot.columns, reverse=True)]

    # Rename columns to be more readable
    pivot.columns = [f"{c}" for c in pivot.columns]

    fig, ax = plt.subplots(figsize=(20, 10))
    sns.heatmap(
        pivot,
        cmap="RdYlGn",
        vmin=0,
        vmax=0.5,
        annot=True,
        fmt=".0%",
        linewidths=0.5,
        linecolor="white",
        cbar_kws={"label": "Comeback Win Probability", "format": mticker.PercentFormatter(1.0)},
        ax=ax,
        annot_kws={"size": 7},
    )

    ax.set_xlabel("Minutes Remaining (bucket floor)", fontsize=12)
    ax.set_ylabel("Point Deficit", fontsize=12)
    ax.set_title(
        "NCAA Women's Basketball: Comeback Probability\n"
        "P(trailing team wins) by deficit and time remaining — 288K games, 2001–2026",
        fontsize=14,
        fontweight="bold",
    )

    plt.tight_layout()
    out = output_dir / "comeback_heatmap.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out}")


def make_win_prob_curves(probs_df, output_dir, min_sample=30):
    """Line chart: comeback probability vs time for selected deficits."""
    df = probs_df[probs_df["adequate_sample"]].copy()

    selected_deficits = ["5", "10", "11-15", "16-20", "21-25"]
    colors = ["#2ecc71", "#f39c12", "#e74c3c", "#9b59b6", "#34495e"]

    fig, ax = plt.subplots(figsize=(14, 8))

    for deficit_label, color in zip(selected_deficits, colors):
        subset = df[df["deficit_bucket"] == deficit_label].sort_values("time_bucket")
        if subset.empty:
            continue

        ax.plot(
            subset["time_bucket"],
            subset["comeback_pct"],
            label=f"{deficit_label} pts",
            color=color,
            linewidth=2,
        )
        ax.fill_between(
            subset["time_bucket"],
            subset["ci_lower"],
            subset["ci_upper"],
            alpha=0.15,
            color=color,
        )

    ax.set_xlabel("Minutes Remaining", fontsize=12)
    ax.set_ylabel("Comeback Win Probability", fontsize=12)
    ax.set_title(
        "Comeback Probability by Time Remaining\n"
        "Selected deficit sizes — 95% Wilson CI bands",
        fontsize=14,
        fontweight="bold",
    )
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.set_xlim(40, 0)  # Time goes right to left
    ax.set_ylim(0, 0.6)
    ax.axhline(y=0.05, color="gray", linestyle="--", alpha=0.5, label="5% threshold")
    ax.legend(fontsize=11)
    ax.grid(alpha=0.3)

    plt.tight_layout()
    out = output_dir / "win_prob_curves.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out}")


def find_greatest_comebacks(game_states_path, probs_df, output_dir, top_n=25):
    """Find and chart the most improbable comebacks."""
    print("Loading game states for greatest comebacks analysis...")
    df = pd.read_parquet(game_states_path)

    # Only games where the trailing team won
    comebacks = df[df["trailing_team_won"]].copy()

    # Only regulation periods
    comebacks = comebacks[comebacks["period"] <= 4]

    # For each game, find the maximum deficit the winning team faced
    worst_moments = (
        comebacks.groupby("unique_game_id")
        .agg(
            max_deficit=("deficit", "max"),
            season=("season", "first"),
            home_name=("home_name", "first"),
            away_name=("away_name", "first"),
            home_final=("home_final", "first"),
            away_final=("away_final", "first"),
        )
        .reset_index()
    )

    # Also find the time remaining when at max deficit
    def get_worst_moment_details(group):
        worst = group.loc[group["deficit"].idxmax()]
        return pd.Series({
            "max_deficit_seconds_remaining": worst["seconds_remaining"],
            "max_deficit_period": worst["period"],
            "trailing_team_at_worst": worst["trailing_team"],
        })

    details = comebacks.groupby("unique_game_id").apply(get_worst_moment_details).reset_index()
    worst_moments = worst_moments.merge(details, on="unique_game_id")

    # Sort by largest deficit
    worst_moments = worst_moments.sort_values("max_deficit", ascending=False)

    # Deduplicate: same game may appear under multiple team directories with
    # slightly different unique_game_id. Dedup by (season, home_name, away_name, home_final, away_final).
    worst_moments = worst_moments.drop_duplicates(
        subset=["season", "home_name", "away_name", "home_final", "away_final"]
    )

    # Determine the winning team name
    def winner_name(row):
        if row["home_final"] > row["away_final"]:
            return row["home_name"]
        return row["away_name"]

    def loser_name(row):
        if row["home_final"] > row["away_final"]:
            return row["away_name"]
        return row["home_name"]

    worst_moments["winner"] = worst_moments.apply(winner_name, axis=1)
    worst_moments["loser"] = worst_moments.apply(loser_name, axis=1)
    worst_moments["max_deficit_min_remaining"] = worst_moments["max_deficit_seconds_remaining"] / 60.0

    top = worst_moments.head(top_n)

    out_csv = output_dir / "greatest_comebacks.csv"
    top[["unique_game_id", "season", "winner", "loser", "home_final", "away_final",
         "max_deficit", "max_deficit_min_remaining", "max_deficit_period"]].to_csv(out_csv, index=False)
    print(f"Saved top {top_n} comebacks to {out_csv}")

    # Print top 10
    print(f"\nTop 10 Greatest Comebacks (by max deficit overcome):")
    for i, (_, row) in enumerate(top.head(10).iterrows(), 1):
        mins = row["max_deficit_min_remaining"]
        print(
            f"  {i:2d}. {row['winner']} overcame {int(row['max_deficit'])}-pt deficit "
            f"({mins:.1f} min left) to beat {row['loser']} "
            f"{int(row['home_final'])}-{int(row['away_final'])} ({row['season']})"
        )

    return worst_moments


def main():
    parser = argparse.ArgumentParser(description="Visualize comeback probability data")
    parser.add_argument("--probs", default="data/comeback_probs.csv",
                        help="Probability table CSV from build_probability_table.py")
    parser.add_argument("--game-states", default="data/game_states.parquet",
                        help="Game states parquet from parse_games.py")
    parser.add_argument("--output-dir", default="output",
                        help="Output directory for charts")
    parser.add_argument("--min-sample", type=int, default=30,
                        help="Minimum observations for inclusion")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    probs_df = pd.read_csv(args.probs)
    print(f"Loaded {len(probs_df)} probability cells")

    make_heatmap(probs_df, output_dir, args.min_sample)
    make_win_prob_curves(probs_df, output_dir, args.min_sample)
    find_greatest_comebacks(args.game_states, probs_df, output_dir)


if __name__ == "__main__":
    main()
