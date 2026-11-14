"""Exercise CLI failure handling with the real client and offline transports."""

import csv
import io
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import pytest

from pogo_analyzer import cli, lineups
from pogo_analyzer.pokebattler import PoliteClient

FIXTURES = Path(__file__).parent / "fixtures"


class Response(io.BytesIO):
    status = 200


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def transport(monkeypatch):
    """Inject only I/O and time; preserve PoliteClient's real error handling."""
    original_init = PoliteClient.__init__
    now = [100.0]
    calls = []
    clients = []

    def install(reply):
        def opener(request, timeout):
            calls.append(request.full_url)
            value = reply(request.full_url)
            if isinstance(value, Exception):
                raise value
            if isinstance(value, int):
                raise HTTPError(request.full_url, value, "test response", {}, io.BytesIO())
            if isinstance(value, bytes):
                return Response(value)
            return Response(json.dumps(value).encode())

        def sleep(delay):
            now[0] += delay

        def init(self, *args, **kwargs):
            original_init(
                self,
                *args,
                **kwargs,
                opener=opener,
                clock=lambda: now[0],
                wall_clock=lambda: now[0],
                sleep=sleep,
            )
            clients.append(self)

        monkeypatch.setattr(PoliteClient, "__init__", init)
        return calls, clients

    return install


def counter_args(tmp_path, fmt="json"):
    return [
        "counters",
        "--defender",
        "TEST",
        "--tier",
        "RAID_LEVEL_1",
        "--format",
        fmt,
        "--cache-dir",
        str(tmp_path),
    ]


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (URLError("DNS unavailable"), "network error"),
        (TimeoutError("timed out"), "network error"),
        (OSError("connection lost"), "network error"),
        (400, "HTTP 400"),
        (302, "HTTP 302"),
        (b"<html>maintenance</html>", "invalid JSON"),
    ],
)
def test_client_errors_exit_cleanly(transport, tmp_path, capsys, failure, message):
    calls, clients = transport(lambda url: failure)
    assert cli.main(counter_args(tmp_path)) == 5
    captured = capsys.readouterr()
    assert not captured.out
    assert len(captured.err.splitlines()) == 1
    assert "fight.pokebattler.com" in captured.err
    assert message in captured.err
    assert "Traceback" not in captured.err
    assert len(calls) == 1
    assert clients[1].network_requests == 1


@pytest.mark.parametrize("source_url", [lineups.EVENT_INFO_URL, lineups.PVPOKE_GM_URL])
@pytest.mark.parametrize(("status", "exit_code"), [(404, 5), (429, 3)])
def test_source_errors_name_github(transport, tmp_path, capsys, source_url, status, exit_code):
    def reply(url):
        return status if url == source_url else fixture("lineups.json")

    calls, clients = transport(reply)
    assert cli.main(["lineups", "--cache-dir", str(tmp_path)]) == exit_code
    captured = capsys.readouterr()
    assert not captured.out
    assert len(captured.err.splitlines()) == 1
    assert f"raw.githubusercontent.com returned HTTP {status}" in captured.err
    assert "Pokebattler" not in captured.err
    assert "Traceback" not in captured.err
    assert clients[0].network_requests == len(calls)
    if status == 429:
        assert f"after {len(calls)} requests; try again later" in captured.err


def three_defenders():
    data = fixture("lineups.json")
    data["1"]["encounters"] = {
        "first": [
            {"id": 122, "template": "FIRST"},
            {"id": 110, "template": "SECOND"},
            {"id": 122, "template": "THIRD"},
        ],
    }
    return data


@pytest.mark.parametrize("command", ["counters", "tally"])
@pytest.mark.parametrize("fmt", ["table", "csv", "json"])
@pytest.mark.parametrize(("failure", "exit_code"), [("budget", 4), ("blocked", 3)])
def test_mid_run_stop_preserves_results_and_names_remaining(
    transport,
    tmp_path,
    capsys,
    command,
    fmt,
    failure,
    exit_code,
):
    def reply(url):
        if url == lineups.EVENT_INFO_URL:
            return three_defenders()
        if url == lineups.PVPOKE_GM_URL:
            return fixture("species.json")
        if "/SECOND/" in url:
            return 429
        return fixture("rocket_counters_sample.json")

    calls, clients = transport(reply)
    args = [
        command,
        "--character",
        "fire",
        "--slot",
        "1",
        "--top",
        "1",
        "--format",
        fmt,
        "--cache-dir",
        str(tmp_path),
        "--max-requests",
        "1" if failure == "budget" else "10",
    ]
    assert cli.main(args) == exit_code
    captured = capsys.readouterr()
    assert "GAMMA" in captured.out
    if fmt == "json":
        rows = json.loads(captured.out)["results"]
    elif fmt == "csv":
        rows = list(csv.DictReader(io.StringIO(captured.out)))
        assert cli.CREDITS not in captured.out
    else:
        rows = None
        assert cli.CREDITS in captured.out
    if rows is not None:
        assert len(rows) == 1
        assert rows[0]["defender" if command == "counters" else "defenders"].startswith("FIRST")
    assert "Not fetched: SECOND, SECOND_FORM (RAID_LEVEL_1)" in captured.err
    assert "Not fetched: THIRD, THIRD_FORM (RAID_LEVEL_1)" in captured.err
    assert "Not fetched: FIRST" not in captured.err
    assert not any("/THIRD" in url for url in calls)
    assert clients[1].network_requests == (1 if failure == "budget" else 2)
    if failure == "blocked":
        assert "fight.pokebattler.com returned HTTP 429 after 4 requests; try again later" in (
            captured.err
        )
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "bad_response",
    [{"attackers": []}, {"attackers": [{"pokemonId": "SECOND"}]}, None, []],
)
def test_unparseable_defender_is_unresolved_and_run_continues(
    transport,
    tmp_path,
    capsys,
    bad_response,
):
    def reply(url):
        if url == lineups.EVENT_INFO_URL:
            return three_defenders()
        if url == lineups.PVPOKE_GM_URL:
            return fixture("species.json")
        if "/SECOND/" in url:
            return bad_response
        return fixture("rocket_counters_sample.json")

    calls, _ = transport(reply)
    assert (
        cli.main(
            [
                "counters",
                "--character",
                "fire",
                "--slot",
                "1",
                "--format",
                "json",
                "--cache-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    rows = json.loads(captured.out)["results"]
    assert {row["defender"] for row in rows} == {"FIRST", "THIRD"}
    assert "Unresolved defender: SECOND (RAID_LEVEL_1)" in captured.err
    assert any("/THIRD/" in url for url in calls)
    assert all(urlsplit(url).scheme == "https" for url in calls)
