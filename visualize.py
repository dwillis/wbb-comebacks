"""
Phase 3: Visualize comeback probability data.

Produces:
  1. Heatmap: deficit vs time remaining, colored by trailing team win probability
  2. Win probability curves: selected deficits over elapsed game time
  3. Greatest comebacks list ranked by improbability
  4. Single-game win probability chart for the most improbable comeback

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

from utils import (
    bin_deficit,
    bin_deficit_sort_key,
    time_bucket_label,
    time_bucket_sort_key,
)


def _make_single_heatmap(ax, pivot, title):
    """Render a single heatmap onto the given axes."""
    landmarks = [0.05, 0.10, 0.25, 0.50]
    annot_array = pd.DataFrame("", index=pivot.index, columns=pivot.columns)
    for r in range(pivot.shape[0]):
        for c in range(pivot.shape[1]):
            val = pivot.iloc[r, c]
            if pd.notna(val) and any(abs(val - lm) < 0.02 for lm in landmarks):
                annot_array.iloc[r, c] = f"{val:.0%}"

    sns.heatmap(
        pivot,
        cmap="RdYlGn",
        vmin=0,
        vmax=0.5,
        annot=annot_array,
        fmt="s",
        linewidths=0.5,
        linecolor="white",
        cbar_kws={"label": "Trailing Team Win Probability", "format": mticker.PercentFormatter(1.0)},
        ax=ax,
        annot_kws={"size": 6, "fontweight": "bold"},
    )
    ax.set_xlabel("Minutes Left in Game", fontsize=10)
    ax.set_ylabel("Point Deficit", fontsize=10)
    ax.set_title(title, fontsize=11, fontweight="bold")


def make_heatmap(probs_df, output_dir):
    """Create side-by-side heatmaps: trailing team at home vs. away."""
    df = probs_df[probs_df["adequate_sample"]].copy()

    fig, axes = plt.subplots(1, 2, figsize=(28, 10))

    for ax, venue, label in zip(axes, ["home", "away"], ["Trailing Team at Home", "Trailing Team on the Road"]):
        venue_df = df[df["venue"] == venue]
        pivot = venue_df.pivot_table(
            index="deficit_bucket",
            columns="time_bucket",
            values="trailing_team_win_pct",
            aggfunc="first",
        )

        sorted_idx = sorted(pivot.index, key=bin_deficit_sort_key)
        pivot = pivot.loc[sorted_idx]
        sorted_cols = sorted(pivot.columns, key=time_bucket_sort_key, reverse=True)
        pivot = pivot[sorted_cols]

        _make_single_heatmap(ax, pivot, label)

    fig.suptitle(
        "NCAA Women's Basketball: Trailing Team Win Probability\n"
        "By deficit, time remaining, and venue — 288K games, 2001–2026",
        fontsize=14,
        fontweight="bold",
        y=1.02,
    )

    plt.tight_layout()
    out = output_dir / "comeback_heatmap.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out}")


def make_win_prob_curves(probs_df, output_dir):
    """Line chart: trailing team win probability vs elapsed game time, home vs away."""
    df = probs_df[(probs_df["adequate_sample"]) & (probs_df["n_games"] >= 30)].copy()

    selected_deficits = ["5", "10", "11-15", "16-20", "21-25"]
    colors = ["#2ecc71", "#f39c12", "#e74c3c", "#9b59b6", "#34495e"]

    fig, ax = plt.subplots(figsize=(14, 8))

    for deficit_label, color in zip(selected_deficits, colors):
        for venue, linestyle, alpha in [("home", "-", 1.0), ("away", "--", 0.7)]:
            subset = df[(df["deficit_bucket"] == deficit_label) & (df["venue"] == venue)].copy()
            if subset.empty:
                continue

            subset["minutes_remaining"] = subset["time_bucket"].apply(time_bucket_sort_key)
            subset = subset.sort_values("minutes_remaining")
            subset["minutes_elapsed"] = 40 - subset["minutes_remaining"]

            # Only label once per deficit (home line gets the label)
            label = f"{deficit_label} pts" if venue == "home" else None
            ax.plot(
                subset["minutes_elapsed"],
                subset["trailing_team_win_pct"],
                label=label,
                color=color,
                linewidth=2,
                linestyle=linestyle,
                alpha=alpha,
            )

    # Add a legend entry explaining line styles
    ax.plot([], [], color="gray", linestyle="-", linewidth=2, label="Home (trailing)")
    ax.plot([], [], color="gray", linestyle="--", linewidth=2, alpha=0.7, label="Away (trailing)")

    ax.set_xlabel("Minutes Elapsed", fontsize=12)
    ax.set_ylabel("Trailing Team Win Probability", fontsize=12)
    ax.set_title(
        "Trailing Team Win Probability by Elapsed Game Time\n"
        "Selected deficit sizes — solid = home, dashed = away",
        fontsize=14,
        fontweight="bold",
    )
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.set_xlim(0, 40)
    ax.set_ylim(0, 0.6)
    ax.axhline(y=0.05, color="gray", linestyle=":", alpha=0.5, label="5% threshold")
    ax.legend(fontsize=10, ncol=2)
    ax.grid(alpha=0.3)

    plt.tight_layout()
    out = output_dir / "win_prob_curves.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out}")


def find_greatest_comebacks(game_states_path, probs_df, output_dir, top_n=25):
    """Find the most improbable comebacks, ranked by lowest win probability at worst moment."""
    print("Loading game states for greatest comebacks analysis...")
    df = pd.read_parquet(game_states_path)

    # Only games where the trailing team won
    comebacks = df[df["trailing_team_won"]].copy()

    # Only regulation periods
    if "periods_regulation" in comebacks.columns:
        comebacks = comebacks[comebacks["period"] <= comebacks["periods_regulation"]]
    else:
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

    # Find the time remaining when at max deficit
    def get_worst_moment_details(group):
        worst = group.loc[group["deficit"].idxmax()]
        return pd.Series({
            "max_deficit_seconds_remaining": worst["seconds_remaining"],
            "max_deficit_period": worst["period"],
            "trailing_team_at_worst": worst["trailing_team"],
        })

    details = comebacks.groupby("unique_game_id").apply(get_worst_moment_details).reset_index()
    worst_moments = worst_moments.merge(details, on="unique_game_id")

    # Compute the deficit_bucket, time_bucket, and venue at the worst moment,
    # then look up trailing_team_win_pct from the probability table
    worst_moments["deficit_bucket"] = worst_moments["max_deficit"].apply(bin_deficit)
    worst_moments["time_bucket"] = worst_moments["max_deficit_seconds_remaining"].apply(time_bucket_label)
    worst_moments["venue"] = worst_moments["trailing_team_at_worst"].map({"home": "home", "visitor": "away"})

    # Join against probability table (venue-aware)
    prob_lookup = probs_df[["deficit_bucket", "time_bucket", "venue", "trailing_team_win_pct"]].copy()
    worst_moments = worst_moments.merge(
        prob_lookup,
        on=["deficit_bucket", "time_bucket", "venue"],
        how="left",
    )
    worst_moments.rename(columns={"trailing_team_win_pct": "worst_probability"}, inplace=True)

    # Fill NaN probabilities (cells without adequate sample) with 0
    worst_moments["worst_probability"] = worst_moments["worst_probability"].fillna(0.0)

    # Rank by lowest probability (most improbable comeback first)
    worst_moments = worst_moments.sort_values("worst_probability", ascending=True)

    # Deduplicate: same game may appear under multiple team directories.
    # Use final scores + deficit + time as the key since team names can have
    # slightly different spellings across directories.
    worst_moments = worst_moments.drop_duplicates(
        subset=["season", "home_final", "away_final", "max_deficit",
                "max_deficit_seconds_remaining"]
    )

    # Determine the winning/losing team names
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
    # Whether the comeback team was playing at home or away
    worst_moments["comeback_at"] = worst_moments["trailing_team_at_worst"].map({"home": "home", "visitor": "away"})

    top = worst_moments.head(top_n)

    out_csv = output_dir / "greatest_comebacks.csv"
    top[["unique_game_id", "season", "winner", "loser", "home_final", "away_final",
         "max_deficit", "max_deficit_min_remaining", "max_deficit_period",
         "comeback_at", "worst_probability"]].to_csv(out_csv, index=False)
    print(f"Saved top {top_n} comebacks to {out_csv}")

    # Print top 10
    print(f"\nTop 10 Most Improbable Comebacks:")
    for i, (_, row) in enumerate(top.head(10).iterrows(), 1):
        mins = row["max_deficit_min_remaining"]
        prob = row["worst_probability"]
        venue_tag = "H" if row["comeback_at"] == "home" else "A"
        print(
            f"  {i:2d}. {row['winner']} [{venue_tag}] overcame {int(row['max_deficit'])}-pt deficit "
            f"({mins:.1f} min left, {prob:.1%} win prob) to beat {row['loser']} "
            f"{int(row['home_final'])}-{int(row['away_final'])} ({row['season']})"
        )

    return worst_moments


def make_single_game_chart(game_states_path, probs_df, output_dir, game_id):
    """Plot win probability over game time for a single game."""
    print(f"Creating single-game chart for {game_id}...")
    df = pd.read_parquet(game_states_path)

    game = df[df["unique_game_id"] == game_id].copy()
    if game.empty:
        print(f"  Warning: game {game_id} not found in game states")
        return

    # Sort chronologically (ascending period, descending clock within period)
    game = game.sort_values(["period", "clock_seconds"], ascending=[True, False])

    # Determine which team we're tracking (the winner)
    home_final = game["home_final"].iloc[0]
    away_final = game["away_final"].iloc[0]
    home_name = game["home_name"].iloc[0]
    away_name = game["away_name"].iloc[0]
    home_won = home_final > away_final
    winner_name = home_name if home_won else away_name
    loser_name = away_name if home_won else home_name

    # Build probability lookup dict from probs_df (venue-aware)
    prob_lookup = {}
    for _, row in probs_df.iterrows():
        prob_lookup[(row["deficit_bucket"], row["time_bucket"], row["venue"])] = row["trailing_team_win_pct"]

    # For each scoring play, compute the winner's win probability
    elapsed_times = []
    win_probs = []

    # Determine regulation periods for this game
    if "periods_regulation" in game.columns:
        periods_reg = game["periods_regulation"].iloc[0]
    else:
        periods_reg = 4
    total_reg_minutes = periods_reg * 10  # usually 40

    for _, play in game.iterrows():
        margin = play["home_score"] - play["away_score"]
        seconds_rem = play["seconds_remaining"]
        period = play["period"]

        # Elapsed time in minutes
        if period <= periods_reg:
            elapsed = (total_reg_minutes * 60 - seconds_rem) / 60.0
        else:
            # Overtime: place after regulation
            elapsed = total_reg_minutes + (play["period"] - periods_reg - 1) * 5 + (5 * 60 - play["clock_seconds"]) / 60.0

        if margin == 0:
            # Tied
            win_prob = 0.50
        else:
            deficit = abs(margin)
            deficit_bucket = bin_deficit(deficit)
            time_bucket = time_bucket_label(seconds_rem)
            # Determine venue for the trailing team
            venue = "home" if margin < 0 else "away"
            lookup_prob = prob_lookup.get((deficit_bucket, time_bucket, venue))

            if lookup_prob is None:
                lookup_prob = 0.0  # extreme deficit, no data

            if home_won:
                # We track the home team (the winner)
                if margin > 0:
                    # Home leads → win prob = 1 - trailing team's win prob
                    win_prob = 1.0 - lookup_prob
                else:
                    # Home trails → win prob = trailing team's win prob
                    win_prob = lookup_prob
            else:
                # We track the away team (the winner)
                if margin < 0:
                    # Away leads (margin negative means away ahead) → win prob = 1 - trailing team's prob
                    win_prob = 1.0 - lookup_prob
                else:
                    # Away trails → win prob = trailing team's prob
                    win_prob = lookup_prob

        elapsed_times.append(elapsed)
        win_probs.append(win_prob)

    fig, ax = plt.subplots(figsize=(14, 6))

    ax.plot(elapsed_times, win_probs, color="#2c3e50", linewidth=1.5, alpha=0.8)
    ax.axhline(y=0.5, color="gray", linestyle="-", alpha=0.3)
    ax.axhline(y=0.05, color="red", linestyle="--", alpha=0.3, label="5% threshold")

    # Find and annotate the worst moment
    min_prob_idx = np.argmin(win_probs)
    ax.annotate(
        f"  {win_probs[min_prob_idx]:.1%}",
        xy=(elapsed_times[min_prob_idx], win_probs[min_prob_idx]),
        fontsize=10,
        fontweight="bold",
        color="#e74c3c",
    )
    ax.plot(elapsed_times[min_prob_idx], win_probs[min_prob_idx],
            "o", color="#e74c3c", markersize=8)

    max_deficit = game["deficit"].max()
    season = game["season"].iloc[0]

    ax.set_xlabel("Minutes Elapsed", fontsize=12)
    ax.set_ylabel(f"{winner_name} Win Probability", fontsize=12)
    ax.set_title(
        f"{winner_name} vs {loser_name} ({season})\n"
        f"Overcame {int(max_deficit)}-point deficit — "
        f"Final: {int(home_final)}-{int(away_final)}",
        fontsize=14,
        fontweight="bold",
    )
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.set_ylim(0, 1.0)
    ax.set_xlim(0, max(elapsed_times) + 1)
    ax.legend(fontsize=10)
    ax.grid(alpha=0.3)

    plt.tight_layout()
    out = output_dir / "single_game_win_prob.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out}")


def main():
    parser = argparse.ArgumentParser(description="Visualize comeback probability data")
    parser.add_argument("--probs", default="data/comeback_probs.csv",
                        help="Probability table CSV from build_probability_table.py")
    parser.add_argument("--game-states", default="data/game_states.parquet",
                        help="Game states parquet from parse_games.py")
    parser.add_argument("--output-dir", default="output",
                        help="Output directory for charts")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    probs_df = pd.read_csv(args.probs)
    print(f"Loaded {len(probs_df)} probability cells")

    make_heatmap(probs_df, output_dir)
    make_win_prob_curves(probs_df, output_dir)
    worst_moments = find_greatest_comebacks(args.game_states, probs_df, output_dir)

    # Single-game chart for the most improbable comeback
    if not worst_moments.empty:
        top_game_id = worst_moments.iloc[0]["unique_game_id"]
        make_single_game_chart(args.game_states, probs_df, output_dir, top_game_id)


if __name__ == "__main__":
    main()
