"""Small, offline static reports; never renice the runner or use more than two workers."""

import copy
import fcntl
import hashlib
import json
import multiprocessing
from datetime import date

import pytest
from test_cli_topn import cache as cache
from test_cli_topn import read_source, write_source

from pogo_analyzer import calc_cli, cli, precompute, sim_cli, topn, topn_cli
from pogo_analyzer.lineups import EVENT_INFO_URL, PVPOKE_GM_URL

_ORIGINAL_SCREEN = topn.screen_candidate


def _favor_by_rank(candidate, pools, *, rank, **kwargs):
    row = _ORIGINAL_SCREEN(candidate, pools, rank=rank, **kwargs)
    row["score"] = int(candidate.species_id == ("metagross" if rank == "grunt" else "kirlia"))
    return row


@pytest.fixture(autouse=True)
def priority(monkeypatch):
    calls = []
    monkeypatch.setattr(precompute.os, "nice", lambda value: calls.append(value) or 17)
    monkeypatch.setattr(precompute.os, "getpriority", lambda *args: 7)
    return calls


@pytest.fixture
def characters(cache):
    event = read_source(cache, EVENT_INFO_URL)
    event["15"] = copy.deepcopy(event["14"])
    event["15"].update(type="Cliff", grunt="Executive")
    event["16"] = copy.deepcopy(event["14"])
    event["16"].update(type="Empty")
    event["16"]["encounters"]["third"] = []
    event["14"]["encounters"]["second"].append({"id": 9999})
    write_source(cache, EVENT_INFO_URL, event)
    return cache


def argv(cache, out, *extra):
    return [
        "precompute",
        "--out",
        str(out),
        "--battle-date",
        "2026-11-14",
        "--cache-dir",
        str(cache),
        "--workers",
        "1",
        "--level",
        "40",
        "--k",
        "1",
        "--candidates",
        "metagross,kirlia",
        *extra,
    ]


def run(cache, out, *extra):
    assert cli.main(argv(cache, out, *extra)) == 0
    return json.loads((out / "manifest.json").read_text())


def report_files(out):
    return {str(p.relative_to(out)): json.loads(p.read_text()) for p in out.rglob("*.json")}


def assert_no_stages(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("a reusable run must not screen or battle")

    monkeypatch.setattr(topn, "screen_candidate", blocked)
    monkeypatch.setattr(topn, "full_result", blocked)
    monkeypatch.setattr(sim_cli, "_pool_context", blocked)


def test_outputs_compact_provenance_and_every_character(characters, tmp_path, capsys, priority):
    out = tmp_path / "reports"
    manifest = run(characters, out)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert all(line.startswith("estimate:") for line in captured.err.splitlines())
    files = report_files(out)
    assert len(manifest["characters"]) == 3
    assert {e["status"] for e in manifest["characters"]} == {"computed", "unavailable"}
    assert "overall.json" in files and "manifest.json" in files
    assert manifest["workers"] == 1 and manifest["niceness"] == 17
    assert priority == [10]
    assert manifest["params"]["rcpm_table"] == "dec-2025"
    assert manifest["runtime_seconds"] >= 0
    assert all(value >= 0 for value in manifest["peak_memory"].values())
    assert manifest["tool_version"] and len(manifest["code_hash"]) == 64
    for source in manifest["sources"]:
        body = read_source(characters, source["url"])
        expected = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert source["sha256"] == expected
        assert source["fetched_at"]
    for entry in manifest["characters"]:
        data = files[entry["file"]]
        assert len(entry["key"]) == 64 and data["key"] == entry["key"]
        assert entry["rank"] and entry["runtime_seconds"] >= 0
        assert data["character"]["name"] == entry["name"]
        for field in ("unresolved", "unavailable"):
            assert all(row["character"] == entry["name"] for row in data[field])
        assert all(source["fetched_at"] for source in data["sources"])
        assert data["validation_label"] == data["validation"]["label"]
        assert data["estimate_label"] == "estimate (every number)"
        for rows in data["character"]["finalists"].values():
            assert all(row["calc_rows"] for row in rows)
    overall = files["overall.json"]
    assert overall["coverage"] == overall["all"]["coverage"]
    assert overall["coverage"]["total"] == 3
    assert overall["coverage"]["characters_with_result"] == 2
    for path in out.rglob("*.json"):
        raw = path.read_text()
        assert "\n" not in raw
        assert raw == json.dumps(json.loads(raw), separators=(",", ":"))


def test_reuse_skips_all_stages_and_preserves_reports(characters, tmp_path, monkeypatch):
    out = tmp_path / "reports"
    first = run(characters, out)
    before = {p: (out / p).read_bytes() for p in report_files(out) if p != "manifest.json"}
    assert_no_stages(monkeypatch)
    second = run(characters, out, "--workers", "2")
    assert {e["status"] for e in second["characters"]} == {"reused", "unavailable"}
    assert second["overall"]["status"] == "reused"
    assert [e["key"] for e in first["characters"]] == [e["key"] for e in second["characters"]]
    assert all((out / p).read_bytes() == body for p, body in before.items())


def test_default_battle_date_and_source_in_reports(cache, tmp_path, monkeypatch):
    class RunDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 15)

    monkeypatch.setattr(topn_cli, "date", RunDate)
    out = tmp_path / "reports"
    options = argv(cache, out)
    index = options.index("--battle-date")
    del options[index : index + 2]
    assert cli.main(options) == 0
    for data in report_files(out).values():
        assert data["battle_date"] == data["params"]["battle_date"] == "2026-11-15"
        assert data["battle_date_source"] == "default: run date"
        if "character" in data:
            rows = data["character"]["finalists"]["40"]
            assert rows
            for row in rows:
                assert row["battle_date"] == "2026-11-15"
                assert row["screen"]["stats_grade"] == "parity-only"
                assert all(
                    slot["battle_date"] == "2026-11-15" for slot in row["screen"]["slot_aggregates"]
                )
    before = {p: (out / p).read_bytes() for p in report_files(out) if p != "manifest.json"}
    assert_no_stages(monkeypatch)
    manifest = run(cache, out, "--battle-date", "2026-11-15")
    assert manifest["battle_date_source"] == "explicit"
    assert manifest["overall"]["status"] == "reused"
    assert all((out / p).read_bytes() == body for p, body in before.items())


@pytest.mark.parametrize(
    "stamp,reusable",
    [("2026-11-15", True), ("2026-09-29", False), ("2025-12-11", False)],
)
def test_reuse_date_depends_on_era_and_extrapolation(cache, tmp_path, monkeypatch, stamp, reusable):
    out = tmp_path / "reports"
    first = run(cache, out)
    if reusable:
        assert_no_stages(monkeypatch)
    second = run(cache, out, "--battle-date", stamp)
    assert second["battle_date"] == stamp
    assert second["battle_date_source"] == "explicit"
    for before, after in zip(first["characters"], second["characters"], strict=True):
        assert (before["key"] == after["key"]) is reusable
        assert after["status"] == ("reused" if reusable else "computed")
    assert (first["overall"]["key"] == second["overall"]["key"]) is reusable
    assert second["overall"]["status"] == ("reused" if reusable else "computed")


def test_changed_source_body_recomputes(cache, tmp_path, monkeypatch):
    out = tmp_path / "reports"
    first = run(cache, out)
    body = read_source(cache, PVPOKE_GM_URL)
    body["harmless_note"] = "source hash changed"
    write_source(cache, PVPOKE_GM_URL, body)
    calls = []
    original = topn.rank_character

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(topn, "rank_character", counted)
    second = run(cache, out)
    assert calls == [1]
    assert second["characters"][0]["status"] == second["overall"]["status"] == "computed"
    assert first["characters"][0]["key"] != second["characters"][0]["key"]
    assert first["overall"]["key"] != second["overall"]["key"]


def test_force_recomputes(cache, tmp_path, monkeypatch):
    out = tmp_path / "reports"
    first = run(cache, out)
    calls = []
    original = topn.rank_character

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(topn, "rank_character", counted)
    second = run(cache, out, "--force")
    assert calls == [1]
    assert second["characters"][0]["status"] == second["overall"]["status"] == "computed"
    assert first["overall"]["key"] == second["overall"]["key"]


def test_character_restricts_and_skips_overall(characters, tmp_path):
    out = tmp_path / "reports"
    manifest = run(characters, out, "--character", "Cliff")
    assert len(manifest["characters"]) == 1
    assert "Cliff" in manifest["characters"][0]["name"]
    assert not (out / "overall.json").exists()
    assert manifest["overall"] == {"key": None, "file": None, "status": "unavailable"}


@pytest.mark.parametrize("start_method", ["fork", "spawn"])
def test_parallel_equals_serial_including_overall_completion(
    characters,
    tmp_path,
    monkeypatch,
    start_method,
):
    if start_method not in multiprocessing.get_all_start_methods():
        pytest.skip(f"{start_method} unavailable")
    monkeypatch.setattr(topn, "screen_candidate", _favor_by_rank)
    mapped = []

    class RecordingPool:
        def __enter__(self):
            self.pool = multiprocessing.get_context(start_method).Pool(
                2,
                initializer=sim_cli._ignore_interrupt,
            )
            return self

        def __exit__(self, *args):
            return self.pool.__exit__(*args)

        def imap(self, function, items, *, chunksize):
            mapped.append((function.func, len(items)))
            return self.pool.imap(function, items, chunksize=chunksize)

    class RecordingContext:
        def Pool(self, workers, *, initializer):
            assert workers == 2
            assert initializer is sim_cli._ignore_interrupt
            return RecordingPool()

    monkeypatch.setattr(sim_cli, "_pool_context", RecordingContext)

    def no_nested_trials(*args, **kwargs):
        pytest.fail("precompute must never use timed trials or nested pools")

    monkeypatch.setattr(sim_cli, "_timed_trials", no_nested_trials)
    serial, parallel = tmp_path / "serial", tmp_path / "parallel"
    run(characters, serial)
    run(characters, parallel, "--workers", "2")
    first, second = report_files(serial), report_files(parallel)
    for files in (first, second):
        manifest = files.pop("manifest.json")
        for field in ("workers", "runtime_seconds", "peak_memory"):
            manifest.pop(field)
        for entry in manifest["characters"]:
            entry.pop("runtime_seconds")
        files["manifest.json"] = manifest
    assert first == second
    assert len(first["overall.json"]["all"]["results"]["40"]) == 2
    assert sum(size for function, size in mapped if function is _favor_by_rank) == 10
    # Two local finalists and the two missing overall-union battles all use the pool.
    assert sum(size for function, size in mapped if function is topn.full_result) == 4


@pytest.mark.parametrize("existing", [False, True])
def test_failed_atomic_write_preserves_target_and_cleans_temp(tmp_path, monkeypatch, existing):
    target = tmp_path / "characters" / "test.json"
    if existing:
        precompute.atomic_json(target, {"old": "complete"})

    def fail_replace(*args):
        raise OSError("injected before replace")

    monkeypatch.setattr(precompute.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        precompute.atomic_json(target, {"new": "complete"})
    assert target.exists() == existing
    if existing:
        assert json.loads(target.read_text()) == {"old": "complete"}
    assert list(target.parent.iterdir()) == ([target] if existing else [])


def test_failed_job_write_does_not_publish_manifest(cache, tmp_path, monkeypatch, capsys):
    out = tmp_path / "reports"

    def fail_replace(*args):
        raise OSError("injected write failure")

    monkeypatch.setattr(precompute.os, "replace", fail_replace)
    with pytest.raises(SystemExit) as exc:
        cli.main(argv(cache, out))
    assert exc.value.code == 2
    assert "injected write failure" in capsys.readouterr().err
    assert not list(out.rglob("*.json"))


def test_output_lock_rejects_second_run(cache, tmp_path, capsys, monkeypatch):
    out = tmp_path / "reports"
    out.mkdir()
    monkeypatch.setattr(calc_cli, "load_sources", lambda *a: pytest.fail("must lock first"))
    with (out / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit) as exc:
            cli.main(argv(cache, out))
    assert exc.value.code == 2
    assert "precompute already running" in capsys.readouterr().err
    assert not (out / "manifest.json").exists()


@pytest.mark.parametrize("nice,calls,result", [(4, [4], 17), (0, [], 7)])
def test_priority(cache, tmp_path, priority, nice, calls, result):
    manifest = run(cache, tmp_path / "reports", "--nice", str(nice))
    assert priority == calls
    assert manifest["niceness"] == result


@pytest.mark.parametrize("workers", [0, -1, 3])
def test_workers_rejected_before_sources(cache, tmp_path, monkeypatch, capsys, workers):
    monkeypatch.setattr(precompute.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(calc_cli, "load_sources", lambda *a: pytest.fail("must validate first"))
    with pytest.raises(SystemExit) as exc:
        cli.main(argv(cache, tmp_path / "reports", "--workers", str(workers)))
    assert exc.value.code == 2
    assert "--workers must be between 1 and 2" in capsys.readouterr().err


def test_defaults_shared_with_topn(cache, tmp_path):
    parsed = cli.parser().parse_args(
        [
            "precompute",
            "--out",
            str(tmp_path / "reports"),
            "--battle-date",
            "2026-11-14",
            "--cache-dir",
            str(cache),
        ]
    )
    assert parsed.workers == 3 and parsed.nice == 10
    parsed.all = True
    data, _, _ = topn_cli.prepare_output(parsed)
    assert data["params"]["levels"] == [40, 50]
    assert data["params"]["trainer_level"] == 50
    assert data["params"]["k"] == 30


@pytest.mark.parametrize(
    "extra,message",
    [
        (["--k", "0"], "--k must be positive"),
        (["--level", "40.1"], "level"),
        (["--level", "nan"], "level"),
        (["--trainer-level", "0"], "trainer level"),
        (["--battle-date", "20261114"], "ISO date"),
        (["--battle-date", "2019-07-21"], "before Team GO Rocket"),
        (["--candidates", ""], "nonempty"),
    ],
)
def test_shared_validation_before_sources(cache, tmp_path, monkeypatch, capsys, extra, message):
    monkeypatch.setattr(calc_cli, "load_sources", lambda *a: pytest.fail("must validate first"))
    with pytest.raises(SystemExit) as exc:
        cli.main(argv(cache, tmp_path / "reports", *extra))
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_missing_character_file_recomputes_overall(cache, tmp_path):
    out = tmp_path / "reports"
    first = run(cache, out)
    (out / first["characters"][0]["file"]).unlink()
    second = run(cache, out)
    assert second["overall"]["status"] == "computed"
    assert first["overall"]["key"] == second["overall"]["key"]


def test_changed_overall_key_recomputes_without_screening(cache, tmp_path, monkeypatch):
    out = tmp_path / "reports"
    run(cache, out)
    data = json.loads((out / "overall.json").read_text())
    data["key"] = "obsolete"
    precompute.atomic_json(out / "overall.json", data)
    monkeypatch.setattr(
        topn, "screen_candidates", lambda *a, **k: pytest.fail("must reuse finalists")
    )
    assert run(cache, out)["overall"]["status"] == "computed"


def test_same_count_different_candidates_and_rcpm_invalidate(cache, tmp_path):
    out = tmp_path / "reports"
    first = run(cache, out, "--candidates", "metagross")
    second = run(cache, out, "--candidates", "kirlia")
    assert first["characters"][0]["key"] != second["characters"][0]["key"]
    assert second["characters"][0]["status"] == "computed"
    third = run(cache, out, "--candidates", "kirlia", "--rcpm-table", "venonic-2023")
    assert second["characters"][0]["key"] != third["characters"][0]["key"]


def test_fetch_time_alone_does_not_invalidate(cache, tmp_path, monkeypatch):
    out = tmp_path / "reports"
    first = run(cache, out)
    write_source(cache, PVPOKE_GM_URL, read_source(cache, PVPOKE_GM_URL))
    assert_no_stages(monkeypatch)
    second = run(cache, out)
    assert second["characters"][0]["status"] == second["overall"]["status"] == "reused"
    assert first["sources"][0]["sha256"] == second["sources"][0]["sha256"]


def test_candidate_filter_including_skipped_entries_invalidates(cache, tmp_path):
    gm = read_source(cache, PVPOKE_GM_URL)
    mega = copy.deepcopy(next(s for s in gm["pokemon"] if s["speciesId"] == "metagross"))
    mega.update(speciesId="metagross_mega", speciesName="Metagross Mega")
    gm["pokemon"].append(mega)
    write_source(cache, PVPOKE_GM_URL, gm)
    out = tmp_path / "reports"
    first = run(cache, out, "--candidates", "metagross")
    second = run(cache, out, "--candidates", "metagross,metagross_mega")
    assert first["params"]["candidate_count"] == second["params"]["candidate_count"]
    assert first["characters"][0]["key"] != second["characters"][0]["key"]
    data = json.loads((out / second["characters"][0]["file"]).read_text())
    assert data["skipped"][0]["speciesId"] == "metagross_mega"


def test_code_hash_uses_installed_package_code_and_json(tmp_path, monkeypatch):
    package = tmp_path / "package"
    (package / "data").mkdir(parents=True)
    (package / "precompute.py").write_bytes(b"code")
    (package / "data" / "rules.json").write_bytes(b'{"rules":true}')
    (package / "ignored.txt").write_bytes(b"not part of the hash")
    monkeypatch.setattr(precompute, "__file__", str(package / "precompute.py"))
    monkeypatch.chdir(tmp_path)
    expected = hashlib.sha256(b'{"rules":true}code').hexdigest()
    assert precompute.code_hash() == expected
    (package / "data" / "rules.json").write_bytes(b'{"rules":false}')
    assert precompute.code_hash() != expected


def test_changed_code_hash_invalidates(cache, tmp_path, monkeypatch):
    out = tmp_path / "reports"
    first = run(cache, out)
    monkeypatch.setattr(precompute, "code_hash", lambda: "changed-package")
    second = run(cache, out)
    assert second["characters"][0]["status"] == "computed"
    assert first["characters"][0]["key"] != second["characters"][0]["key"]
