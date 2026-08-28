# ParlayAPI Odds Fetch Action

[![Smoke test](https://github.com/JacobiusMakes/parlayapi-odds-action/actions/workflows/smoke.yml/badge.svg)](https://github.com/JacobiusMakes/parlayapi-odds-action/actions/workflows/smoke.yml)
[![Release](https://img.shields.io/github/v/release/JacobiusMakes/parlayapi-odds-action)](https://github.com/JacobiusMakes/parlayapi-odds-action/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Fetch live sports betting odds from [ParlayAPI](https://parlay-api.com) (30+ sportsbooks) straight into your GitHub workflow, as a JSON or CSV file. Built for cron-driven models, dashboards, and data pipelines that live in GitHub Actions.

No Node build, no Docker pull: this is a composite action using only bash, curl, and jq, all preinstalled on GitHub-hosted runners.

## Quick start: scheduled odds snapshots

Grab NBA odds every 6 hours and store each snapshot as a workflow artifact.

```yaml
name: NBA odds snapshot
on:
  schedule:
    - cron: "0 */6 * * *"
  workflow_dispatch:

jobs:
  odds:
    runs-on: ubuntu-latest
    steps:
      - name: Fetch odds
        id: odds
        uses: JacobiusMakes/parlayapi-odds-action@v1
        with:
          api_key: ${{ secrets.PARLAY_API_KEY }}
          sport: basketball_nba
          regions: us
          markets: h2h,spreads,totals

      - name: Upload snapshot
        uses: actions/upload-artifact@v4
        with:
          name: nba-odds-${{ github.run_id }}
          path: ${{ steps.odds.outputs.file }}
```

Setup:

1. Get a free API key at [parlay-api.com/signup](https://parlay-api.com/signup). The free tier includes 1,000 credits per month.
2. Add it as a repository secret named `PARLAY_API_KEY` (Settings, Secrets and variables, Actions).
3. Commit the workflow above to `.github/workflows/odds.yml`.

A call with one market and one region costs 1 credit (credits per call = markets x regions), so even an hourly cron fits inside the free tier. Current tiers and credit prices: [parlay-api.com/pricing](https://parlay-api.com/pricing).

## Example: commit a CSV for a dashboard

Refresh a CSV in your repo once a day, so a dashboard (Flat Data, Observable, a static site, a notebook) can read it from a stable URL.

```yaml
name: NFL odds CSV
on:
  schedule:
    - cron: "30 11 * * *"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  odds:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Fetch odds as CSV
        uses: JacobiusMakes/parlayapi-odds-action@v1
        with:
          api_key: ${{ secrets.PARLAY_API_KEY }}
          sport: americanfootball_nfl
          markets: h2h,spreads,totals
          format: csv
          output: data/nfl-odds.csv

      - name: Commit updated CSV
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/nfl-odds.csv
          git diff --cached --quiet || git commit -m "Update NFL odds CSV"
          git push
```

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `api_key` | yes | | Your ParlayAPI key. Always pass it from a secret. Free key: [parlay-api.com/signup](https://parlay-api.com/signup) |
| `sport` | yes | | Sport key, e.g. `basketball_nba`, `americanfootball_nfl`, `baseball_mlb`, `soccer_epl`. Full live list (no key needed): [parlay-api.com/v1/sports](https://parlay-api.com/v1/sports) |
| `regions` | no | `us` | Comma-separated bookmaker regions: `us`, `us2`, `uk`, `eu`, `au`, and more. Use `eu` for Pinnacle and European books. |
| `markets` | no | `h2h` | Comma-separated markets: `h2h`, `spreads`, `totals` |
| `odds_format` | no | `american` | `american` or `decimal` |
| `output` | no | `odds.json` | Path of the file to write. Parent directories are created if needed. |
| `format` | no | `json` | `json` writes the raw API response. `csv` flattens it to one row per bookmaker, market, and outcome. |

## Outputs

| Output | Description |
|---|---|
| `file` | Path of the written odds file (same as the `output` input) |
| `event_count` | Number of events in the response |

## JSON shape

The JSON file is the raw API response: an array of events, each with `id`, `commence_time`, `home_team`, `away_team`, and a `bookmakers` array of `markets` and `outcomes`. Full reference: [parlay-api.com/docs](https://parlay-api.com/docs).

## CSV shape

One row per bookmaker, market, and outcome:

```csv
"event_id","commence_time","sport_key","home_team","away_team","bookmaker","bookmaker_title","market","market_last_update","outcome","price","point"
"2fffd3f11aad1186b2f18aebd6eb3b50","2026-08-28T23:15:00Z","baseball_mlb","Atlanta Braves","Colorado Rockies","fanduel","FanDuel","h2h","2026-08-28T16:00:01Z","Atlanta Braves",-215,""
"2fffd3f11aad1186b2f18aebd6eb3b50","2026-08-28T23:15:00Z","baseball_mlb","Atlanta Braves","Colorado Rockies","pinnacle","Pinnacle","h2h","2026-08-28T15:59:23Z","Atlanta Braves",-222,""
```

`point` is filled for `spreads` and `totals` rows and empty for `h2h`.

## Troubleshooting

**HTTP 401 MISSING_KEY or INVALID_KEY.** The key did not reach the API, or it has a typo or stray whitespace. Check that the secret exists under the exact name your workflow references, and that you pass it as `api_key: ${{ secrets.PARLAY_API_KEY }}`. Note that secrets are not available to workflows triggered from forks.

**HTTP 401 on a key that worked yesterday.** Keys can be deactivated from the dashboard. Log in at [parlay-api.com](https://parlay-api.com) and check the key status.

**`event_count` is 0.** Usually not an error: it means no events are currently scheduled for that sport (off-season, or no games in the window). Verify the sport key against [parlay-api.com/v1/sports](https://parlay-api.com/v1/sports).

**Out of credits or rate limited.** Check your usage on the dashboard, and see [parlay-api.com/pricing](https://parlay-api.com/pricing) for tier limits. Reducing `markets` and `regions` reduces the credit cost of each call.

**Failure messages.** On any non-200 response the action fails the step and prints the API's own error code, message, and `request_id`. Include the `request_id` if you contact support.

**Want to try it without a key?** The API has a free no-auth demo endpoint: `https://parlay-api.com/v1/try/baseball_mlb/odds` (also `basketball_nba`, `americanfootball_nfl`, `icehockey_nhl`, `soccer_epl`, `mma_mixed_martial_arts`). This action itself needs a key, but the demo endpoint is an easy way to see the response shape first.

## License

[MIT](LICENSE)
