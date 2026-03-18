# WBB Comeback Probability Model

## Overview

Build a model that answers: **given a team is trailing by X points with Y time remaining, what is the historical probability that they come back to win?**

The dataset contains ~296K game JSON files spanning 20+ seasons (2001–2026) of NCAA women's basketball, with full play-by-play data including timestamps and running scores.

## Data Structure

Each game file contains:

- **Game metadata**: home/visiting team IDs, names, final scores, `IsComplete` flag
- **Plays array**: chronologically ordered, each play has `Period` (1–4+), `ClockSeconds` (600→0 per period), `Type`, `Action`, and `Score` (home/visitor totals, present only on scoring plays)
- Regulation: 4 quarters × 10 minutes (600 seconds each). Overtime: 5-minute periods.

Key detail: `Score` is only populated on scoring plays (~22% of plays). To track the score at any point, carry forward the most recent `Score` object.

## Phase 1: Data Extraction

### Goal
Parse all game files into a flat table of **game-states**: snapshots of the score differential at regular time intervals.

### Approach (Python)

```
For each game JSON:
    1. Skip if Game.IsComplete != true
    2. Determine winner (compare Game.HomeTeam.Score vs Game.VisitingTeam.Score)
    3. Walk the Plays array chronologically, carrying forward the latest Score
    4. At each scoring play, record:
        - game_id (filename)
        - season (from directory path)
        - home_team, visiting_team
        - period, clock_seconds
        - home_score, visitor_score
        - margin (from the trailing team's perspective)
        - total_seconds_remaining = (periods_remaining * period_length) + clock_seconds
        - trailing_team ("home" or "visitor")
        - trailing_team_won (boolean — the key target variable)
```

### Output
A CSV/Parquet file with one row per scoring play per game, annotated with whether the trailing team ultimately won.

### Libraries
- `json`, `pathlib` for file I/O
- `pandas` for tabular output
- `multiprocessing` or `joblib` for parallel parsing (~296K files)

### Edge Cases to Handle
- **Tied scores**: margin = 0 — exclude from "comeback" analysis or treat separately
- **Overtime games**: `total_seconds_remaining` needs to account for extra periods; flag OT games for optional filtering
- **Incomplete games**: skip (`IsComplete != true`)
- **Missing or malformed plays**: skip games where Score never appears or final score doesn't match play-by-play

## Phase 2: Aggregation & Probability Table

### Goal
Build a lookup table: **P(win | margin, time_remaining)**

### Approach

1. **Bin the data** by:
   - `margin`: 1-point buckets for small deficits (1–10), then 5-point buckets (11–15, 16–20, 21–25, 26–30, 31+)
   - `time_remaining`: 30-second buckets for the final 2 minutes (0:00–0:30, 0:30–1:00, 1:00–1:30, 1:30–2:00), then 1-minute buckets (2–3 min, ... 39–40 min)

2. **Deduplicate for independence**: Each game is counted once per (margin_bucket, time_bucket) cell. A single game may pass through a cell via multiple scoring plays, but the outcome (trailing team wins or not) is the same for all of them. Using one observation per game ensures the Wilson confidence intervals are correctly calibrated.

3. **For each (margin_bucket, time_bucket)**, compute:
   - `n_games`: how many unique games had a team trailing by that margin with that much time left (independent observations)
   - `n_wins`: how many of those games saw the trailing team win
   - `n_observations`: total scoring plays in this cell across all games (for reference; not used for statistics)
   - `trailing_team_win_pct`: n_wins / n_games
   - `ci_lower`, `ci_upper`: 95% Wilson confidence interval (computed on n_games)

4. **Minimum sample size**: flag cells with fewer than 30 unique games as `adequate_sample = False`

### Output
A CSV lookup table + a heatmap visualization.

## Phase 3: Visualization

### Heatmap (primary)
- **X-axis**: minutes left in game (most time on left → 0 on right)
- **Y-axis**: point deficit (1 → 31+)
- **Color**: trailing team win probability (0% red → 50% green)
- Annotate only landmark cells (near 5%, 10%, 25%, 50%) to avoid visual clutter

### Win Probability Curves (secondary)
- Line chart: for selected deficits (5, 10, 11–15, 16–20, 21–25 points), plot trailing team win probability vs. elapsed game time (0→40 minutes, left to right)
- Overlay with 95% Wilson confidence bands
- Filter cells with fewer than 30 unique games to avoid noisy CI bands

### Single-Game Win Probability Chart
- Charts the most improbable comeback in the dataset
- Plots one team's win probability over the course of the game, updating at each scoring play
- Uses the probability lookup table to compute win probability at each moment
- Annotates the worst moment (lowest win probability)

### Greatest Comebacks
- Identifies the 25 most improbable comebacks, ranked by the trailing team's win probability at their worst moment (not just by raw deficit size)
- Joins game-level worst moments against the probability table for ranking

## Phase 4: Modeling (Optional Extension)

### Logistic Regression
Go beyond the lookup table with a parametric model:

```python
from sklearn.linear_model import LogisticRegression

features = ["margin", "total_seconds_remaining", "margin_x_time"]
# margin_x_time = interaction term

model = LogisticRegression()
model.fit(X_train[features], y_train["trailing_team_won"])
```

### Additional features to explore:
- **Is home team trailing?** (home court comeback advantage)
- **Season era** (pre-2015 vs post-2015 — has the 3-point revolution changed comeback odds?)
- **Scoring run context**: is the trailing team on a run at the snapshot moment? (requires looking at recent play history)
- **Division/conference tier**: do high-major teams come back more often?

### Evaluation
- AUC-ROC on held-out test set (split by season to avoid leakage)
- Calibration plot: do predicted probabilities match observed frequencies?
- Brier score for probability calibration quality

## Phase 5: Analysis Questions to Answer

Once the model and tables are built, use them to investigate:

1. **"Point of no return"**: For each deficit size, at what time remaining does the comeback probability drop below 5%? Below 1%?
2. **Home court comeback advantage**: Are home teams more likely to come back than visitors? By how much?
3. **Era comparison**: Have comeback probabilities changed over 20 years? (hypothesis: more 3-point shooting = quicker scoring = easier comebacks)
4. **Overtime factor**: Are games that reach OT more likely to have involved earlier comebacks?
5. **Greatest comebacks**: Rank the most improbable comebacks in the dataset by the lowest trailing team win probability at the worst moment (using the probability lookup table)
6. **Conference patterns**: Which conferences produce the most comebacks? (proxy for competitive balance)
7. **Quarter-specific momentum**: Is a 10-point deficit at halftime more or less recoverable than a 10-point deficit entering Q4?

## Implementation Plan

| Step | Task | Est. Output |
|------|------|-------------|
| 1 | Write game parser script (`parse_games.py`) | game_states.parquet |
| 2 | Run parser across all ~296K files | ~5–15M rows |
| 3 | Aggregation script (`build_probability_table.py`) | comeback_probs.csv |
| 4 | Heatmap + line chart visualization | comeback_heatmap.png |
| 5 | Logistic regression model (optional) | model.pkl + calibration plots |
| 6 | Analysis notebook exploring the questions above | analysis.ipynb |

## File Structure

```
wbb-game-data/
├── analysis/
│   ├── parse_games.py            # Phase 1: extract game states
│   ├── build_probability_table.py # Phase 2: aggregate
│   ├── visualize.py              # Phase 3: charts
│   ├── model.py                  # Phase 4: logistic regression
│   ├── analysis.ipynb            # Phase 5: exploration
│   ├── data/
│   │   ├── game_states.parquet
│   │   └── comeback_probs.csv
│   └── output/
│       ├── comeback_heatmap.png
│       ├── win_prob_curves.png
│       └── greatest_comebacks.csv
```

## Dependencies

```
pandas
pyarrow          # for parquet
matplotlib
seaborn
scikit-learn     # optional, for Phase 4
joblib           # parallel processing
scipy            # Wilson CI calculation
```
