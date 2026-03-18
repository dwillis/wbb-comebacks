# Guide to comeback_probs.csv

## What is this file?

This is a lookup table that answers the question: **if a team is losing by X points with Y minutes left, how often do they come back to win?**

It was built from ~286,000 NCAA women's basketball games spanning 25 seasons (2001-02 through 2025-26), using full play-by-play scoring data. For each game, we recorded whether the trailing team in a given deficit/time situation ultimately won — counting each game only once per situation to ensure statistical independence.

## Columns

| Column | Type | Description |
|--------|------|-------------|
| `deficit_bucket` | string | How far behind the trailing team is. Single-point buckets from `1` through `10`, then grouped: `11-15`, `16-20`, `21-25`, `26-30`, `31+`. |
| `time_bucket` | string | Time remaining in regulation. For the final 2 minutes, 30-second bins: `0.0-0.5`, `0.5-1.0`, `1.0-1.5`, `1.5-2.0`. For 2+ minutes, integer-minute bins: `2`, `3`, ..., `39`. |
| `n_games` | integer | Number of unique games where a team was trailing by this deficit with this much time left. This is the true independent sample size used for all statistics. |
| `n_wins` | integer | Of those games, how many times the trailing team went on to win. |
| `n_observations` | integer | Total number of scoring plays (across all games) in this cell. Larger than `n_games` because a single game can have multiple scoring plays in the same cell. Included for reference but not used for statistics. |
| `trailing_team_win_pct` | float | The trailing team's historical win rate: `n_wins / n_games`. Ranges from 0.0 (never happened) to ~0.46 (nearly a coin flip). |
| `ci_lower` | float | Lower bound of the 95% Wilson confidence interval. |
| `ci_upper` | float | Upper bound of the 95% Wilson confidence interval. |
| `adequate_sample` | boolean | `True` if `n_games >= 30`. When `False`, the win percentage is based on very few independent games and shouldn't be taken at face value. |

## How to read it

**Example row:**

```
deficit_bucket: 5, time_bucket: 10, n_games: 18432, n_wins: 3872, n_observations: 24892, trailing_team_win_pct: 0.210, adequate_sample: True
```

This means: across all games in the dataset, 18,432 unique games had a moment where a team trailed by 5 points with 10–11 minutes remaining. Of those, 3,872 (21.0%) saw the trailing team come back to win. The 24,892 figure counts total scoring plays in this situation across all games (higher because a single game can have multiple scoring plays while down by 5 in the same minute).

## Why n_games vs n_observations?

Each game is counted **once** per cell, regardless of how many scoring plays occurred in that situation. This matters because:

- A team that's down by 10 for several consecutive scoring plays would inflate the observation count but represents only one independent trial (the game either results in a comeback or it doesn't).
- The Wilson confidence intervals require independent observations to be valid. Using `n_games` ensures the intervals are correctly calibrated.

## Time bucket detail

For the final 2 minutes of regulation, the table provides 30-second granularity because endgame situations change rapidly:

| `time_bucket` | Meaning |
|---------------|---------|
| `0.0-0.5` | 0 to 30 seconds remaining |
| `0.5-1.0` | 30 to 60 seconds remaining |
| `1.0-1.5` | 1:00 to 1:30 remaining |
| `1.5-2.0` | 1:30 to 2:00 remaining |
| `2` | 2:00 to 2:59 remaining |
| `3` | 3:00 to 3:59 remaining |
| ... | ... |
| `39` | 39:00 to 40:00 (start of game) |

## Key patterns in the data

**Small deficits are very recoverable.** A 1-point deficit is nearly a coin flip regardless of time remaining (~45% win rate with 20+ minutes left). Even with under 30 seconds to play, teams trailing by 1 still win roughly 25% of the time.

**The cliff is steep between 10 and 15 points.** A 10-point deficit at halftime (20 min left) has roughly a 12% win rate for the trailing team. An 11-15 point deficit at halftime drops to about 6%. By 16-20 points, it's under 2%.

**Time matters most for moderate deficits.** For a 5-point deficit, the trailing team win rate drops from ~25% at 30 minutes elapsed to ~8% with 2 minutes left. For a 1-point deficit, time barely matters — the rate stays in the 40-45% range until the final minutes.

**Deficits of 20+ are essentially fatal at any point.** Even early in the game, trailing by 21-25 points yields a win rate under 1%.

## The confidence intervals

The `ci_lower` and `ci_upper` columns give a 95% Wilson confidence interval. Wilson intervals are better than simple ± calculations for proportions, especially when the probability is near 0% or 100% or when sample sizes are modest. The intervals are computed using `n_games` (independent observations), not `n_observations`.

## Scope and limitations

- **Regulation only.** Overtime periods are excluded. The model covers the standard 40-minute regulation game (4 quarters × 10 minutes).
- **All divisions.** The data includes D1, D2, D3, NAIA, and other NCAA-affiliated women's basketball. Comeback rates likely differ across competition levels but are not split here.
- **All seasons pooled.** Twenty-five years of games are combined into one table. If the style of play has changed (e.g., more 3-point shooting in recent years), that could affect comeback odds differently by era.
- **No home/away split.** Home court advantage likely makes home teams slightly more likely to come back, but this table doesn't separate the two.
- **No momentum or context.** The table only knows the deficit and time remaining. It doesn't account for whether a team is on a scoring run, foul trouble, or any other contextual factor.

## Using this data

**Quick lookup:** Filter to the deficit bucket and time bucket you're interested in, and read the `trailing_team_win_pct` value.

**Visualization:** Pivot the table with `deficit_bucket` as rows and `time_bucket` as columns, with `trailing_team_win_pct` as values, to create a heatmap.

```python
import pandas as pd

df = pd.read_csv("comeback_probs.csv")
pivot = df.pivot_table(index="deficit_bucket", columns="time_bucket", values="trailing_team_win_pct")
```

**In-game win probability:** For a specific game, look up the current deficit and time remaining to get a rough win probability for the trailing team. The leading team's win probability is `1 - trailing_team_win_pct`.

**Filtering by confidence:** Use `adequate_sample == True` to exclude unreliable cells, or use the confidence interval columns to report ranges instead of point estimates.
