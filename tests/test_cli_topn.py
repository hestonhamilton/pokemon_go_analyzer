"""Small cached source extracts and injected outcomes; no transport or large runs."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from pogo_analyzer import calc_cli, cli, sim_cli, topn, topn_cli
from pogo_analyzer.lineups import EVENT_INFO_URL, PVPOKE_GM_URL
from pogo_analyzer.pokebattler import PoliteClient
from pogo_analyzer.sim import winrate

FIXTURES = Path(__file__).parent / "fixtures" / "calc"


def write_source(root, url, body):
    client = PoliteClient(root / "sources")
    client._write_cache(
        client.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json"), url, 200, body
    )


def read_source(root, url):
    path = root / "sources" / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    return json.loads(path.read_text())["body"]


@pytest.fixture
def cache(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    event = json.loads((FIXTURES / "event-info.json").read_text())
    event["14"]["encounters"].update(second=[{"id": 281}], third=[{"id": 209}])
    gm = json.loads((FIXTURES / "gamemaster.json").read_text())
    for item in gm["pokemon"]:
        if item["speciesId"] == "metagross":
            item["fastMoves"] = ["ZEN_HEADBUTT", "BULLET_PUNCH"]
            item["chargedMoves"] = ["METEOR_MASH", "EARTHQUAKE"]
            item["legacyMoves"] = ["ZEN_HEADBUTT"]
        else:
            item["fastMoves"] = item["fastMoves"][:1]
            item["chargedMoves"] = item["chargedMoves"][:1]
    write_source(root, EVENT_INFO_URL, event)
    write_source(root, PVPOKE_GM_URL, gm)

    def blocked(*args, **kwargs):
        raise AssertionError("cached topn must not attempt a request")

    monkeypatch.setattr(PoliteClient, "_request", blocked)
    return root


def args(cache, *, all_characters=False):
    return [
        "topn",
        *(["--all"] if all_characters else ["--character", "fai gru"]),
        "--battle-date",
        "2026-11-14",
        "--cache-dir",
        str(cache),
    ]


def output(cache, capsys, extra=(), *, all_characters=False):
    assert cli.main(args(cache, all_characters=all_characters) + list(extra)) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    if not data["unavailable"]:
        assert "estimate:" in captured.err
    return data


def candidates(cache, levels=(40,)):
    _, species, moves, _ = calc_cli.load_sources(cache)
    return topn.build_candidates(species, moves, levels)[0]


def finalists(data):
    return [row for c in data["characters"] for rows in c["finalists"].values() for row in rows]


@pytest.mark.parametrize("k", [1, 2])
def test_cli_k_limits_stage_two(cache, capsys, monkeypatch, k):
    calls = []
    original = sim_cli._timed_trials

    def counted(team, pools, **kwargs):
        calls.append(team)
        return original(team, pools, **kwargs)

    monkeypatch.setattr(sim_cli, "_timed_trials", counted)
    data = output(cache, capsys, ["--k", str(k)])
    assert len(calls) == len(finalists(data)) == 2 * k
    assert data["params"]["k"] == k
    assert data["params"]["levels"] == [40, 50]
    assert data["params"]["trainer_level"] == 50
    assert all(r["battles"] == 1 for r in finalists(data))


def test_screen_top_k_and_moves_ties_are_deterministic(cache):
    builds = candidates(cache, (40, 50))
    calls = []
    scores = {"metagross": 0.9, "kirlia": 0.5, "snubbull": 0.5}

    def identify(team):
        return next(c for c in builds if c.team == team)

    def grid(team, pools, **kwargs):
        rate = scores[identify(team).species_id]
        # Unequal slot weights: the engine must average slot rates, not battles.
        return [], [
            {"slot": 1, "win_rate": rate, "battles": 99},
            {"slot": 2, "win_rate": rate, "battles": 1},
            {"slot": 3, "win_rate": 0, "battles": 1},
        ]

    def trial_runner(team, pools, **kwargs):
        candidate = identify(team)
        calls.append(candidate.key)
        kwargs.pop("execution")
        return winrate.trials(team, pools, **kwargs)

    parsed = cli.parser().parse_args(args(cache))
    chars, species, moves, _ = calc_cli.load_sources(cache)
    pools, _, _ = sim_cli._pools(chars[0], species, moves, parsed)
    ranked = topn.rank_character(
        list(reversed(builds)),
        pools,
        k=2,
        rank="grunt",
        battle_date=parsed.battle_date,
        grid=grid,
        trial_runner=trial_runner,
    )
    assert len(calls) == 4
    assert {key[0] for key in calls} == {"metagross", "kirlia"}
    assert all(key[2:] == ("BULLET_PUNCH", "EARTHQUAKE") for key in calls if key[0] == "metagross")
    assert set(ranked) == {40, 50}
    for rows in ranked.values():
        for row in rows:
            expected = 2 * scores[row["speciesId"]] / 3
            assert row["screen"]["score"] == pytest.approx(expected)
            assert row["screen"]["grid_limitation"] == winrate.GRID_NOTE


def test_full_sort_uses_win_rate_hp_then_turns(cache):
    # Distinct synthetic source identities keep all four builds through screening.
    builds = [
        topn.Candidate(f"s{i}", c.attacker, c.move_flags)
        for i, c in enumerate(candidates(cache)[:4])
    ]
    metrics = [(0, 0.9, 1), (1, 0.1, 20), (1, 0.8, 40), (1, 0.8, 10)]
    pools = [[winrate.Option("target", builds[0].team[0])]] * 3

    def trial_runner(team, pools, *, execution, **kwargs):
        i = next(i for i, c in enumerate(builds) if c.team == team)
        win, hp, turns = metrics[i]
        execution.update(mode="injected", workers=1)
        for lineup, summary in winrate.trials(team, pools, **kwargs):
            yield (
                lineup,
                dict(summary, winner="player" if win else "rocket", hp_fraction=hp, turns=turns),
            )

    ranked = topn.rank_character(
        builds, pools, k=4, rank="grunt", battle_date="2026-11-14", trial_runner=trial_runner
    )
    assert [r["speciesId"] for r in ranked[40]] == ["s3", "s2", "s1", "s0"]


def test_json_provenance_grades_and_calc_cells_match_sim(cache, capsys):
    data = output(cache, capsys, ["--candidates", "metagross", "--k", "1", "--level", "40"])
    assert data["validation_label"] == data["validation"]["label"]
    assert data["battle_date"] == "2026-11-14" and data["era"] == "mar-2026"
    assert data["rcpm_note"] == calc_cli.CP_ONLY
    assert all(s["fetched_at"] and s["license"] == "MIT" for s in data["sources"])
    assert {s["url"] for s in data["sources"]} == {EVENT_INFO_URL, PVPOKE_GM_URL}
    assert "not lineup win rates" in data["screen_note"]
    assert "no encounter-rate source" in data["weighting_note"]
    (row,) = finalists(data)
    assert row["grade"] == "estimate; unverified (l); extrapolated forward; stats parity-only"
    assert row["move_flags"][row["fast_move"]]["elite"] is False
    assert len(row["calc_rows"]) == 3
    assert all(
        "grade" in cell and "value" in cell
        for matchup in row["calc_rows"]
        for cell in matchup.values()
    )
    assert all(
        m["damage"]["grade"] == "parity-only"
        for matchup in row["calc_rows"]
        for m in matchup["charged"]["value"]
    )
    argv = [
        "sim",
        "--character",
        "Fairy grunt",
        "--battle-date",
        data["battle_date"],
        "--trainer-level",
        "50",
        "--attacker",
        "metagross",
        "--level",
        "40",
        "--ivs",
        "15/15/15",
        "--fast",
        row["fast_move"],
        "--charged",
        row["charged_move"],
        "--cache-dir",
        str(cache),
    ]
    direct = sim_cli.build_output(cli.parser().parse_args(argv))["results"][0]
    for key in direct:
        if key not in ("execution", "team"):
            assert row[key] == direct[key]
    calc_args = cli.parser().parse_args([*argv, "--format", "json"])
    calc_args.defender = None
    calc_args.slot = calc_args.rank = None
    calc_args.sort = "fast_turns_to_ko"
    assert (
        sorted(row["calc_rows"], key=lambda r: r["fast_turns_to_ko"]["value"])
        == (calc_cli.build_output(calc_args)["results"])
    )


def test_overall_union_coverage_and_incomplete_grades(cache, capsys, monkeypatch):
    event = read_source(cache, EVENT_INFO_URL)
    event["14"]["encounters"]["second"].append({"id": 9999})
    event["15"] = copy.deepcopy(event["14"])
    event["15"].update(type="Cliff", grunt="Executive")
    event["15"]["encounters"]["second"] = [{"id": 281}]
    event["16"] = copy.deepcopy(event["14"])
    event["16"].update(grunt="Giovanni")
    event["16"]["encounters"]["second"] = [{"id": 281}]
    event["17"] = copy.deepcopy(event["14"])
    event["17"]["type"] = "Empty"
    event["17"]["encounters"]["third"] = []
    write_source(cache, EVENT_INFO_URL, event)
    original = topn.screen_candidate

    def different_favorites(candidate, pools, *, rank, **kwargs):
        row = original(candidate, pools, rank=rank, **kwargs)
        favorite = "metagross" if rank == "grunt" else "kirlia"
        row["score"] = int(candidate.species_id == favorite)
        return row

    monkeypatch.setattr(topn, "screen_candidate", different_favorites)
    calls = []
    original_trials = sim_cli._timed_trials

    def counted(team, pools, **kwargs):
        calls.append(kwargs["rank"])
        return original_trials(team, pools, **kwargs)

    monkeypatch.setattr(sim_cli, "_timed_trials", counted)
    data = output(cache, capsys, ["--k", "1", "--level", "40"], all_characters=True)
    assert len(calls) == 6  # 3 local finalists + 3 missing union results, no unavailable battles.
    coverage = data["overall"]["coverage"]
    assert coverage["characters_with_result"] == 3 and coverage["total"] == 4
    assert coverage["missing"] == [
        {
            "character": "Empty grunt (female)",
            "reason": topn.UNAVAILABLE,
        }
    ]
    assert data["overall"]["grunts"]["coverage"]["characters_with_result"] == 1
    assert data["overall"]["leaders"]["coverage"] == {
        "characters_with_result": 2,
        "total": 2,
        "missing": [],
    }
    assert all(r["grade"].startswith("estimate") for r in finalists(data))
    assert all(
        ("pool incomplete" in r["grade"]) == (not r["pool_complete"]) for r in finalists(data)
    )
    for view in ("all", "grunts", "leaders"):
        rows = data["overall"][view]["results"]["40"]
        assert {r["speciesId"] for r in rows} == {"kirlia", "metagross"}
        for row in rows:
            assert row["grade"].startswith("estimate")
            assert ("pool incomplete" in row["grade"]) == (view != "leaders")
            per = row["per_character"]
            assert all(r["character"] != "Empty grunt (female)" for r in per)
            assert row["win_rate"] == pytest.approx(sum(r["win_rate"] for r in per) / len(per))
            # Overall entries are compact; calc cells stay on per-character finalists only.
            assert all("calc_rows" not in r and r["grade"].startswith("estimate") for r in per)
    assert all(r["calc_rows"] for r in finalists(data))


def test_candidates_shadow_mega_unreleased_and_rejections(cache, capsys):
    gm = read_source(cache, PVPOKE_GM_URL)
    base = next(s for s in gm["pokemon"] if s["speciesId"] == "metagross")
    for name in ("metagross_shadow", "metagross_mega", "unreleased", "rejected"):
        item = copy.deepcopy(base)
        item.update(speciesId=name, speciesName=name)
        if name == "unreleased":
            item["tags"] = ["unreleased"]
        if name == "rejected":
            item["fastMoves"] = ["EARTHQUAKE"]
        gm["pokemon"].append(item)
    write_source(cache, PVPOKE_GM_URL, gm)
    data = output(cache, capsys)
    skipped = {r["speciesId"]: r["reason"] for r in data["skipped"]}
    assert "Mega" in skipped["metagross_mega"]
    assert "unreleased" in skipped["unreleased"]
    assert "invalid fast move" in skipped["rejected"]
    assert data["params"]["candidate_count"] == 4
    shadow = [r for r in finalists(data) if r["speciesId"] == "metagross_shadow"]
    assert len(shadow) == 2
    assert all(r["species"] == "metagross" and r["form"] == "shadow" for r in shadow)
    assert all(r["team"][0]["shadow"] for r in shadow)
    assert all(m["form"]["value"] == "shadow" for r in shadow for m in r["calc_rows"])
    restricted = output(cache, capsys, ["--candidates", "metagross_shadow", "--level", "40"])
    assert {r["speciesId"] for r in finalists(restricted)} == {"metagross_shadow"}
    assert restricted["params"]["candidate_count"] == 1


def test_special_move_rejection_keeps_valid_movesets(cache, capsys):
    gm = read_source(cache, PVPOKE_GM_URL)
    next(m for m in gm["moves"] if m["moveId"] == "METEOR_MASH")["isMegaMove"] = True
    write_source(cache, PVPOKE_GM_URL, gm)
    data = output(cache, capsys, ["--candidates", "metagross", "--level", "40"])
    assert all("unsupported special move: METEOR_MASH" in r["reason"] for r in data["skipped"])
    assert len(data["skipped"]) == 2
    assert all(r["charged_move"] == "EARTHQUAKE" for r in finalists(data))


def test_overall_equal_character_weight_sort_and_weakest_grade(cache):
    characters = [
        {"name": "a", "rank": "grunt"},
        {"name": "b", "rank": "leader"},
        {"name": "missing", "rank": "grunt", "reason": topn.UNAVAILABLE},
    ]
    builds = [
        topn.Candidate(f"s{i}", c.attacker, c.move_flags)
        for i, c in enumerate(candidates(cache)[:4])
    ]
    results = {c["name"]: {} for c in characters}
    metrics = [(0, 0, 1, 1), (0, 1, 0.1, 20), (1, 0, 0.8, 40), (1, 0, 0.8, 10)]
    for candidate, (first_win, second_win, hp, turns) in zip(builds, metrics, strict=True):
        for name, win, battles in (("a", first_win, 1), ("b", second_win, 1000)):
            row = {
                **candidate.output(),
                "character": name,
                "battles": battles,
                "win_rate": win,
                "mean_player_hp_fraction_left": hp,
                "mean_turns": turns,
                "rules_grade": "unverified" if name == "b" else "estimate",
                "flags": ["unverified", "extrapolated"] if name == "b" else [],
                "pool_complete": name != "b",
            }
            results[name][candidate.key] = sim_cli._grade(
                row, "model" if name == "b" else "parity-only"
            )
    view = topn.overall_view(characters, results)
    assert view["coverage"] == {
        "characters_with_result": 2,
        "total": 3,
        "missing": [{"character": "missing", "reason": topn.UNAVAILABLE}],
    }
    rows = view["results"]["40"]
    assert [r["speciesId"] for r in rows] == ["s3", "s2", "s1", "s0"]
    assert [r["win_rate"] for r in rows] == [0.5, 0.5, 0.5, 0]
    for row in rows:
        assert sim_cli._grade(row, row["stats_grade"])["grade"] == (
            "estimate; unverified (l); extrapolated forward; stats model; pool incomplete"
        )


def test_exclude_elite_and_legacy_on_both_sides(cache, capsys):
    builds = candidates(cache)
    meta = [c for c in builds if c.species_id == "metagross"]
    assert len(meta) == 4
    assert any(c.move_flags["METEOR_MASH"]["elite"] for c in meta if "METEOR_MASH" in c.move_flags)
    assert any(
        c.move_flags["ZEN_HEADBUTT"]["legacy"] for c in meta if "ZEN_HEADBUTT" in c.move_flags
    )
    gm = read_source(cache, PVPOKE_GM_URL)
    snubbull = next(s for s in gm["pokemon"] if s["speciesId"] == "snubbull")
    snubbull["eliteMoves"] = snubbull["fastMoves"]
    write_source(cache, PVPOKE_GM_URL, gm)
    data = output(cache, capsys, ["--candidates", "metagross,snubbull", "--exclude-elite-legacy"])
    assert data["params"]["exclude_elite_legacy"]
    assert data["params"]["candidate_count"] == 1
    assert "excluded from candidate and Rocket pools" in data["filter_note"]
    assert data["unavailable"] and data["unresolved"]
    assert any("empty fast or charged" in r["reason"] for r in data["skipped"])
    _, species, moves, _ = calc_cli.load_sources(cache)
    filtered, _ = topn.build_candidates(
        species, moves, [40], selectors=["metagross"], exclude_elite_legacy=True
    )
    assert [c.key[2:] for c in filtered] == [("BULLET_PUNCH", "EARTHQUAKE")]


@pytest.mark.parametrize(
    "extra,message",
    [
        (["--k", "0"], "--k must be positive"),
        (["--level", "40.1"], "level"),
        (["--level", "nan"], "level"),
        (["--battle-date", "20261114"], "ISO date"),
        (["--battle-date", "2026-02-30"], "invalid --battle-date"),
        (["--battle-date", "2019-07-21"], "before Team GO Rocket battles"),
        (["--candidates", ""], "nonempty"),
    ],
)
def test_invalid_parameters_before_sources(cache, capsys, monkeypatch, extra, message):
    monkeypatch.setattr(calc_cli, "load_sources", lambda *a: pytest.fail("must validate first"))
    with pytest.raises(SystemExit) as exc:
        cli.main(args(cache) + extra)
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_required_date_and_json_only(cache, capsys):
    argv = args(cache)
    i = argv.index("--battle-date")
    del argv[i : i + 2]
    with pytest.raises(SystemExit):
        cli.main(argv)
    assert "--battle-date" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(args(cache) + ["--format", "table"])
    assert "invalid choice" in capsys.readouterr().err


def test_unvalidated_still_estimate_and_empty_overall(cache, capsys, tmp_path):
    data = output(cache, capsys, ["--fixtures-dir", str(tmp_path / "missing"), "--k", "1"])
    assert "UNVALIDATED" in data["validation_label"]
    assert all(r["grade"].startswith("estimate") for r in finalists(data))
    event = read_source(cache, EVENT_INFO_URL)
    event["14"]["encounters"]["third"] = []
    write_source(cache, EVENT_INFO_URL, event)
    parsed = cli.parser().parse_args(args(cache, all_characters=True))
    empty = topn_cli.build_output(parsed)
    assert empty["overall"]["coverage"]["characters_with_result"] == 0
    assert empty["overall"]["all"]["results"] == {}
