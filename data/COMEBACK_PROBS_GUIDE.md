# Guide to comeback_probs.csv

## What is this file?

This is a lookup table that answers the question: **if a team is losing by X points with Y minutes left, how often do they come back to win?**

It was built from ~286,000 NCAA women's basketball games spanning 25 seasons (2001-02 through 2025-26), using full play-by-play scoring data. Every time a scoring play occurred and one team was trailing, that moment became an observation: we recorded how far behind the trailing team was, how much time was left, and whether they ultimately won.

The file has 597 rows. Each row represents one combination of deficit size and time remaining, with the historical comeback rate for that situation.

## Columns

| Column | Type | Description |
|--------|------|-------------|
| `deficit_bucket` | string | How far behind the trailing team is. Single-point buckets from `1` through `10`, then grouped: `11-15`, `16-20`, `21-25`, `26-30`, `31+`. |
| `time_bucket` | integer | Minutes remaining in regulation, floored to the nearest whole minute. `0` means 0:00–0:59 left, `1` means 1:00–1:59, and so on up to `39` (39:00–40:00, i.e. the start of the game). |
| `n_observations` | integer | How many times a team was trailing by this deficit with this much time left across all 286K games. Larger numbers mean more reliable estimates. |
| `n_comebacks` | integer | Of those observations, how many times the trailing team went on to win the game. |
| `comeback_pct` | float | The comeback win rate: `n_comebacks / n_observations`. Ranges from 0.0 (never happened) to ~0.46 (nearly a coin flip). |
| `ci_lower` | float | Lower bound of the 95% Wilson confidence interval. |
| `ci_upper` | float | Upper bound of the 95% Wilson confidence interval. |
| `adequate_sample` | boolean | `True` if `n_observations >= 30`. When `False`, the comeback percentage is based on very few games and shouldn't be taken at face value. |

## How to read it

**Example row:**

```
deficit_bucket: 5, time_bucket: 10, n_observations: 24892, n_comebacks: 5214, comeback_pct: 0.209, adequate_sample: True
```

This means: across all games in the dataset, there were 24,892 moments where a team trailed by 5 points with 10–11 minutes remaining. Of those, 5,214 times (20.9%) the trailing team came back to win.

## Key patterns in the data

**Small deficits are very recoverable.** A 1-point deficit is nearly a coin flip regardless of time remaining (~45% comeback rate with 20+ minutes left). Even with under a minute to play, teams trailing by 1 still win about 25% of the time.

**The cliff is steep between 10 and 15 points.** A 10-point deficit at halftime (20 min left) has roughly a 12% comeback rate. An 11-15 point deficit at halftime drops to about 6%. By 16-20 points, it's under 2%.

**Time matters most for moderate deficits.** For a 5-point deficit, the comeback rate drops from ~25% at 30 minutes remaining to ~8% with 2 minutes left. For a 1-point deficit, time barely matters — the rate stays in the 40-45% range until the final minutes.

**Deficits of 20+ are essentially fatal at any point.** Even with a full game to play, trailing by 21-25 points yields a comeback rate under 1%.

## The confidence intervals

The `ci_lower` and `ci_upper` columns give a 95% Wilson confidence interval around the comeback percentage. Wilson intervals are better than simple ± calculations for proportions, especially when the probability is near 0% or 100% or when sample sizes are modest.

For most cells, the intervals are tight (±1-2 percentage points) because the sample sizes are large. For extreme deficits late in games, the intervals widen because there are fewer observations.

## What "adequate_sample" means

Only 14 of the 597 cells have `adequate_sample = False`. These are mostly extreme deficits (26-30 or 31+ points) very late in the game, where such situations almost never arise. The comeback percentages for these cells are technically computed but shouldn't be cited as reliable.

## Scope and limitations

- **Regulation only.** Overtime periods are excluded. The model covers the standard 40-minute regulation game (4 quarters × 10 minutes).
- **All divisions.** The data includes D1, D2, D3, NAIA, and other NCAA-affiliated women's basketball. Comeback rates likely differ across competition levels but are not split here.
- **All seasons pooled.** Twenty-five years of games are combined into one table. If the style of play has changed (e.g., more 3-point shooting in recent years), that could affect comeback odds differently by era.
- **No home/away split.** Home court advantage likely makes home teams slightly more likely to come back, but this table doesn't separate the two.
- **No momentum or context.** The table only knows the deficit and time remaining. It doesn't account for whether a team is on a scoring run, foul trouble, or any other contextual factor.

## Using this data

**Quick lookup:** Filter to the deficit bucket and time bucket you're interested in, and read the `comeback_pct` value.

**Visualization:** Pivot the table with `deficit_bucket` as rows and `time_bucket` as columns, with `comeback_pct` as values, to create a heatmap.

```python
import pandas as pd

df = pd.read_csv("comeback_probs.csv")
pivot = df.pivot_table(index="deficit_bucket", columns="time_bucket", values="comeback_pct")
```

**In-game win probability:** For a specific game, look up the current deficit and time remaining to get a rough win probability for the trailing team. The leading team's win probability is `1 - comeback_pct`.

**Filtering by confidence:** Use `adequate_sample == True` to exclude unreliable cells, or use the confidence interval columns to report ranges instead of point estimates.
