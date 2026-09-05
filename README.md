# ParlayAPI Odds Fetch Action v2

[![Offline unit tests](https://github.com/JacobiusMakes/parlayapi-odds-action/actions/workflows/smoke.yml/badge.svg)](https://github.com/JacobiusMakes/parlayapi-odds-action/actions/workflows/smoke.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Bring [ParlayAPI](https://parlay-api.com) odds into a private model or internal research workflow. This action verifies the caller repository through GitHub, then writes JSON or CSV into a protected runner temporary directory outside your checkout. It prints no prices, teams, response bodies or credentials.

v2 requires a **private GitHub.com repository** and your own ParlayAPI account key. Public repositories, organization-internal repositories and unverifiable visibility are refused before any ParlayAPI request. The composite action uses Python 3.10+ and its standard library on Linux or macOS. It has no package install step.

## Quick start: private analysis

Create a private repository, get your own key at [signup](https://parlay-api.com/signup), and save it as a repository secret named `PARLAY_API_KEY`. Add a model script that accepts a local JSON path. Keep its diagnostics and results private; it must not print or republish the input data.

```yaml
name: Private odds analysis
on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  analyze:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false

      - name: Fetch for this private project
        id: odds
        uses: JacobiusMakes/parlayapi-odds-action@v2
        with:
          api_key: ${{ secrets.PARLAY_API_KEY }}
          sport: baseball_mlb
          markets: h2h

      - name: Run your internal model
        env:
          ODDS_FILE: ${{ steps.odds.outputs.file }}
        run: python3 analysis.py "$ODDS_FILE"

      - name: Remove the input after analysis
        if: always() && steps.odds.outputs.file != ''
        env:
          ODDS_FILE: ${{ steps.odds.outputs.file }}
        run: |
          python3 - <<'PY'
          import os
          from pathlib import Path
          source = Path(os.environ["ODDS_FILE"])
          source.unlink(missing_ok=True)
          source.parent.rmdir()
          PY
```

`analysis.py` is your own model, not included with the action. Read the JSON locally with `json.load`; an empty array is a valid response and should be handled without inventing missing data. For reproducible workflows, pin a reviewed v2 release commit rather than a moving major-version tag. When adding a schedule, calculate its workload using the [current pricing and credit rules](https://parlay-api.com/pricing), including the selected markets and regions.

## Data use and limits of the guard

This v2 tool is designed for personal and internal analysis. Do not publish its raw odds as a public board, committed snapshot, downloadable feed, public artifact or white-label product. Each customer uses their own account and key. A private repository is a prerequisite for this action, not a license grant. Private repository collaborators and later workflow steps can still read or copy the file, and administrators can change repository visibility later.

The visibility check reduces accidental distribution; it is not DRM or a change to existing API contracts. Your applicable [Terms of Service](https://parlay-api.com/terms), [Acceptable Use Policy](https://parlay-api.com/acceptable-use) and any signed agreement govern data rights. Discuss public display, redistribution or a separate license with [ParlayAPI support](https://parlay-api.com/support). A self-serve upgrade does not establish a signed redistribution grant. The action's MIT license covers its software, **not the API data**.

Only use trusted workflows and runners. Unix modes restrict other users, not other processes running as the same runner user. GitHub-hosted jobs clean their temporary workspace; self-hosted runner operators remain responsible for cleanup after interruptions. The example also removes the input explicitly after analysis. Avoid public artifacts, logs, caches and commits containing responses.

## Inputs

| Input | Required | Default | Accepted values |
| --- | --- | --- | --- |
| `api_key` | yes | | Own ParlayAPI key from a repository secret; no whitespace or control characters. |
| `sport` | yes | | Lowercase underscore-separated key from the [sports catalogue](https://parlay-api.com/v1/sports), for example `baseball_mlb`. |
| `regions` | no | `us` | Comma-separated `us`, `us2`, `uk`, `eu`, `fr`, `au`, `ca`, `mx`, `latam`, `br`, `asia`; no spaces or duplicates. |
| `markets` | no | `h2h` | Comma-separated `h2h`, `spreads`, `totals`; no spaces or duplicates. |
| `odds_format` | no | `american` | `american` or `decimal`. |
| `output` | no | `odds.json` | One filename, 1 to 128 characters, starting with a letter or digit; subsequent letters, digits, `.`, `_`, `-`. No directory paths. Use `odds.csv` with CSV if desired. |
| `format` | no | `json` | `json` or `csv`. |

Repository identity, GitHub token and runner directories come directly from the GitHub Actions context. There is no input to override repository verification or the API origins. The old `PARLAY_BASE_URL` override is ignored. GitHub Enterprise Server is unsupported because verification uses the fixed GitHub.com API.

## Outputs and source values

| Output | Meaning |
| --- | --- |
| `file` | Absolute file path in a newly created directory under runner temporary storage, outside the checkout. Directory mode `0700`, file mode `0600`. |
| `event_count` | Number of supplied events, including zero for an empty array. |

JSON preserves the validated API response bytes: a top-level event array with bookmaker, market and outcome objects. CSV flattens only supplied outcomes. It does not merge books, infer missing opponents, fabricate a price or calculate a replacement line.

CSV columns:

```text
event_id,commence_time,sport_key,home_team,away_team,bookmaker,bookmaker_title,bookmaker_last_update,market,market_last_update,outcome,price,point
```

Missing/null prices, points and timestamps are empty cells. A supplied point of zero stays `0`. Book and market update times have separate columns; a book update is never represented as a supplied market update. Treat source text as data when importing CSV into other tools.

## Failure behavior

- Verification requires HTTP 200 from `https://api.github.com/repos/{caller}` with the exact caller `full_name`, boolean `private: true` and `visibility: "private"`. Public, internal, missing/malformed data, authentication errors and timeouts all stop before the odds request. The workflow token is used only for GitHub; the ParlayAPI key is used only for ParlayAPI.
- The data request uses `https://parlay-api.com/v1/sports/{sport}/odds`, the validated query inputs, `dateFormat=iso` and an `X-API-Key` header. It never sends the key in the URL. It requests the endpoint's default upcoming-event scope.
- Both requests refuse redirects, make no automatic retries and ignore environment proxy/base-URL overrides. Each has a 30-second total deadline. GitHub metadata is capped at 512 KiB; odds responses and expanded CSV output are capped at 8 MiB each.
- Errors report a fixed explanation and, when available, HTTP status. Provider messages, body excerpts, request IDs and secrets are intentionally excluded from logs. For 401/403, check the relevant credential and repository access. For 429, reduce workload before retrying manually. For 5xx/timeouts, retry later. Oversized responses require a narrower request or another appropriately scoped private integration.
- Failed validation or a failed request produces no data file or success output. Partial file-writing failures remove the newly created private directory.

## Migrating from v1

v2 is a deliberate major-version change. Existing v1 version tags and their behavior are left unchanged; do not force-move `v1` onto this release.

Move your workflow to a private repository before selecting v2. Change `output: data/odds.csv` to a basename such as `output: odds.csv`, and pass `steps.odds.outputs.file` to your private analysis process. Replace workflows that commit, publish or upload raw responses with local consumption and cleanup. CSV adds `bookmaker_last_update` and no longer fills a missing market timestamp from the bookmaker timestamp. The bash/curl/jq runtime is replaced with Python stdlib, and no sandbox/base-URL override remains.

## Offline verification

```sh
python3 -m unittest discover -s tests -v
```

Tests cover request ordering and token separation, refusal before odds access, redirects, timeouts, malformed/oversized responses, input injection, file boundaries and modes, source nulls/zero points, cleanup and log secrecy. Fixtures are explicitly unit data with no real market quotes. The public repository's workflow runs these tests only; it makes no live odds requests and uses no API secret.

## Software license

[MIT](LICENSE). API data is governed separately as described above.
