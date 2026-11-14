"""Exercise CLI failure handling with the real client and offline transports."""

import csv
import io
import json
import os
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import pytest

from pogo_analyzer import cli, lineups, pokebattler
from pogo_analyzer.pokebattler import PoliteClient, build_rocket_url

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
        (IncompleteRead(b"partial", 100), "network error"),
        (400, "HTTP 400"),
        (302, "HTTP 302"),
        (b"<html>maintenance</html>", "invalid JSON"),
    ],
)
def test_client_errors_exit_cleanly(transport, tmp_path, capsys, failure, message):
    calls, clients = transport(lambda url: failure)
    assert cli.main(counter_args(tmp_path)) == 5
    captured = capsys.readouterr()
    assert json.loads(captured.out)["results"] == []
    assert "Not fetched: TEST (RAID_LEVEL_1)" in captured.err
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
@pytest.mark.parametrize(
    ("failure", "exit_code"),
    [("budget", 4), (429, 3), (URLError("offline"), 5), (400, 5), (b"bad JSON", 5)],
)
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
            return 429 if failure == "budget" else failure
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
    if failure == 429:
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


@pytest.mark.parametrize("command", ["counters", "tally"])
@pytest.mark.parametrize("fmt", ["json", "csv", "table"])
@pytest.mark.parametrize(
    ("failure", "exit_code"),
    [
        ("budget_zero", 4),
        ("budget", 4),
        (429, 3),
        (URLError("offline"), 5),
        (400, 5),
        (b"bad JSON", 5),
        ("cache_write", 6),
    ],
)
def test_stop_continues_from_cache_only(
    transport,
    tmp_path,
    monkeypatch,
    capsys,
    command,
    fmt,
    failure,
    exit_code,
):
    data = three_defenders()
    data["1"]["encounters"]["first"].append({"id": 122, "template": "FOURTH"})

    def reply(url):
        if url == lineups.EVENT_INFO_URL:
            return data
        if url == lineups.PVPOKE_GM_URL:
            return fixture("species.json")
        if "/SECOND/" in url and not isinstance(failure, str):
            return failure
        return fixture("rocket_counters_sample.json")

    calls, clients = transport(reply)
    lineups.load_lineups(PoliteClient(tmp_path / "sources", min_interval=0))
    seed = PoliteClient(tmp_path)
    # Only the fallback ID is cached for THIRD, whose primary ID is a miss.
    seed.get_json(build_rocket_url("THIRD_FORM", "RAID_LEVEL_1", 40))
    if failure == "budget_zero":
        seed.get_json(build_rocket_url("FIRST", "RAID_LEVEL_1", 40))
    if failure == "cache_write":
        second_url = build_rocket_url("SECOND", "RAID_LEVEL_1", 40)
        second_name = pokebattler.hashlib.sha256(second_url.encode()).hexdigest() + ".json"
        original_replace = pokebattler.os.replace

        def replace(source, destination):
            if destination.name == second_name:
                raise OSError("cache disk full")
            original_replace(source, destination)

        monkeypatch.setattr(pokebattler.os, "replace", replace)
    calls.clear()
    clients.clear()
    budget = "0" if failure == "budget_zero" else "1" if failure == "budget" else "10"
    assert (
        cli.main(
            [
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
                budget,
            ]
        )
        == exit_code
    )
    captured = capsys.readouterr()
    if fmt == "json":
        rows = json.loads(captured.out)["results"]
    elif fmt == "csv":
        rows = list(csv.DictReader(io.StringIO(captured.out)))
    else:
        fields, *lines = captured.out.splitlines()[:-1]
        rows = [dict(zip(fields.split(" | "), line.split(" | "), strict=True)) for line in lines]
    if command == "counters":
        assert {row["defender"] for row in rows} == {"FIRST", "THIRD_FORM"}
    else:
        assert len(rows) == 1
        assert int(rows[0]["count"]) == 2
        assert rows[0]["defenders"] == "FIRST (RAID_LEVEL_1), THIRD_FORM (RAID_LEVEL_1)"
    assert "Not fetched: SECOND, SECOND_FORM (RAID_LEVEL_1)" in captured.err
    assert "Not fetched: FOURTH, FOURTH_FORM (RAID_LEVEL_1)" in captured.err
    assert "Not fetched: FIRST" not in captured.err
    assert "Not fetched: THIRD" not in captured.err
    assert sum(line.startswith("stopped:") for line in captured.err.splitlines()) == 1
    assert not any("/THIRD" in url or "/FOURTH" in url for url in calls)
    expected = 0 if failure == "budget_zero" else 1 if failure == "budget" else 2
    assert len(calls) == clients[1].network_requests == expected
    assert clients[1].cache_only


@pytest.mark.parametrize("failure", [URLError("offline"), 400, b"bad JSON"])
@pytest.mark.parametrize("source_url", [lineups.EVENT_INFO_URL, lineups.PVPOKE_GM_URL])
def test_lineup_source_failure_has_no_rows(transport, tmp_path, capsys, failure, source_url):
    transport(lambda url: failure if url == source_url else fixture("lineups.json"))
    assert cli.main(["counters", "--character", "fire", "--cache-dir", str(tmp_path)]) == 5
    captured = capsys.readouterr()
    assert not captured.out
    assert len(captured.err.splitlines()) == 1
    assert "raw.githubusercontent.com" in captured.err


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write chmod read-only directories")
@pytest.mark.parametrize("source_failure", [False, True])
def test_read_only_cache_exits_six(transport, tmp_path, capsys, source_failure):
    calls, clients = transport(lambda url: fixture("rocket_counters_sample.json"))
    cache_dir = tmp_path / "read-only"
    cache_dir.mkdir()
    cache_dir.chmod(0o555)
    try:
        args = (
            ["counters", "--character", "fire", "--cache-dir", str(cache_dir)]
            if source_failure
            else counter_args(cache_dir)
        )
        assert cli.main(args) == 6
    finally:
        cache_dir.chmod(0o755)
    captured = capsys.readouterr()
    expected_path = cache_dir / ("sources" if source_failure else ".pace.lock")
    assert f"stopped: cache error at {expected_path}:" in captured.err
    assert "Permission denied" in captured.err
    assert "network error" not in captured.err
    assert "Traceback" not in captured.err
    assert not calls
    assert all(client.network_requests == 0 for client in clients)
    if source_failure:
        assert not captured.out
    else:
        assert json.loads(captured.out)["results"] == []


def test_cached_404s_are_unresolved_after_stop(transport, tmp_path, capsys):
    def reply(url):
        if url == lineups.EVENT_INFO_URL:
            return three_defenders()
        if url == lineups.PVPOKE_GM_URL:
            return fixture("species.json")
        return 404

    calls, clients = transport(reply)
    lineups.load_lineups(PoliteClient(tmp_path / "sources", min_interval=0))
    seed = PoliteClient(tmp_path)
    for candidate in ("SECOND", "SECOND_FORM"):
        with pytest.raises(pokebattler.NotFound):
            seed.get_json(build_rocket_url(candidate, "RAID_LEVEL_1", 40))
    calls.clear()
    clients.clear()
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
                "--max-requests",
                "0",
            ]
        )
        == 4
    )
    captured = capsys.readouterr()
    assert json.loads(captured.out)["results"] == []
    assert "Unresolved defender: SECOND, SECOND_FORM" in captured.err
    assert "Not fetched: SECOND" not in captured.err
    assert "Not fetched: FIRST" in captured.err
    assert "Not fetched: THIRD" in captured.err
    assert not calls


@pytest.mark.parametrize(("failure", "exit_code"), [("budget", 4), (429, 3), (400, 5)])
def test_later_cache_error_preserves_first_stop_code(
    transport,
    tmp_path,
    monkeypatch,
    capsys,
    failure,
    exit_code,
):
    def reply(url):
        if url == lineups.EVENT_INFO_URL:
            return three_defenders()
        if url == lineups.PVPOKE_GM_URL:
            return fixture("species.json")
        if "/SECOND/" in url:
            return failure
        return fixture("rocket_counters_sample.json")

    calls, clients = transport(reply)
    original_read = PoliteClient._read_cache

    def read(self, path, url):
        if self.cache_only and "/THIRD/" in url:
            raise pokebattler.CacheError(path, "permission denied")
        return original_read(self, path, url)

    monkeypatch.setattr(PoliteClient, "_read_cache", read)
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
                "--max-requests",
                "1" if failure == "budget" else "10",
            ]
        )
        == exit_code
    )
    captured = capsys.readouterr()
    assert {row["defender"] for row in json.loads(captured.out)["results"]} == {"FIRST"}
    assert "Not fetched: SECOND" in captured.err
    assert "Not fetched: THIRD" in captured.err
    assert sum(line.startswith("stopped:") for line in captured.err.splitlines()) == 1
    assert clients[1].network_requests == (1 if failure == "budget" else 2)
    assert not any("/THIRD" in url for url in calls)
