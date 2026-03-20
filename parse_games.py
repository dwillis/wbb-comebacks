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
from functools import partial
from multiprocessing import Pool, cpu_count
from pathlib import Path

import pandas as pd


POWER_4_CONFERENCES = {"ACC", "Big 12", "Big Ten", "SEC"}


def load_d1_teams(teams_json_path="data/teams.json"):
    """Load Division I team data from teams.json.

    Returns:
        d1_ncaa_ids: set of NCAA IDs for D-I teams
        ncaa_id_to_conference: dict mapping NCAA ID -> conference name
    """
    with open(teams_json_path) as f:
        teams = json.load(f)
    d1 = [t for t in teams if t.get("division") == "I"]
    d1_ncaa_ids = {t["ncaa_id"] for t in d1}
    ncaa_id_to_conference = {t["ncaa_id"]: t.get("conference", "") for t in d1}
    return d1_ncaa_ids, ncaa_id_to_conference


def build_d1_team_info(data_dir, d1_ncaa_ids, ncaa_id_to_conference):
    """Build mappings from string team IDs (e.g. 'UA') to D-I team info.

    For each D-I directory, scans all game files and identifies the string ID
    that appears in every game (as home or away) — that's the directory's team.

    Returns:
        d1_string_ids: set of string IDs belonging to D-I teams
        string_id_to_conference: dict mapping string ID -> conference name
    """
    from collections import Counter

    d1_string_ids = set()
    string_id_to_conference = {}
    data_dir = Path(data_dir)

    for team_dir in data_dir.iterdir():
        if not team_dir.is_dir():
            continue
        ncaa_id = ncaa_id_from_dir(team_dir.name)
        if ncaa_id not in d1_ncaa_ids:
            continue

        game_files = list(team_dir.glob("*/*.json"))
        if not game_files:
            continue

        # Count how often each string ID appears across all games in this dir
        id_counter = Counter()
        total = 0
        for gf in game_files:
            try:
                data = json.load(open(gf))
                if not isinstance(data, dict):
                    continue
                g = data.get("Game", {})
                for side in ("HomeTeam", "VisitingTeam"):
                    tid = g.get(side, {}).get("Id", "")
                    if tid:
                        id_counter[tid] += 1
                total += 1
            except (json.JSONDecodeError, OSError):
                pass

        if total == 0 or not id_counter:
            continue

        # The directory's team appears in every game; pick the ID with count == total
        team_ids = [tid for tid, c in id_counter.items() if c == total]
        if len(team_ids) == 1:
            string_id = team_ids[0]
        elif id_counter:
            string_id = id_counter.most_common(1)[0][0]
        else:
            continue

        d1_string_ids.add(string_id)
        conference = ncaa_id_to_conference.get(ncaa_id, "")
        string_id_to_conference[string_id] = conference

    return d1_string_ids, string_id_to_conference


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


def parse_game(filepath, d1_string_ids=None, string_id_to_conference=None):
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

    # Filter: both teams must be Division I
    if d1_string_ids is not None:
        if home_team not in d1_string_ids or away_team not in d1_string_ids:
            return []

    game_date = game.get("Date", "")

    # Conference lookups
    conf_map = string_id_to_conference or {}
    home_conference = conf_map.get(home_team, "")
    away_conference = conf_map.get(away_team, "")
    is_conference_game = home_conference != "" and home_conference == away_conference
    home_is_power4 = home_conference in POWER_4_CONFERENCES
    away_is_power4 = away_conference in POWER_4_CONFERENCES

    # Unique identifier per game file: ncaa_id prefix from directory, season, game_id
    team_ncaa_id = team_dir.split("-")[0] if team_dir != "unknown" else "unknown"
    unique_game_id = f"{team_ncaa_id}-{season}-{game_id}"

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
            "game_date": game_date,
            "team_dir": team_dir,
            "home_team": home_team,
            "home_name": home_name,
            "home_conference": home_conference,
            "away_team": away_team,
            "away_name": away_name,
            "away_conference": away_conference,
            "is_conference_game": is_conference_game,
            "home_is_power4": home_is_power4,
            "away_is_power4": away_is_power4,
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
            "periods_regulation": periods_regulation,
            "home_final": home_final,
            "away_final": away_final,
        })

    # Validate: last PBP score should match game final scores.
    # If they're swapped or way off, the PBP data is unreliable for this game.
    if rows and (current_home_score > 0 or current_away_score > 0):
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


def ncaa_id_from_dir(dirname):
    """Extract the NCAA ID prefix from a team directory name like '8-alabama'."""
    prefix = dirname.split("-")[0]
    return int(prefix) if prefix.isdigit() else None


def find_game_files(data_dir, d1_team_ids=None):
    """Find all game JSON files in the data directory.

    If d1_team_ids is provided, only include files from team directories
    whose NCAA ID prefix is in the set.
    """
    all_files = list(Path(data_dir).glob("*/*/*.json"))
    if d1_team_ids is None:
        return all_files
    return [f for f in all_files if ncaa_id_from_dir(f.parts[-3]) in d1_team_ids]


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

    # Load Division I team data
    d1_ncaa_ids, ncaa_id_to_conference = load_d1_teams()
    print(f"Loaded {len(d1_ncaa_ids)} Division I team NCAA IDs")

    print(f"Finding game files in {data_dir}...")
    files = find_game_files(data_dir, d1_ncaa_ids)
    print(f"Found {len(files):,} game files from D-I team directories")

    # Build string ID -> conference mapping from directory contents
    print("Building D-I string team ID mapping...")
    d1_string_ids, string_id_to_conference = build_d1_team_info(
        data_dir, d1_ncaa_ids, ncaa_id_to_conference)
    print(f"Mapped {len(d1_string_ids)} D-I string team IDs")

    if args.limit > 0:
        files = files[:args.limit]
        print(f"Limited to {args.limit:,} files")

    print(f"Parsing with {args.workers} workers...")
    parse_fn = partial(parse_game, d1_string_ids=d1_string_ids,
                       string_id_to_conference=string_id_to_conference)
    with Pool(args.workers) as pool:
        results = pool.map(parse_fn, files, chunksize=200)

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

    # Deduplicate: the same game may appear under multiple team directories.
    # Use home_team + away_team + game_date to identify the same game,
    # then dedup scoring plays within each game.
    before = len(df)
    df = df.drop_duplicates(subset=["home_team", "away_team", "game_date",
                                     "period", "clock_seconds", "home_score", "away_score"])
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
