# Founder note: publishing to the GitHub Actions Marketplace

This repo is release-ready but marketplace listing is a manual checkbox that only a human with admin rights can tick. Two minutes of work:

1. Open the v1.0.0 release: https://github.com/JacobiusMakes/parlayapi-odds-action/releases/tag/v1.0.0
2. Click "Edit" on the release.
3. Check "Publish this Action to the GitHub Marketplace". GitHub will ask you to accept the GitHub Marketplace Developer Agreement the first time.
4. Pick two categories. Suggested: "API management" and "Reporting".
5. Click "Update release".

The `action.yml` already has the marketplace requirements covered: `name`, `description`, `author`, and `branding` (icon `activity`, color `green`). The action name "ParlayAPI Odds Fetch" must be unique on the marketplace; if GitHub rejects it, tweak the `name` field in `action.yml`, commit, retag, and re-publish.

## What was verified against the live API (2026-08-28)

- Endpoint: `GET https://parlay-api.com/v1/sports/{sport_key}/odds` (from the live `/openapi.json`). It is v1, not v4.
- Auth: `X-API-Key` header (recommended by the spec; `?apiKey=` and `Authorization: Bearer` also accepted).
- Query params used: `regions` (default `us`), `markets` (default `h2h`), `oddsFormat`.
- Success body: top-level JSON array of events, confirmed live via the keyless sandbox `/v1/sandbox/sports/{sport_key}/odds`, which mirrors the real endpoint's shape. Note: the keyless demo `/v1/try/{sport_key}/odds` is NOT a byte-for-byte preview. It wraps events in a demo envelope (events nested under an `events` key), so only the event objects inside it match the real response.
- Error body: `{"detail": {"error", "message", "signup_url", "request_id", "docs_url", "status"}}`, confirmed live with a missing key and an invalid key (both HTTP 401). The action surfaces `error`, `message`, and `request_id` on failure.
- Free tier: 1,000 credits per month at $0, confirmed from the live `/pricing` JSON.
- Credit cost formula "markets x regions" is from the live docs description of the odds endpoint.

## Maintenance notes

- The smoke test workflow (`.github/workflows/smoke.yml`) runs the action against the keyless sandbox on every push, weekly, and on demand. It spends no credits and needs no secrets.
- `PARLAY_BASE_URL` is an undocumented workflow-level env override used only by the smoke test. Do not remove it from `action.yml` without updating the workflow.
- The `v1` tag is a moving major-version alias, standard for actions. When you cut v1.1.0, move `v1` to the same commit: `git tag -f v1 && git push -f origin v1`.
