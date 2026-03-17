"""
Phase 1: Parse WBB game JSON files into a flat table of game-state snapshots.

For each completed game, walks the play-by-play and records a row at every
scoring play with the current margin, time remaining, and whether the trailing
team ultimately won.

Usage:
    python parse_games.py /path/to/wbb-game-data
    python parse_games.py /path/to/wbb-game-data --workers 8
"""

import argparse
import json
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path

import pandas as pd


def calc_seconds_remaining(period, clock_seconds, periods_regulation, ot_minutes=5, period_minutes=10):
    """Calculate total seconds remaining in the game from a given moment.

    For regulation periods, assumes periods_regulation total periods.
    For overtime, we don't know how many OT periods there will be, so we
    only count time left in the current OT period.
    """
    if period <= periods_regulation:
        # Regulation: remaining time in current period + full periods left
        remaining_full_periods = periods_regulation - period
        return remaining_full_periods * period_minutes * 60 + clock_seconds
    else:
        # Overtime: just count time left in this OT period
        # (we can't know if more OT periods will follow)
        return clock_seconds


def parse_game(filepath):
    """Parse a single game JSON file and return a list of game-state dicts."""
    filepath = Path(filepath)

    try:
        with open(filepath) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(data, dict):
        return []

    game = data.get("Game")
    if not game:
        return []

    if not game.get("IsComplete"):
        return []

    home_info = game.get("HomeTeam", {})
    away_info = game.get("VisitingTeam", {})

    home_final = home_info.get("Score")
    away_final = away_info.get("Score")
    if home_final is None or away_final is None:
        return []
    if home_final == away_final:
        # Tied final score — shouldn't happen but skip if it does
        return []

    home_won = home_final > away_final

    periods_regulation = game.get("PeriodsRegulation", 4)
    rules = game.get("Rules", {})
    period_minutes = rules.get("PeriodMinutes", 10)
    ot_minutes = rules.get("OTMinutes", 5)

    # Determine if overtime
    home_period_scores = home_info.get("PeriodScores", [])
    is_overtime = len(home_period_scores) > periods_regulation

    # Extract metadata from path: .../team-slug/season/game_id.json
    parts = filepath.parts
    game_id = filepath.stem
    season = parts[-2] if len(parts) >= 2 else "unknown"
    team_dir = parts[-3] if len(parts) >= 3 else "unknown"

    home_team = home_info.get("Id", "")
    home_name = home_info.get("Name", "")
    away_team = away_info.get("Id", "")
    away_name = away_info.get("Name", "")

    # Composite unique game identifier: season + game_id + both team IDs
    unique_game_id = f"{season}_{game_id}_{home_team}_{away_team}"

    plays = data.get("Plays", [])
    if not plays:
        return []

    rows = []
    current_home_score = 0
    current_away_score = 0

    for play in plays:
        score = play.get("Score")
        if not score:
            continue

        home_score = score.get("HomeTeam")
        away_score = score.get("VisitingTeam")
        if home_score is None or away_score is None:
            continue

        current_home_score = home_score
        current_away_score = away_score

        margin = current_home_score - current_away_score  # positive = home leads
        if margin == 0:
            # Tied — no trailing team, skip
            continue

        period = play.get("Period", 1)
        clock_seconds = play.get("ClockSeconds", 0)

        seconds_remaining = calc_seconds_remaining(
            period, clock_seconds, periods_regulation, ot_minutes, period_minutes
        )

        if margin > 0:
            trailing_team = "visitor"
            deficit = margin
            trailing_team_won = not home_won
        else:
            trailing_team = "home"
            deficit = -margin
            trailing_team_won = home_won

        rows.append({
            "unique_game_id": unique_game_id,
            "game_id": game_id,
            "season": season,
            "team_dir": team_dir,
            "home_team": home_team,
            "home_name": home_name,
            "away_team": away_team,
            "away_name": away_name,
            "period": period,
            "clock_seconds": clock_seconds,
            "seconds_remaining": seconds_remaining,
            "home_score": current_home_score,
            "away_score": current_away_score,
            "margin": margin,
            "deficit": deficit,
            "trailing_team": trailing_team,
            "trailing_team_won": trailing_team_won,
            "is_overtime": is_overtime,
            "home_final": home_final,
            "away_final": away_final,
        })

    # Validate: last PBP score should match game final scores.
    # If they're swapped or way off, the PBP data is unreliable for this game.
    if rows and current_home_score > 0 and current_away_score > 0:
        pbp_matches = (current_home_score == home_final and current_away_score == away_final)
        pbp_swapped = (current_home_score == away_final and current_away_score == home_final)
        if not pbp_matches and not pbp_swapped:
            # Allow small discrepancy (FTs after final buzzer etc.)
            home_close = abs(current_home_score - home_final) <= 3
            away_close = abs(current_away_score - away_final) <= 3
            if not (home_close and away_close):
                return []
        if pbp_swapped:
            # PBP home/away are flipped — skip this game as scores can't be trusted
            return []

    return rows


def find_game_files(data_dir):
    """Find all game JSON files in the data directory."""
    return list(Path(data_dir).glob("*/*/*.json"))


def main():
    parser = argparse.ArgumentParser(description="Parse WBB game files into game-state snapshots")
    parser.add_argument("data_dir", help="Path to wbb-game-data repository")
    parser.add_argument("--workers", type=int, default=cpu_count(),
                        help="Number of parallel workers (default: all CPUs)")
    parser.add_argument("--output", default="data/game_states.parquet",
                        help="Output file path (default: data/game_states.parquet)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit number of files to parse (0 = all, useful for testing)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Error: {data_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    print(f"Finding game files in {data_dir}...")
    files = find_game_files(data_dir)
    print(f"Found {len(files):,} game files")

    if args.limit > 0:
        files = files[:args.limit]
        print(f"Limited to {args.limit:,} files")

    print(f"Parsing with {args.workers} workers...")
    with Pool(args.workers) as pool:
        results = pool.map(parse_game, files, chunksize=200)

    # Flatten list of lists
    all_rows = []
    games_parsed = 0
    games_skipped = 0
    for rows in results:
        if rows:
            all_rows.extend(rows)
            games_parsed += 1
        else:
            games_skipped += 1

    print(f"Games parsed: {games_parsed:,}")
    print(f"Games skipped: {games_skipped:,}")
    print(f"Total game-state rows: {len(all_rows):,}")

    if not all_rows:
        print("No data extracted. Exiting.", file=sys.stderr)
        sys.exit(1)

    df = pd.DataFrame(all_rows)

    # Deduplicate: each game appears under both teams' directories.
    # Use unique_game_id (season + game_id + home + away) for proper dedup.
    before = len(df)
    df = df.drop_duplicates(subset=["unique_game_id", "period", "clock_seconds", "home_score", "away_score"])
    after = len(df)
    print(f"Deduplicated: {before:,} -> {after:,} rows ({before - after:,} duplicates removed)")

    # Sort by season, unique_game_id, then chronologically within game
    df = df.sort_values(["season", "unique_game_id", "period", "clock_seconds"],
                        ascending=[True, True, True, False])

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    print(f"Saved to {output_path} ({output_path.stat().st_size / 1024 / 1024:.1f} MB)")

    # Print summary stats
    print(f"\nSummary:")
    print(f"  Seasons: {df['season'].nunique()} ({df['season'].min()} to {df['season'].max()})")
    print(f"  Unique games: {df['unique_game_id'].nunique():,}")
    print(f"  Comeback win rate: {df['trailing_team_won'].mean():.1%}")
    print(f"  Overtime games: {df.loc[df['is_overtime'], 'unique_game_id'].nunique():,}")


if __name__ == "__main__":
    main()
