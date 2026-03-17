# WBB Comeback Probability

A model that answers: **given a team is trailing by X points with Y minutes remaining, how often do they come back to win?**

Built from ~286,000 NCAA women's basketball games spanning 25 seasons (2001–02 through 2025–26), using full play-by-play data. Every scoring play where one team was trailing becomes an observation — recording the deficit, time remaining, and whether the trailing team ultimately won. The result is a probability lookup table covering every combination of deficit size and time remaining in regulation.

A pre-built version of the probability table is available in [data/comeback_probs.csv](data/comeback_probs.csv). See [data/COMEBACK_PROBS_GUIDE.md](data/COMEBACK_PROBS_GUIDE.md) for a full description of its columns and how to use it.

## Data

The scripts expect play-by-play game data in JSON format from NCAA teams' official websites. Each file should represent one game and include a `Game` object with `HomeTeam`, `VisitingTeam`, `IsComplete`, and a `Plays` array. Organize the files into a directory tree (e.g., by season) and pass the root path to `parse_games.py`.

The data used for this project comes from [this repository](https://github.com/dwillis/wbb-game-data) maintained by the author.

## Setup

The project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
uv sync
```

## Running the pipeline

**Step 1 — Parse games into a flat table of game-states:**

```bash
uv run python parse_games.py /path/to/wbb-game-data
```

This walks every JSON file in the given directory, extracts a row for each scoring play, and writes `data/game_states.parquet`. Use `--workers N` to parallelize across CPU cores.

**Step 2 — Build the probability table:**

```bash
uv run python build_probability_table.py
```

Reads `data/game_states.parquet` and writes `data/comeback_probs.csv`. Use `--input` and `--output` to override the default paths.

**Step 3 — Visualize:**

```bash
uv run python visualize.py
```

Produces a heatmap of comeback rates by deficit and time remaining, plus win probability curves for selected deficit sizes.

## Scope and limitations

The model covers regulation play only (4 quarters × 10 minutes). It pools all competition levels (D1, D2, D3, NAIA) and all 25 seasons together, so it doesn't account for differences in pace or era. It also has no knowledge of context beyond the score and the clock — no home-court advantage, no foul trouble, no momentum.

## License

This project is released under the [MIT License](LICENSE). You are free to use, modify, and distribute it for any purpose, provided the original copyright notice is retained.

## Author

Built by [Derek Willis](https://github.com/dwillis).
