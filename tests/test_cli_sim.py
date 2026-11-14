"""Offline simulator CLI checks use cached calculator extracts, never a transport."""

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from pogo_analyzer import calc_cli, cli, sim_cli
from pogo_analyzer.lineups import EVENT_INFO_URL, PVPOKE_GM_URL
from pogo_analyzer.pokebattler import PoliteClient
from pogo_analyzer.sim import winrate
from pogo_analyzer.sim.rocket import simulate_rocket

FIXTURES = Path(__file__).parent / "fixtures" / "calc"


def write_source(root, url, body):
    client = PoliteClient(root / "sources")
    client._write_cache(
        client.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json"), url, 200, body
    )


def read_source(root, url):
    return json.loads(
        (root / "sources" / (hashlib.sha256(url.encode()).hexdigest() + ".json")).read_text()
    )["body"]


@pytest.fixture
def cache(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    event = json.loads((FIXTURES / "event-info.json").read_text())
    # A synthetic complete lineup, using source species unaltered. Existing extract stays intact.
    event["14"]["encounters"]["third"] = [{"id": 281}]
    write_source(root, EVENT_INFO_URL, event)
    write_source(root, PVPOKE_GM_URL, json.loads((FIXTURES / "gamemaster.json").read_text()))

    def blocked(*args, **kwargs):
        raise AssertionError("cached sim must not attempt a request")

    monkeypatch.setattr(PoliteClient, "_request", blocked)
    return root


def args(cache, fmt="json"):
    return [
        "sim",
        "--character",
        "fai gru",
        "--battle-date",
        "2026-11-14",
        "--trainer-level",
        "50",
        "--attacker",
        "metagross",
        "--level",
        "43.5",
        "--ivs",
        "15/9/12",
        "--fast",
        "BULLET_PUNCH",
        "--charged",
        "METEOR_MASH",
        "--shadow",
        "--cache-dir",
        str(cache),
        "--format",
        fmt,
    ]


def output(cache, capsys, extra=()):
    assert cli.main(args(cache) + list(extra)) == 0
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("fmt", ["table", "json", "csv"])
def test_formats_and_metadata(cache, capsys, fmt):
    assert cli.main(args(cache, fmt)) == 0
    captured = capsys.readouterr()
    text = captured.out
    assert "estimate" in text
    assert "2026-11-14" in text and "mar-2026" in text
    assert "unverified" in text and "parity-only" in text
    if fmt == "json":
        data = json.loads(text)
        assert data["validation"]["validated"] is True
        assert len(data["validation"]["open_discrepancies"]) == 2
        assert {s["url"] for s in data["sources"]} == {EVENT_INFO_URL, PVPOKE_GM_URL}
        assert all(s["fetched_at"] and s["license"] == "MIT" for s in data["sources"])
        assert data["credits"] == calc_cli.CREDITS
        assert data["moveset_pool_note"] == calc_cli.POOL_NOTE
        assert data["rcpm_note"] == calc_cli.CP_ONLY
        (row,) = data["results"]
        assert row["battles"] == row["lineups"] == 6 * (6 + 15) * 15
        assert row["pool_complete"] and row["slot_option_counts"] == [6, 21, 15]
        assert row["wins"] + row["losses"] + row["draws"] == row["battles"]
        assert row["rules_grade"] == "unverified" and row["stats_grade"] == "parity-only"
        # 2026-11-14 is after the newest rules source (29 Sep 2026).
        assert row["grade"] == "estimate; unverified (l); extrapolated forward; stats parity-only"
        assert "l" in row["ledger_rows"] and row["flags"] == ["extrapolated", "unverified"]
        assert all(set(e) == {"row", "grade", "option", "source"} for e in row["evidence"])
        assert row["rules"] == data["rules"]
        assert "weakest" in data["grade_note"]
        assert data["rules"]["rocket_charged"] == "when_ready"
        assert data["rules"]["player_shield_policy"] == "first_two"
    elif fmt == "csv":
        lines = text.splitlines()
        start = next(i for i, s in enumerate(lines) if s.startswith("battle_date,era,rules,"))
        (row,) = list(csv.DictReader(io.StringIO("\n".join(lines[start:]))))
        assert int(row["battles"]) == 1890
        assert json.loads(row["flags"]) == ["extrapolated", "unverified"]
        assert "no appearance-rate source" in captured.err
        assert calc_cli.CREDITS in captured.err
    else:
        assert "slots_swept" in text and "per_slot" in text and "evidence" in text
        assert calc_cli.CREDITS in text and calc_cli.CP_ONLY in text


@pytest.mark.parametrize("fmt", ["table", "json", "csv"])
def test_per_slot_label_every_format(cache, capsys, fmt):
    assert cli.main(args(cache, fmt) + ["--per-slot", "--slot", "2"]) == 0
    text = capsys.readouterr().out
    assert winrate.GRID_NOTE in text
    if fmt == "json":
        data = json.loads(text)
        assert len(data["results"]) == 21
        assert all(r["slot"] == 2 and r["battles"] == 1 for r in data["results"])
        (group,) = data["aggregates"]
        assert group["battles"] == 21
        assert group["win_rate"] == sum(r["winner"] == "player" for r in data["results"]) / 21
        assert all(
            r["grid_limitation"] == winrate.GRID_NOTE for r in data["results"] + data["aggregates"]
        )


@pytest.mark.parametrize("fmt", ["table", "json", "csv"])
def test_unvalidated(cache, capsys, tmp_path, fmt):
    # Missing copied acceptance corpus follows calc's missing-fixtures failure path.
    assert (
        cli.main(
            args(cache, fmt)
            + ["--per-slot", "--slot", "1", "--fixtures-dir", str(tmp_path / "missing")]
        )
        == 0
    )
    text = capsys.readouterr().out
    assert "UNVALIDATED" in text
    if fmt == "json":
        data = json.loads(text)
        assert not data["validation"]["validated"]
        assert all(r["stats_grade"] == "parity-only" for r in data["results"])


@pytest.mark.parametrize("value", ["2026-02-30", "20261114", "today", "2026-W01-1"])
def test_bad_date_rejected_before_sources(cache, capsys, monkeypatch, value):
    monkeypatch.setattr(
        calc_cli, "load_sources", lambda *a: pytest.fail("date must validate first")
    )
    with pytest.raises(SystemExit) as exc:
        cli.main(args(cache) + ["--battle-date", value])
    assert exc.value.code == 2
    assert "date" in capsys.readouterr().err


def test_battle_date_required(cache, capsys):
    argv = args(cache)
    i = argv.index("--battle-date")
    del argv[i : i + 2]
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2
    assert "--battle-date" in capsys.readouterr().err


@pytest.mark.parametrize("option", ["--defender", "--rank"])
def test_no_explicit_defender_or_rank(cache, capsys, option):
    with pytest.raises(SystemExit) as exc:
        cli.main(args(cache) + [option, "snubbull"])
    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_slot_requires_grid(cache, capsys):
    with pytest.raises(SystemExit):
        cli.main(args(cache) + ["--slot", "2"])
    assert "--slot requires --per-slot" in capsys.readouterr().err


def test_exclusion_and_empty_species_visible(cache, capsys):
    gm = read_source(cache, PVPOKE_GM_URL)
    snubbull = next(s for s in gm["pokemon"] if s["speciesId"] == "snubbull")
    snubbull["eliteMoves"] = snubbull["fastMoves"]
    write_source(cache, PVPOKE_GM_URL, gm)
    data = output(cache, capsys, ["--exclude-elite-legacy"])
    assert data["exclude_elite_legacy"] is True
    assert "excluded" in data["filter_note"]
    assert len(data["unresolved"]) == 2
    assert all(
        "empty" in u["reason"] and "--exclude-elite-legacy" in u["reason"]
        for u in data["unresolved"]
    )
    assert data["results"] == []
    assert data["unavailable"][0]["battles"] == 0
    assert data["unavailable"][0]["pool_complete"] is False
    grid_data = output(cache, capsys, ["--per-slot", "--slot", "2", "--exclude-elite-legacy"])
    assert len(grid_data["results"]) == 3 * 4  # Kirlia loses legacy Draining Kiss.
    assert all(r["pool_complete"] is False for r in grid_data["results"])


def test_unresolved_species_and_incomplete_pool(cache, capsys):
    event = read_source(cache, EVENT_INFO_URL)
    event["14"]["encounters"]["second"].append({"id": 9999})
    write_source(cache, EVENT_INFO_URL, event)
    data = output(cache, capsys)
    assert data["unresolved"][0]["species"] == "dex_9999"
    assert data["unresolved"][0]["reason"]
    assert data["results"][0]["pool_complete"] is False
    assert "incomplete" in data["results"][0]["pool_scope"]
    assert data["results"][0]["grade"].endswith("; pool incomplete")


def test_special_move_rejected_as_calc(cache, capsys):
    gm = read_source(cache, PVPOKE_GM_URL)
    next(m for m in gm["moves"] if m["moveId"] == "BITE")["percentMaxHP"] = 0.5
    write_source(cache, PVPOKE_GM_URL, gm)
    with pytest.raises(SystemExit):
        cli.main(args(cache))
    assert "unsupported special move: BITE" in capsys.readouterr().err


@pytest.mark.parametrize(
    "kind,rank", [("Grunt", "grunt"), ("Executive", "leader"), ("Giovanni", "giovanni")]
)
def test_tier_rank_and_direct_battle(cache, capsys, monkeypatch, kind, rank):
    event = read_source(cache, EVENT_INFO_URL)
    event["14"].update(grunt=kind)
    write_source(cache, EVENT_INFO_URL, event)
    calls = []

    def battle(team, rocket, **kwargs):
        calls.append((team, rocket, kwargs))
        return simulate_rocket(team, rocket, **kwargs)

    monkeypatch.setattr(winrate, "simulate_rocket", battle)
    # grid's default argument is deliberately explicit for this spy.
    original_grid = sim_cli.grid
    monkeypatch.setattr(sim_cli, "grid", lambda *a, **k: original_grid(*a, **k, battle=battle))
    data = output(
        cache,
        capsys,
        [
            "--character",
            "Fairy" if kind == "Executive" else "Giovanni" if kind == "Giovanni" else "fai gru",
            "--per-slot",
            "--slot",
            "1",
        ],
    )
    assert len(calls) == 6
    for row, (team, rocket, kwargs) in zip(data["results"], calls, strict=True):
        assert kwargs == dict(
            rank=rank, battle_date="2026-11-14", rules=sim_cli.DEFAULT_ROCKET_RULES
        )
        direct = simulate_rocket(team, rocket, **kwargs)
        assert row["winner"] == direct.winner and row["turns"] == direct.turns_elapsed
        assert row["rank"] == rank
        assert team[0].shadow and team[0].energy == rocket[0].energy == 0


def test_fixed_order_team_forms(cache, capsys, tmp_path, monkeypatch):
    path = tmp_path / "team.json"
    base = dict(
        species="metagross", level=43.5, ivs="15/9/12", fast="BULLET_PUNCH", charged=["METEOR_MASH"]
    )
    path.write_text(json.dumps([dict(base, shadow=True), dict(base, purified=True), base]))
    argv = [
        "sim",
        "--character",
        "fai gru",
        "--battle-date",
        "2026-11-14",
        "--trainer-level",
        "50",
        "--team",
        str(path),
        "--cache-dir",
        str(cache),
        "--format",
        "json",
    ]
    original = sim_cli.simulate_rocket
    calls = []

    def battle(team, rocket, **kw):
        if not calls:
            calls.append((team, rocket, kw))
        return original(team, rocket, **kw)

    monkeypatch.setattr(sim_cli, "simulate_rocket", battle)
    assert cli.main(argv) == 0
    data = json.loads(capsys.readouterr().out)
    own, rocket, kw = calls[0]
    assert [m.shadow for m in own] == [True, False, False]
    assert own[1] == own[2]  # purified stats with supplied IVs, no second IV gain
    assert all(m.energy == 0 for m in own + rocket)
    assert [p["form"] for p in data["results"][0]["team"]] == ["shadow", "purified", "normal"]
    assert len(data["results"][0]["slots_swept"]) == 3
    assert kw["rank"] == "grunt"
    path.write_text(json.dumps([base] * 4))
    with pytest.raises(SystemExit):
        cli.main(argv)
    assert "one to three" in capsys.readouterr().err


def test_grades_use_nested_damage_and_gate(cache, monkeypatch):
    parsed = cli.parser().parse_args(args(cache))
    chars, species, moves, _ = calc_cli.load_sources(cache)
    (attacker,) = calc_cli.build_attackers(calc_cli._team(parsed), species, moves)
    pools, _, records = sim_cli._pools(chars[0], species, moves, parsed)
    option = pools[0][0]
    validation = sim_cli.run_acceptance(parsed.fixtures_dir)
    original = sim_cli.grade_row

    def weaker(*a, **kw):
        row = original(*a, **kw)
        row["rocket_charged"]["value"][0]["damage"]["grade"] = "model"
        return row

    monkeypatch.setattr(sim_cli, "grade_row", weaker)
    assert (
        sim_cli._stats_grade(attacker, option, records[option.species], parsed, "grunt", validation)
        == "model"
    )


def test_multiprocessing_identical_to_serial(monkeypatch):
    from pogo_analyzer.sim.battle import Combatant
    from pogo_analyzer.sim.calculator import Move

    fast = Move("fast", "normal", 2, 1)
    charge = Move("charge", "normal", 10, 1, energy=40)
    team = tuple(Combatant(100, 100, hp, ("normal",), fast, (charge,)) for hp in (40, 90, 160))
    # Distinct Rocket options per slot, so outcomes differ by lineup: a dropped,
    # duplicated or reordered lineup changes the compared sequence.
    pools = tuple(
        tuple(
            winrate.Option(f"s{slot}-{hp}", Combatant(100, 100, hp, ("normal",), fast, (charge,)))
            for hp in (30, 120, 260)
        )
        for slot in range(3)
    )
    serial = list(winrate.trials(team, pools, rank="grunt", battle_date="2026-11-14"))
    assert len({s["winner"] for _, s in serial}) > 1  # Outcomes really vary.
    execution = {}
    monkeypatch.setattr(sim_cli, "PARALLEL_AFTER", -1)
    monkeypatch.setattr(sim_cli, "_cpus", lambda: 2)
    parallel = list(
        sim_cli._timed_trials(
            team, pools, rank="grunt", battle_date="2026-11-14", execution=execution
        )
    )

    def names(trials):
        return [([o.species for o in lineup], summary) for lineup, summary in trials]

    assert names(serial) == names(parallel)
    assert winrate.aggregate(team, serial) == winrate.aggregate(team, parallel)
    assert execution["mode"] == "serial then stdlib multiprocessing"
    # Two CPUs: one worker plus the parent.
    assert execution["workers"] == 1 and execution["processes"] == 2


def test_cpus_respect_affinity(monkeypatch):
    if not hasattr(sim_cli.os, "sched_getaffinity"):
        pytest.skip("no CPU affinity on this platform")
    monkeypatch.setattr(sim_cli.os, "sched_getaffinity", lambda pid: {0, 1})
    monkeypatch.setattr(sim_cli.os, "cpu_count", lambda: 64)
    assert sim_cli._cpus() == 2 and sim_cli._workers() == 1


@pytest.mark.parametrize("cpus,workers", [(None, 0), (1, 0), (2, 1), (4, 3), (64, 3)])
def test_worker_count_counts_the_parent(monkeypatch, cpus, workers):
    # Never more than four processes in all, the parent included.
    monkeypatch.setattr(sim_cli, "_cpus", lambda: cpus)
    assert sim_cli._workers() == workers
    assert sim_cli._workers() + 1 <= sim_cli.MAX_PROCESSES


def test_one_cpu_stays_serial(monkeypatch):
    from pogo_analyzer.sim.battle import Combatant
    from pogo_analyzer.sim.calculator import Move

    member = Combatant(100, 100, 100, ("normal",), Move("fast", "normal", 2, 1), ())
    pools = tuple(tuple(winrate.Option(str(i), member) for i in range(2)) for _ in range(3))
    execution = {}
    monkeypatch.setattr(sim_cli, "PARALLEL_AFTER", -1)
    monkeypatch.setattr(sim_cli, "_cpus", lambda: 1)
    list(
        sim_cli._timed_trials(
            (member,), pools, rank="grunt", battle_date="2026-11-14", execution=execution
        )
    )
    assert execution["mode"] == "serial" and execution["workers"] == 1


def test_pool_context_avoids_helper_process():
    import multiprocessing

    expected = "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
    assert sim_cli._pool_context().get_start_method() == expected


def _with_date(cache, stamp, fmt="json"):
    argv = args(cache, fmt)
    argv[argv.index("--battle-date") + 1] = stamp
    return argv


def test_battle_date_before_rocket_battles_is_rejected(cache, capsys):
    # Team GO Rocket grunt battles first appeared on 2019-07-22.
    with pytest.raises(SystemExit):
        cli.main(_with_date(cache, "2019-07-21"))
    assert "before Team GO Rocket battles began" in capsys.readouterr().err


def test_dates_within_sources_are_not_extrapolated(cache, capsys):
    assert cli.main(_with_date(cache, "2026-09-29")) == 0
    row = json.loads(capsys.readouterr().out)["results"][0]
    assert row["flags"] == ["unverified"]
    assert row["grade"] == "estimate; unverified (l); stats parity-only"


def test_large_selection_warns(cache, capsys, monkeypatch):
    monkeypatch.setattr(sim_cli, "LARGE_SELECTION", 1)
    assert cli.main(args(cache)) == 0
    assert "lineups across" in capsys.readouterr().err


def test_grid_table_shows_player_slot(cache, capsys):
    assert cli.main(args(cache, "table") + ["--per-slot", "--slot", "1"]) == 0
    text = capsys.readouterr().out
    headers = [line for line in text.splitlines() if line.split("|")[0].strip() == "character"]
    assert len(headers) == 2 and all("player_slot" in line for line in headers)


def test_headline_never_repeats_estimate():
    row = {"rules_grade": "estimate", "flags": [], "pool_complete": True}
    assert sim_cli._grade(row, "model")["grade"] == "estimate; stats model"


def test_workers_ignore_interrupt():
    import signal

    previous = signal.getsignal(signal.SIGINT)
    try:
        sim_cli._ignore_interrupt()
        assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
    finally:
        signal.signal(signal.SIGINT, previous)
