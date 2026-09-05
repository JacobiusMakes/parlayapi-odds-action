"""Offline transport/command tests. Unit fixtures below are not market quotes."""

import copy
import csv
import io
import json
import os
from pathlib import Path
import signal
import socket
import stat
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, build_opener

import fetch_odds as action


PRIVATE = {"full_name": "unit-owner/private-project", "private": True, "visibility": "private"}
# Deliberately non-market unit data: no fabricated sports prices or real quotes.
EVENTS = [{
    "id": "unit-event", "sport_key": "baseball_mlb", "commence_time": "unit-time",
    "home_team": "PRIVATE_HOME_CANARY", "away_team": "PRIVATE_AWAY_CANARY",
    "bookmakers": [{"key": "unit-book", "title": "PRIVATE_BOOK_CANARY", "last_update": "unit-source-time",
                    "markets": [{"key": "h2h", "outcomes": [
                        {"name": "PRIVATE_OUTCOME_CANARY", "price": None},
                    ]}]}],
}]
KEY = "UNIT_API_SECRET_CANARY"
TOKEN = "UNIT_GITHUB_TOKEN_CANARY"


class Response(io.BytesIO):
    def __init__(self, data, url, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.url = url
        self.headers = {} if headers is None else headers

    def geturl(self):
        return self.url


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        base = Path(self.root.name)
        (base / "workspace").mkdir()
        (base / "runner-temp").mkdir()
        (base / "step-output").touch()
        self.env = {
            "ODDS_GITHUB_REPOSITORY": PRIVATE["full_name"],
            "ODDS_GITHUB_SERVER_URL": "https://github.com",
            "ODDS_GITHUB_TOKEN": TOKEN, "PARLAY_API_KEY": KEY,
            "ODDS_WORKSPACE": str(base / "workspace"),
            "ODDS_RUNNER_TEMP": str(base / "runner-temp"),
            "GITHUB_OUTPUT": str(base / "step-output"),
            "PARLAY_SPORT": "baseball_mlb",
        }
        self.network = patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden in unit tests"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def invoke(self, repository=PRIVATE, events=EVENTS, failure=None, fail_at=0, overrides=None):
        calls = []
        output = io.StringIO()
        error = io.StringIO()
        env = dict(self.env, **(overrides or {}))
        Path(env["GITHUB_OUTPUT"]).write_text("")

        def open_response(request, timeout):
            calls.append(request)
            self.assertEqual(timeout, action.REQUEST_SECONDS)
            if failure is not None and len(calls) == fail_at + 1:
                raise failure
            body = repository if len(calls) == 1 else events
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            return Response(data, request.full_url)

        opener = Mock()
        opener.open.side_effect = open_response
        with patch.object(action, "build_opener", return_value=opener) as build, redirect_stdout(output), redirect_stderr(error):
            code = action.main(env)
        for build_call in build.call_args_list:
            proxy, redirect = build_call.args
            self.assertEqual(proxy.proxies, {})
            self.assertIsInstance(redirect, action.NoRedirect)
        logs = output.getvalue() + error.getvalue()
        for forbidden in (KEY, TOKEN, "PRIVATE_HOME_CANARY", "PRIVATE_AWAY_CANARY",
                          "PRIVATE_BOOK_CANARY", "PRIVATE_OUTCOME_CANARY", "PROVIDER_BODY_CANARY"):
            self.assertNotIn(forbidden, logs)
        outputs = dict(line.split("=", 1) for line in Path(env["GITHUB_OUTPUT"]).read_text().splitlines())
        return code, calls, outputs, logs

    def test_private_json_order_origins_header_separation_and_permissions(self):
        code, calls, outputs, _ = self.invoke(overrides={
            "PARLAY_BASE_URL": "https://untrusted.invalid", "HTTPS_PROXY": "https://untrusted.invalid",
        })
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].full_url, "https://api.github.com/repos/" + PRIVATE["full_name"])
        self.assertEqual(calls[1].full_url, "https://parlay-api.com/v1/sports/baseball_mlb/odds?regions=us&markets=h2h&oddsFormat=american&dateFormat=iso")
        self.assertEqual(calls[0].get_header("Authorization"), "Bearer " + TOKEN)
        self.assertIsNone(calls[0].get_header("X-api-key"))
        self.assertEqual(calls[1].get_header("X-api-key"), KEY)
        self.assertIsNone(calls[1].get_header("Authorization"))
        self.assertNotIn(KEY, calls[1].full_url)
        target = Path(outputs["file"])
        self.assertEqual(json.loads(target.read_bytes()), EVENTS)
        self.assertEqual(outputs["event_count"], "1")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o700)
        self.assertEqual(target.parent.parent, Path(self.env["ODDS_RUNNER_TEMP"]).resolve())
        self.assertNotIn(Path(self.env["ODDS_WORKSPACE"]).resolve(), target.parents)

    def test_public_internal_missing_and_mismatched_repo_never_call_odds(self):
        variants = [None, [], {}, dict(PRIVATE, private=False), dict(PRIVATE, private=1),
                    dict(PRIVATE, private="true"), dict(PRIVATE, visibility="internal"),
                    dict(PRIVATE, visibility="public"), dict(PRIVATE, visibility=None),
                    dict(PRIVATE, full_name="unit-owner/another-project"),
                    {"full_name": PRIVATE["full_name"], "private": True}]
        for repository in variants:
            with self.subTest(repository=repository):
                code, calls, outputs, _ = self.invoke(repository=repository)
                self.assertEqual(code, 1)
                self.assertEqual(len(calls), 1)
                self.assertEqual(outputs, {})

    def test_github_errors_never_call_odds_or_print_body(self):
        for status in (301, 302, 307, 308, 401, 403, 404, 429, 503):
            with self.subTest(status=status):
                failure = HTTPError("https://api.github.com/", status, "PROVIDER_BODY_CANARY", {}, io.BytesIO(KEY.encode()))
                code, calls, outputs, logs = self.invoke(failure=failure)
                self.assertEqual(code, 1)
                self.assertEqual(len(calls), 1)
                self.assertEqual(outputs, {})
                self.assertIn("HTTP " + str(status), logs)
        code, calls, _, _ = self.invoke(failure=TimeoutError("PROVIDER_BODY_CANARY"))
        self.assertEqual((code, len(calls)), (1, 1))

    def test_github_malformed_duplicate_and_oversized_responses_fail_closed(self):
        bodies = [b"PROVIDER_BODY_CANARY", b'{"private":true,"private":false}',
                  b'{"private":NaN}', b"[" * 2000, b" " * (action.GITHUB_MAX_BYTES + 1)]
        for body in bodies:
            with self.subTest(length=len(body)):
                code, calls, outputs, _ = self.invoke(repository=body)
                self.assertEqual((code, len(calls), outputs), (1, 1, {}))

    def test_empty_json_is_success_and_csv_missing_values_preserve_point_zero(self):
        code, _, outputs, _ = self.invoke(events=[])
        self.assertEqual(code, 0)
        self.assertEqual(outputs["event_count"], "0")
        self.assertEqual(json.loads(Path(outputs["file"]).read_text()), [])
        events = copy.deepcopy(EVENTS)
        market = events[0]["bookmakers"][0]["markets"][0]
        market["key"] = "spreads"
        market["outcomes"].append({"name": "unit-zero-point", "price": None, "point": 0})
        market["outcomes"].append({"name": "unit-null-point", "price": None, "point": None})
        code, _, outputs, _ = self.invoke(events=events, overrides={
            "PARLAY_FORMAT": "csv", "PARLAY_OUTPUT": "private.csv", "PARLAY_MARKETS": "spreads",
        })
        self.assertEqual(code, 0)
        rows = list(csv.DictReader(io.StringIO(Path(outputs["file"]).read_text())))
        self.assertEqual(len(rows), 3)
        self.assertEqual([row["point"] for row in rows], ["", "0", ""])
        self.assertEqual([row["price"] for row in rows], ["", "", ""])
        self.assertEqual(rows[0]["market_last_update"], "")
        self.assertEqual(rows[0]["bookmaker_last_update"], "unit-source-time")
        self.assertEqual(rows[0]["outcome"], "PRIVATE_OUTCOME_CANARY")

    def test_odds_errors_malformed_and_timeouts_never_publish_outputs(self):
        for status in (301, 302, 307, 308, 401, 403, 429, 503):
            with self.subTest(status=status):
                failure = HTTPError("https://parlay-api.com/", status, KEY, {}, io.BytesIO(b"PROVIDER_BODY_CANARY"))
                code, calls, outputs, _ = self.invoke(failure=failure, fail_at=1)
                self.assertEqual((code, len(calls), outputs), (1, 2, {}))
        for events in (b"PROVIDER_BODY_CANARY", {}, {"events": EVENTS}, [None], b" " * (action.ODDS_MAX_BYTES + 1)):
            with self.subTest(shape=type(events).__name__):
                code, calls, outputs, _ = self.invoke(events=events)
                self.assertEqual((code, len(calls), outputs), (1, 2, {}))
        code, calls, outputs, _ = self.invoke(failure=TimeoutError(KEY), fail_at=1)
        self.assertEqual((code, len(calls), outputs), (1, 2, {}))
        self.assertEqual(list(Path(self.env["ODDS_RUNNER_TEMP"]).iterdir()), [])

    def test_unknown_commence_time_stays_unknown(self):
        for missing in (True, False):
            events = copy.deepcopy(EVENTS)
            if missing:
                del events[0]["commence_time"]
            else:
                events[0]["commence_time"] = None
            for output_format in ("json", "csv"):
                with self.subTest(missing=missing, output_format=output_format):
                    code, _, outputs, _ = self.invoke(events=events, overrides={"PARLAY_FORMAT": output_format})
                    self.assertEqual(code, 0)
                    text = Path(outputs["file"]).read_text()
                    if output_format == "json":
                        self.assertEqual(json.loads(text), events)
                    else:
                        self.assertEqual(list(csv.DictReader(io.StringIO(text)))[0]["commence_time"], "")
        for invalid_time in (123, True, [], {}):
            with self.subTest(invalid_time=invalid_time):
                events = copy.deepcopy(EVENTS)
                events[0]["commence_time"] = invalid_time
                code, _, outputs, _ = self.invoke(events=events)
                self.assertEqual((code, outputs), (1, {}))

    def test_invalid_inputs_do_not_make_any_request(self):
        cases = [
            ("PARLAY_API_KEY", ""), ("PARLAY_API_KEY", KEY + "\r\nX-Evil: yes"),
            ("ODDS_GITHUB_TOKEN", TOKEN + "\n"), ("ODDS_GITHUB_TOKEN", "é"),
            ("ODDS_GITHUB_SERVER_URL", "https://github.example.com"),
            ("ODDS_GITHUB_REPOSITORY", "owner/../private"),
            ("ODDS_GITHUB_REPOSITORY", "owner/private?other=true"),
            ("PARLAY_SPORT", "../sports"), ("PARLAY_SPORT", "baseball_mlb?apiKey=bad"),
            ("PARLAY_SPORT", "baseball_mlb\n"), ("PARLAY_REGIONS", "us,unknown"),
            ("PARLAY_REGIONS", "us,us"), ("PARLAY_MARKETS", "h2h, h2h"),
            ("PARLAY_MARKETS", "props"), ("PARLAY_ODDS_FORMAT", "wrong"),
            ("PARLAY_FORMAT", "wrong"), ("PARLAY_OUTPUT", "../odds.json"),
            ("PARLAY_OUTPUT", "folder/odds.json"), ("PARLAY_OUTPUT", "folder\\odds.json"),
            ("PARLAY_OUTPUT", "/tmp/odds.json"), ("PARLAY_OUTPUT", "odds.json\nfile=bad"),
            ("PARLAY_OUTPUT", ".git"), ("ODDS_RUNNER_TEMP", ""),
            ("ODDS_RUNNER_TEMP", self.env["ODDS_WORKSPACE"]),
        ]
        for name, value in cases:
            with self.subTest(name=name, value=value):
                code, calls, outputs, _ = self.invoke(overrides={name: value})
                self.assertEqual((code, calls, outputs), (1, [], {}))

    def test_symlink_temp_inside_checkout_is_rejected(self):
        target = Path(self.env["ODDS_WORKSPACE"]) / "inside"
        target.mkdir()
        link = Path(self.root.name) / "linked-temp"
        link.symlink_to(target, target_is_directory=True)
        code, calls, _, _ = self.invoke(overrides={"ODDS_RUNNER_TEMP": str(link)})
        self.assertEqual((code, calls), (1, []))

    def test_invalid_nested_source_values_fail_without_substitution(self):
        for value in (True, "100", 0, float("inf")):
            events = copy.deepcopy(EVENTS)
            events[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] = value
            with self.subTest(price=value):
                code, _, outputs, _ = self.invoke(events=events)
                self.assertEqual((code, outputs), (1, {}))
        events = copy.deepcopy(EVENTS)
        events[0]["sport_key"] = "soccer_epl"
        code, _, outputs, _ = self.invoke(events=events)
        self.assertEqual((code, outputs), (1, {}))

    def test_output_failure_removes_only_new_private_directory(self):
        existing = Path(self.env["ODDS_RUNNER_TEMP"]) / "existing-file"
        existing.write_text("keep")
        real_open = os.open

        def fail_target(path, flags, *args, **kwargs):
            if str(path).endswith("odds.json"):
                raise OSError(KEY)
            return real_open(path, flags, *args, **kwargs)

        with patch.object(action.os, "open", side_effect=fail_target):
            code, calls, outputs, _ = self.invoke()
        self.assertEqual((code, len(calls), outputs), (1, 2, {}))
        self.assertEqual(list(Path(self.env["ODDS_RUNNER_TEMP"]).iterdir()), [existing])


class TransportTests(unittest.TestCase):
    def test_redirect_handlers_never_construct_followup_requests(self):
        handler = action.NoRedirect()
        opener = build_opener(handler)
        request = Request("https://parlay-api.com/", headers={"X-API-Key": KEY})
        for code in (301, 302, 303, 307, 308):
            with self.subTest(code=code), self.assertRaises(HTTPError) as raised:
                opener.error("http", request, io.BytesIO(), code, "redirect", {"location": "https://untrusted.invalid/"})
            raised.exception.close()

    def test_size_headers_and_unexpected_response_origin(self):
        for headers, url in (({"Content-Length": "999"}, "https://parlay-api.com/"),
                             ({"Content-Length": "invalid"}, "https://parlay-api.com/"),
                             ({"Content-Length": "3"}, "https://parlay-api.com/"),
                             ({}, "https://untrusted.invalid/")):
            with self.subTest(headers=headers, url=url):
                opener = Mock()
                opener.open.return_value = Response(b"{}", url, headers=headers)
                with patch.object(action, "build_opener", return_value=opener), self.assertRaises(action.SafeError):
                    action.request_bytes("https://parlay-api.com/", {}, 10, "ParlayAPI")

    def test_csv_expansion_has_a_byte_limit(self):
        with patch.object(action, "ODDS_MAX_BYTES", 200), self.assertRaises(action.SafeError):
            action.csv_bytes(EVENTS)

    def test_total_deadline_is_enforced_and_cancelled(self):
        before = signal.getsignal(signal.SIGALRM)
        with patch.object(action, "REQUEST_SECONDS", 0.01), self.assertRaises(TimeoutError):
            with action.request_deadline():
                time.sleep(0.1)
        self.assertEqual(signal.getsignal(signal.SIGALRM), before)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
