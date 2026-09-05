"""Private-workflow v2. Stdlib only; never logs response content or credentials."""

import csv
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import tempfile
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


REQUEST_SECONDS = 30
GITHUB_MAX_BYTES = 512 * 1024
ODDS_MAX_BYTES = 8 * 1024 * 1024
REGIONS = frozenset(("us", "us2", "uk", "eu", "fr", "au", "ca", "mx", "latam", "br", "asia"))
MARKETS = frozenset(("h2h", "spreads", "totals"))
CSV_FIELDS = (
    "event_id", "commence_time", "sport_key", "home_team", "away_team",
    "bookmaker", "bookmaker_title", "bookmaker_last_update", "market", "market_last_update",
    "outcome", "price", "point",
)


class SafeError(Exception):
    """Messages must be fixed text, optionally containing an integer HTTP status."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@contextmanager
def request_deadline():
    # A total deadline bounds trickling bodies/headers instead of restarting
    # a socket timeout on each byte. Supported runners are Linux/macOS.
    if not hasattr(signal, "setitimer"):
        raise SafeError("Use a Linux or macOS runner with Python 3.10 or later.")

    def expire(signum, frame):
        raise TimeoutError()

    previous_handler = signal.signal(signal.SIGALRM, expire)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, REQUEST_SECONDS)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def request_bytes(url, headers, limit, service):
    """One GET, no proxies, redirects, retries or response-text error messages."""
    request = Request(url, headers=headers, method="GET")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with request_deadline(), opener.open(request, timeout=REQUEST_SECONDS) as response:
            if response.status != 200:
                raise SafeError(f"{service} returned HTTP {int(response.status)}. Check access and retry manually.")
            if response.geturl() != url:
                raise SafeError(f"{service} redirect refused. No automatic retry.")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > limit):
                raise SafeError(f"{service} response size is invalid or exceeds the limit.")
            data = response.read(limit + 1)
            if len(data) > limit:
                raise SafeError(f"{service} response exceeds the size limit.")
            if length is not None and len(data) != int(length):
                raise SafeError(f"{service} returned an incomplete response. No automatic retry.")
            return data
    except HTTPError as error:
        # This exception includes the upstream body/reason/URL. Never stringify it.
        status = int(error.code)
        error.close()
        raise SafeError(f"{service} returned HTTP {status}. Check access and retry manually.") from None
    except SafeError:
        raise
    except Exception:
        raise SafeError(f"{service} request failed or timed out. No automatic retry.") from None


def parse_json(data, service):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError()

    try:
        return json.loads(data, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except Exception:
        raise SafeError(f"{service} returned invalid JSON. Response content is withheld.") from None


def enum_list(value, allowed, name):
    parts = value.split(",")
    if not parts or len(parts) != len(set(parts)) or any(part not in allowed for part in parts):
        raise SafeError(f"Invalid {name}. Use the documented comma-separated values without spaces or duplicates.")
    return value


def header_secret(value, name):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,512}", value):
        raise SafeError(f"Invalid or missing {name}. Supply the documented secret without whitespace.")
    return value


def configuration(env):
    if env.get("ODDS_GITHUB_SERVER_URL") != "https://github.com":
        raise SafeError("This action requires a private repository on GitHub.com.")
    repository = env.get("ODDS_GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", repository):
        raise SafeError("Cannot verify the caller repository. Use this action in GitHub Actions.")
    if repository.split("/")[1] in (".", ".."):
        raise SafeError("Cannot verify the caller repository. Use this action in GitHub Actions.")
    key = header_secret(env.get("PARLAY_API_KEY", ""), "api_key")
    token = header_secret(env.get("ODDS_GITHUB_TOKEN", ""), "GitHub workflow token")
    sport = env.get("PARLAY_SPORT", "")
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", sport) or len(sport) > 100:
        raise SafeError("Invalid sport. Use a sport key from the sports catalogue.")
    regions = enum_list(env.get("PARLAY_REGIONS", "us"), REGIONS, "regions")
    markets = enum_list(env.get("PARLAY_MARKETS", "h2h"), MARKETS, "markets")
    odds_format = env.get("PARLAY_ODDS_FORMAT", "american")
    output_format = env.get("PARLAY_FORMAT", "json")
    if odds_format not in ("american", "decimal") or output_format not in ("json", "csv"):
        raise SafeError("Invalid format. Use american/decimal odds and json/csv output.")
    filename = env.get("PARLAY_OUTPUT", "odds.json")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", filename):
        raise SafeError("Invalid output. Supply a single filename, without directories or control characters.")
    try:
        workspace = Path(env["ODDS_WORKSPACE"]).resolve(strict=True)
        temp_root = Path(env["ODDS_RUNNER_TEMP"]).resolve(strict=True)
        output_command = Path(env["GITHUB_OUTPUT"])
        if not workspace.is_dir() or not temp_root.is_dir():
            raise ValueError()
        if temp_root == workspace or workspace in temp_root.parents:
            raise ValueError()
        if not output_command.is_file() or not env["ODDS_WORKSPACE"] or not env["ODDS_RUNNER_TEMP"]:
            raise ValueError()
        if any(char in str(temp_root) for char in "\r\n"):
            raise ValueError()
    except Exception:
        raise SafeError("Runner temporary storage must exist outside the checkout, with a valid step output file.") from None
    return {
        "repository": repository, "key": key, "token": token, "sport": sport,
        "regions": regions, "markets": markets, "odds_format": odds_format,
        "format": output_format, "filename": filename, "temp_root": temp_root,
        "output_command": output_command,
    }


def verify_private_repository(config):
    repository = config["repository"]
    data = request_bytes(
        f"https://api.github.com/repos/{repository}",
        {"Accept": "application/vnd.github+json", "Authorization": "Bearer " + config["token"],
         "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "parlayapi-odds-action-v2"},
        GITHUB_MAX_BYTES, "GitHub repository verification",
    )
    repo = parse_json(data, "GitHub repository verification")
    if (not isinstance(repo, dict) or repo.get("full_name") != repository
            or repo.get("private") is not True or repo.get("visibility") != "private"):
        raise SafeError("Repository privacy was not verified. Use a private repository; public, internal and unknown visibility are refused.")


def validate_events(events, config):
    """Validate supplied values; never invent missing outcomes or prices."""
    if not isinstance(events, list):
        raise SafeError("ParlayAPI returned an unexpected response shape. Response content is withheld.")

    def invalid():
        raise SafeError("ParlayAPI returned an invalid event structure. Response content is withheld.")

    def text_fields(item, fields):
        if not isinstance(item, dict) or any(not isinstance(item.get(field), str) for field in fields):
            invalid()

    def number_or_null(value):
        return value is None or (type(value) in (int, float) and math.isfinite(value))

    for event in events:
        text_fields(event, ("id", "sport_key", "home_team", "away_team"))
        if event.get("commence_time") is not None and not isinstance(event["commence_time"], str):
            invalid()
        if event["sport_key"] != config["sport"] or not isinstance(event.get("bookmakers"), list):
            invalid()
        for book in event["bookmakers"]:
            text_fields(book, ("key", "title"))
            if book.get("last_update") is not None and not isinstance(book["last_update"], str):
                invalid()
            if not isinstance(book.get("markets"), list):
                invalid()
            for market in book["markets"]:
                text_fields(market, ("key",))
                if market["key"] not in config["markets"].split(",") or not isinstance(market.get("outcomes"), list):
                    invalid()
                if market.get("last_update") is not None and not isinstance(market["last_update"], str):
                    invalid()
                for outcome in market["outcomes"]:
                    text_fields(outcome, ("name",))
                    if not number_or_null(outcome.get("price")) or not number_or_null(outcome.get("point")):
                        invalid()
                    if outcome.get("price") == 0:
                        invalid()
    return events


def csv_bytes(events):
    output = io.BytesIO()

    class LimitedWriter:
        def write(self, text):
            encoded = text.encode("utf-8")
            if output.tell() + len(encoded) > ODDS_MAX_BYTES:
                raise SafeError("CSV output exceeds the size limit. Request fewer markets or regions.")
            output.write(encoded)
            return len(text)

    # Repeated event metadata can make CSV much larger than its JSON input.
    writer = csv.writer(LimitedWriter())
    writer.writerow(CSV_FIELDS)
    for event in events:
        for book in event["bookmakers"]:
            for market in book["markets"]:
                for outcome in market["outcomes"]:
                    writer.writerow((
                        event["id"], event.get("commence_time"), event["sport_key"],
                        event["home_team"], event["away_team"], book["key"], book["title"],
                        book.get("last_update"), market["key"], market.get("last_update"),
                        outcome["name"], outcome.get("price"), outcome.get("point"),
                    ))
    return output.getvalue()


def run(env):
    config = configuration(env)
    verify_private_repository(config)
    query = urlencode({"regions": config["regions"], "markets": config["markets"],
                       "oddsFormat": config["odds_format"], "dateFormat": "iso"})
    data = request_bytes(
        f"https://parlay-api.com/v1/sports/{config['sport']}/odds?{query}",
        {"X-API-Key": config["key"], "Accept": "application/json",
         "User-Agent": "parlayapi-odds-action-v2"}, ODDS_MAX_BYTES, "ParlayAPI",
    )
    events = validate_events(parse_json(data, "ParlayAPI"), config)
    payload = data if config["format"] == "json" else csv_bytes(events)
    private_dir = None
    try:
        private_dir = Path(tempfile.mkdtemp(prefix="parlay-private-", dir=config["temp_root"]))
        os.chmod(private_dir, 0o700)
        target = private_dir / config["filename"]
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(payload)
        with config["output_command"].open("a", encoding="utf-8") as step_output:
            step_output.write(f"file={target}\nevent_count={len(events)}\n")
    except Exception:
        if private_dir is not None:
            shutil.rmtree(private_dir, ignore_errors=True)
        raise SafeError("Could not write the protected runner file. Check runner storage and step output permissions.") from None
    print("Private analysis file ready. Consume it locally and remove it after use.")


def main(env=None):
    try:
        run(os.environ if env is None else env)
        return 0
    except SafeError as error:
        print("::error::" + str(error), file=sys.stderr)
    except Exception:
        print("::error::Action failed. Response content and credentials are withheld.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
