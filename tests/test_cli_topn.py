"""Small cached source extracts and injected outcomes; no transport or large runs."""

import copy
import hashlib
import json
from datetime import date
from fractions import Fraction
from pathlib import Path

import pytest

from pogo_analyzer import calc_cli, cli, sim_cli, topn, topn_cli
from pogo_analyzer.lineups import EVENT_INFO_URL, PVPOKE_GM_URL
from pogo_analyzer.pokebattler import PoliteClient
from pogo_analyzer.sim import solo, winrate

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
    original = solo.aggregate

    def counted(team, pools, **kwargs):
        calls.append(team)
        return original(team, pools, **kwargs)

    monkeypatch.setattr(solo, "aggregate", counted)
    data = output(cache, capsys, ["--k", str(k)])
    assert len(finalists(data)) == 2 * k
    assert len(calls) == 3 * len(finalists(data))  # Era result plus two sensitivity passes.
    assert data["params"]["k"] == k
    assert data["params"]["levels"] == [40, 50]
    assert all(type(level) is float for level in data["params"]["levels"])
    assert data["params"]["trainer_level"] == 50
    assert all(r["battles"] == 1 for r in finalists(data))
    assert all(
        r["execution"] == {"mode": "exact solo engine", "workers": 1} for r in finalists(data)
    )


def test_default_pause_band_and_none_preserve_ranking_and_fields(cache, capsys):
    extra = ["--k", "2", "--level", "40"]
    data = output(cache, capsys, extra)
    disabled = output(cache, capsys, [*extra, "--pause-band", "none"])
    assert data["params"].pop("pause_band") == [6, 8]
    assert disabled["params"].pop("pause_band") == []
    assert data["params"]["pause_threshold"] == disabled["params"]["pause_threshold"] == 0.15
    for row in finalists(data):
        band = row.pop("pause_band")
        assert set(band) == {
            "turns",
            "win_rate",
            "wins",
            "battles",
            "flags",
            "min",
            "max",
            "sensitive",
            "threshold",
            "threshold_note",
            "note",
        }
        assert band["threshold_note"] == "model choice"
        assert band["turns"] == [6, 7, 8]
        assert set(band["win_rate"]) == {"6", "7", "8"}
        assert band["win_rate"]["7"] == row["win_rate"]
        assert band["min"] == min(band["win_rate"].values())
        assert band["max"] == max(band["win_rate"].values())
        rates = [Fraction(band["wins"][t], band["battles"][t]) for t in band["wins"]]
        assert band["sensitive"] == (max(rates) - min(rates) > Fraction("0.15"))
        assert band["wins"]["7"] == row["wins"]
        assert band["battles"]["7"] == row["battles"]
        assert band["threshold"] == 0.15
        assert band["note"] == topn.PAUSE_BAND_NOTE
        assert "sensitivity check over assumed pause lengths, not a measured range" in band["note"]
    assert all("pause_band" not in r for r in finalists(disabled))
    assert data == disabled


@pytest.mark.parametrize(
    "wins,battles,sensitive", [(18, 20, False), (900001, 1000000, True), (15, 20, False)]
)
@pytest.mark.parametrize(
    "stamp,era_turns,reuse_era",
    [("2026-11-14", 7, True), ("2025-12-11", 8, False), ("2025-12-09", 5, False)],
)
def test_pause_band_threshold_era_value_and_mapper(
    cache, monkeypatch, wins, battles, sensitive, stamp, era_turns, reuse_era
):
    builds = candidates(cache)[:1]
    pools = [[winrate.Option("target", builds[0].team[0])]] * 3
    calls, mapped = [], []

    def full(candidate, pools, *, rules=None, **kwargs):
        turn = rules.pause_turns_override if rules is not None else None
        calls.append(turn)
        n_wins, n_battles = (wins, battles) if turn == 6 else (15, 20)
        if turn is None and not reuse_era:
            n_wins = 10  # The era's mixed lengths differ from every equal-length run.
        return {
            "win_rate": n_wins / n_battles,
            "wins": n_wins,
            "battles": n_battles,
            "flags": ["era"] if turn is None else [f"override-{turn}", "unverified"],
            "mean_player_hp_fraction_left": 0,
            "mean_turns": 1,
        }

    def mapper(function, items):
        mapped.append(len(items))
        return map(function, items)

    monkeypatch.setattr(topn, "full_result", full)
    ranked = topn.rank_character(
        builds, pools, k=1, rank="grunt", battle_date=stamp, pause_band=(6, 8), mapper=mapper
    )
    (row,) = ranked[40]
    band = row["pause_band"]
    turns = sorted({6, 8, era_turns})
    overrides = [t for t in turns if t != era_turns or not reuse_era]
    assert band["turns"] == turns
    assert band["win_rate"][str(era_turns)] == 0.75
    assert row["win_rate"] == (0.75 if reuse_era else 0.5)
    assert band["wins"]["6"] == wins
    assert band["battles"]["6"] == battles
    assert band["wins"][str(era_turns)] == 15
    assert band["battles"][str(era_turns)] == 20
    assert band["sensitive"] is sensitive
    assert band["flags"] == sorted(
        [*(["era"] if reuse_era else []), *[f"override-{t}" for t in overrides], "unverified"]
    )
    assert calls == [None, *overrides]
    assert mapped == [1] * (1 + len(calls))  # Screen and every full pass use the same mapper.


@pytest.mark.parametrize("value", ["", "0", "21", "6.0", "6,", "none,8", "six"])
def test_invalid_pause_band_rejected_before_sources(cache, monkeypatch, value):
    monkeypatch.setattr(calc_cli, "load_sources", lambda *a: pytest.fail("must validate first"))
    with pytest.raises(SystemExit) as exc:
        cli.main([*args(cache), "--pause-band", value])
    assert exc.value.code == 2


@pytest.mark.parametrize("stamp,turns", [("2026-11-14", "7"), ("2025-12-11", "8")])
def test_era_only_pause_band_rejected_before_sources(cache, capsys, monkeypatch, stamp, turns):
    monkeypatch.setattr(calc_cli, "load_sources", lambda *a: pytest.fail("must validate first"))
    with pytest.raises(SystemExit) as exc:
        cli.main([*args(cache), "--battle-date", stamp, "--pause-band", turns])
    assert exc.value.code == 2
    assert (
        "--pause-band must include a length other than the era's charged length"
        in capsys.readouterr().err
    )


def test_screen_top_k_and_moves_ties_are_deterministic(cache, monkeypatch):
    monkeypatch.setattr(solo, "supports", lambda *a: False)
    builds = candidates(cache, (40, 50))
    calls = []
    scores = {"metagross": 0.9, "kirlia": 0.5, "snubbull": 0.5}

    def identify(team):
        return next(c for c in builds if c.team == team)

    def grid(team, pools, **kwargs):
        rate = scores[identify(team).species_id]
        # Unequal slot weights: the engine must average slot rates, not battles.
        return [], [
            {
                "slot": slot,
                "win_rate": value,
                "battles": battles,
                "rules_grade": "estimate",
                "flags": [],
                "label": "estimate (every number)",
            }
            for slot, value, battles in ((1, rate, 99), (2, rate, 1), (3, 0, 1))
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
    # kirlia and snubbull tie exactly at the K=2 cut, so both are kept (no alphabetical cut).
    assert len(calls) == 6
    assert {key[0] for key in calls} == {"metagross", "kirlia", "snubbull"}
    assert all(key[2:] == ("BULLET_PUNCH", "EARTHQUAKE") for key in calls if key[0] == "metagross")
    assert set(ranked) == {40, 50}
    for rows in ranked.values():
        for row in rows:
            expected = 2 * scores[row["speciesId"]] / 3
            assert row["screen"]["score"] == pytest.approx(expected)
            assert row["screen"]["grid_limitation"] == winrate.GRID_NOTE


def test_full_sort_uses_win_rate_hp_then_turns(cache, monkeypatch):
    monkeypatch.setattr(solo, "supports", lambda *a: False)
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


@pytest.mark.parametrize(
    "unverified,extrapolated,incomplete",
    [(False, False, False), (True, False, False), (False, True, False), (True, True, True)],
)
def test_screen_preserves_slot_grades_and_has_independent_headline(
    cache, unverified, extrapolated, incomplete
):
    candidate = candidates(cache)[0]
    groups = [
        {
            "slot": slot,
            "win_rate": slot / 4,
            "rules_grade": "unverified" if unverified and slot == 2 else "estimate",
            "flags": ["extrapolated"] if extrapolated and slot == 3 else [],
            "label": "estimate (every number)",
        }
        for slot in range(1, 4)
    ]

    def grid(team, pools, **kwargs):
        return [], copy.deepcopy(groups)

    ((build, screen),) = topn.screen_candidates(
        [candidate],
        [],
        rank="grunt",
        battle_date="2026-11-14",
        grid=grid,
        stats_grade=lambda c: "cp-only" if c is candidate else pytest.fail("unexpected build"),
        pool_complete=not incomplete,
    )
    assert build is candidate
    assert screen["slot_aggregates"] == groups
    assert screen["score"] == 0.5
    assert screen["slot_win_rates"] == [0.25, 0.5, 0.75]
    assert screen["rules_grade"] == ("unverified" if unverified else "estimate")
    assert screen["flags"] == (["extrapolated"] if extrapolated else [])
    expected = sim_cli._grade(
        {
            "rules_grade": screen["rules_grade"],
            "flags": screen["flags"],
            "pool_complete": not incomplete,
        },
        "cp-only",
    )
    assert screen["grade"] == expected["grade"]
    assert screen["stats_grade"] == "cp-only"
    assert screen["label"] == "estimate (every number)"


def test_cli_screen_stats_grade_uses_weakest_of_all_options(cache, capsys, monkeypatch):
    event = read_source(cache, EVENT_INFO_URL)
    event["14"]["encounters"]["second"].append({"id": 209})
    write_source(cache, EVENT_INFO_URL, event)
    seen = []

    def stats_grade(attacker, option, defender, args, rank, validation):
        seen.append(option.species)
        # Only the second species carries the weak grade, after the first slot.
        return "model" if option.species == "kirlia" else "fixture-exact"

    monkeypatch.setattr(sim_cli, "_stats_grade", stats_grade)
    data = output(cache, capsys, ["--candidates", "kirlia", "--level", "40"])
    assert seen == ["snubbull", "kirlia", "snubbull", "snubbull"]
    (row,) = finalists(data)
    assert row["screen"]["stats_grade"] == "model"
    assert row["screen"]["grade"].endswith("stats model")
    assert row["stats_grade"] == "parity-only"


def test_json_provenance_grades_and_calc_cells_match_sim(cache, capsys):
    data = output(cache, capsys, ["--candidates", "metagross", "--k", "1", "--level", "40"])
    assert data["validation_label"] == data["validation"]["label"]
    assert data["battle_date"] == "2026-11-14" and data["era"] == "mar-2026"
    assert data["battle_date_source"] == "explicit"
    assert data["rcpm_note"] == calc_cli.CP_ONLY
    assert all(s["fetched_at"] and s["license"] == "MIT" for s in data["sources"])
    assert {s["url"] for s in data["sources"]} == {EVENT_INFO_URL, PVPOKE_GM_URL}
    assert "not lineup win rates" in data["screen_note"]
    assert "no encounter-rate source" in data["weighting_note"]
    (row,) = finalists(data)
    assert row["grade"] == "estimate; unverified (l); extrapolated forward; stats parity-only"
    screen = row["screen"]
    assert screen["grade"] == row["grade"]
    assert screen["stats_grade"] == "parity-only"
    assert len(screen["slot_aggregates"]) == 3
    assert all(
        slot["label"] == "estimate (every number)"
        and slot["rules_grade"] == "unverified"
        and "extrapolated" in slot["flags"]
        for slot in screen["slot_aggregates"]
    )
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
    original_trials = solo.aggregate

    def counted(team, pools, **kwargs):
        calls.append(kwargs["rank"])
        return original_trials(team, pools, **kwargs)

    monkeypatch.setattr(solo, "aggregate", counted)
    data = output(cache, capsys, ["--k", "1", "--level", "40"], all_characters=True)
    assert len(calls) == 12  # 3 finalists x 3 passes + 3 overall-only results with no band.
    coverage = data["overall"]["coverage"]
    assert coverage["characters_with_result"] == 3 and coverage["total"] == 4
    assert coverage["missing"] == [
        {
            "character": "Empty grunt (female)",
            "reason": topn.UNAVAILABLE,
        }
    ]
    assert coverage["text"] == "covers 3 of 4 characters; missing: Empty grunt (female)"
    assert data["overall"]["grunts"]["coverage"]["characters_with_result"] == 1
    assert data["overall"]["grunts"]["coverage"]["text"] == (
        "covers 1 of 2 characters; missing: Empty grunt (female)"
    )
    assert data["overall"]["leaders"]["coverage"] == {
        "characters_with_result": 2,
        "total": 2,
        "missing": [],
        "text": "covers 2 of 2 characters",
    }
    assert all(r["grade"].startswith("estimate") for r in finalists(data))
    assert all(
        ("pool incomplete" in r["grade"]) == (not r["pool_complete"]) for r in finalists(data)
    )
    assert all(
        ("pool incomplete" in r["screen"]["grade"]) == (not r["pool_complete"])
        for r in finalists(data)
    )
    for view in ("all", "grunts", "leaders"):
        rows = data["overall"][view]["results"]["40"]
        assert {r["speciesId"] for r in rows} == {"kirlia", "metagross"}
        for row in rows:
            assert "pause_band" not in row
            assert row["grade"].startswith("estimate")
            assert row["label"] == "estimate (every number)"
            assert row["evidence"] and row["ledger_rows"] and row["interpretations"]
            assert ("pool incomplete" in row["grade"]) == (view != "leaders")
            per = row["per_character"]
            assert all(r["character"] != "Empty grunt (female)" for r in per)
            assert row["win_rate"] == pytest.approx(sum(r["win_rate"] for r in per) / len(per))
            # Overall entries are compact; calc cells stay on per-character finalists only.
            assert all("calc_rows" not in r and r["grade"].startswith("estimate") for r in per)
            assert all("pause_band" not in r for r in per)
    assert all(r["calc_rows"] for r in finalists(data))


def test_candidates_shadow_mega_unreleased_and_rejections(cache, capsys):
    gm = read_source(cache, PVPOKE_GM_URL)
    base = next(s for s in gm["pokemon"] if s["speciesId"] == "metagross")
    for name in (
        "metagross_shadow",
        "metagross_mega",
        "tagged_mega",
        "kyogre_primal",
        "unreleased",
        "not_released",
        "rejected",
    ):
        item = copy.deepcopy(base)
        item.update(speciesId=name, speciesName=name)
        if name == "unreleased":
            item["tags"] = ["unreleased"]
        if name == "not_released":
            item["released"] = False
        if name == "tagged_mega":
            item.update(speciesId="tagged", tags=["mega"])
        if name == "rejected":
            item["fastMoves"] = ["EARTHQUAKE"]
        gm["pokemon"].append(item)
    write_source(cache, PVPOKE_GM_URL, gm)
    data = output(cache, capsys)
    skipped = {r["speciesId"]: r["reason"] for r in data["skipped"]}
    assert "Mega" in skipped["metagross_mega"]
    assert skipped["tagged"] == skipped["kyogre_primal"] == skipped["metagross_mega"]
    assert "unreleased" in skipped["unreleased"]
    assert skipped["not_released"] == skipped["unreleased"]
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


def test_shadow_rejection_names_source(cache, capsys):
    gm = read_source(cache, PVPOKE_GM_URL)
    base = next(s for s in gm["pokemon"] if s["speciesId"] == "metagross")
    shadow = copy.deepcopy(base)
    shadow.update(speciesId="metagross_shadow", speciesName="Metagross (Shadow)")
    shadow["chargedMoves"] = ["DISARMING_VOICE"]
    gm["pokemon"].append(shadow)
    write_source(cache, PVPOKE_GM_URL, gm)
    data = output(cache, capsys, ["--candidates", "metagross_shadow", "--level", "40"])
    assert not finalists(data)
    assert data["skipped"]
    assert all(
        r["reason"] == "metagross_shadow: invalid charged move for metagross"
        for r in data["skipped"]
    )


@pytest.mark.parametrize("all_characters", [False, True])
def test_duplicate_selected_names_fail_before_battles(cache, monkeypatch, all_characters):
    event = read_source(cache, EVENT_INFO_URL)
    event["15"] = copy.deepcopy(event["14"])
    event["16"] = copy.deepcopy(event["14"])
    event["16"]["type"] = "Empty"
    event["17"] = copy.deepcopy(event["16"])
    write_source(cache, EVENT_INFO_URL, event)
    monkeypatch.setattr(topn, "rank_character", lambda *a, **kw: pytest.fail("must reject first"))
    parsed = cli.parser().parse_args(args(cache, all_characters=all_characters))
    with pytest.raises(ValueError) as exc:
        topn_cli.build_output(parsed)
    expected = "duplicate character names: "
    if all_characters:
        expected += "Empty grunt (female), "
    expected += "Fairy grunt (female)"
    assert str(exc.value) == expected


def test_planned_totals_are_printed_before_ranking(cache, capsys, monkeypatch):
    event = read_source(cache, EVENT_INFO_URL)
    event["15"] = copy.deepcopy(event["14"])
    event["15"].update(type="Cliff", grunt="Executive")
    event["14"]["encounters"]["second"].append({"id": 209})
    event["16"] = copy.deepcopy(event["14"])
    event["16"]["type"] = "Empty"
    event["16"]["encounters"]["third"] = []
    write_source(cache, EVENT_INFO_URL, event)
    calls = []

    def ranked(builds, pools, **kwargs):
        if not calls:
            assert capsys.readouterr().err == (
                "estimate: planned stage-1 1v1 battles: 56; "
                "maximum stage-2 lineup battles: 12. --all adds union completion battles.\n"
            )
        calls.append(kwargs["rank"])
        return {}

    monkeypatch.setattr(topn, "rank_character", ranked)
    parsed = cli.parser().parse_args(
        args(cache, all_characters=True) + ["--candidates", "metagross", "--k", "2"]
    )
    topn_cli.build_output(parsed)
    assert calls == ["grunt", "leader"]


def test_identical_runs_produce_identical_json(cache, capsys):
    event = read_source(cache, EVENT_INFO_URL)
    event["15"] = copy.deepcopy(event["14"])
    event["15"].update(type="Cliff", grunt="Executive")
    write_source(cache, EVENT_INFO_URL, event)
    argv = args(cache, all_characters=True) + ["--candidates", "kirlia", "--level", "40"]
    assert cli.main(argv) == 0
    first = capsys.readouterr().out
    assert cli.main(argv) == 0
    second = capsys.readouterr().out
    assert first == second


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
    shared_evidence = {"row": "l", "grade": "unverified", "option": "shared", "source": "fixture"}
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
            if candidate is builds[0]:
                row.update(
                    evidence=[shared_evidence, dict(shared_evidence, option=name)],
                    ledger_rows=["l", name],
                    interpretations=["shared", name],
                )
            results[name][candidate.key] = sim_cli._grade(
                row, "model" if name == "b" else "parity-only"
            )
    view = topn.overall_view(characters, results)
    assert view["coverage"] == {
        "characters_with_result": 2,
        "total": 3,
        "missing": [{"character": "missing", "reason": topn.UNAVAILABLE}],
        "text": "covers 2 of 3 characters; missing: missing",
    }
    rows = view["results"]["40"]
    assert [r["speciesId"] for r in rows] == ["s3", "s2", "s1", "s0"]
    assert [r["win_rate"] for r in rows] == [0.5, 0.5, 0.5, 0]
    for row in rows:
        assert sim_cli._grade(row, row["stats_grade"])["grade"] == (
            "estimate; unverified (l); extrapolated forward; stats model; pool incomplete"
        )
        assert row["label"] == "estimate (every number)"
        if row["speciesId"] == builds[0].species_id:
            assert row["evidence"] == [
                dict(shared_evidence, option="a"),
                dict(shared_evidence, option="b"),
                shared_evidence,
            ]
            assert row["ledger_rows"] == ["a", "b", "l"]
            assert row["interpretations"] == ["a", "b", "shared"]
        else:
            assert row["evidence"] == row["ledger_rows"] == row["interpretations"] == []


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


def test_default_date_and_explicit_override(cache, capsys, monkeypatch):
    class RunDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 15)

    monkeypatch.setattr(topn_cli, "date", RunDate)
    argv = args(cache)
    i = argv.index("--battle-date")
    del argv[i : i + 2]
    assert cli.main(argv + ["--candidates", "kirlia", "--level", "40"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["battle_date"] == "2026-11-15"
    assert data["battle_date_source"] == "default: run date"
    assert all(
        r["battle_date"] == "2026-11-15"
        and all(slot["battle_date"] == "2026-11-15" for slot in r["screen"]["slot_aggregates"])
        for r in finalists(data)
    )
    explicit = output(cache, capsys, ["--candidates", "kirlia", "--level", "40"])
    assert explicit["battle_date"] == "2026-11-14"
    assert explicit["battle_date_source"] == "explicit"


def test_json_only(cache, capsys):
    with pytest.raises(SystemExit):
        cli.main(args(cache) + ["--format", "table"])
    assert "invalid choice" in capsys.readouterr().err


@pytest.mark.parametrize("error", [KeyError("bug"), TypeError("bug")])
def test_programming_errors_are_not_usage_errors(cache, monkeypatch, error):
    def broken(args):
        raise error

    monkeypatch.setattr(topn_cli, "build_output", broken)
    with pytest.raises(type(error), match="bug"):
        cli.main(args(cache))


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


def test_pause_threshold_parameter_sets_sensitive_flag(cache, monkeypatch):
    builds = candidates(cache)[:1]
    pools = [[winrate.Option("target", builds[0].team[0])]] * 3

    def full(candidate, pools, *, rules=None, **kwargs):
        turn = rules.pause_turns_override if rules is not None else None
        rate = 0.1 if turn == 6 else 0
        return {
            "win_rate": rate,
            "wins": 1 if turn == 6 else 0,
            "battles": 10,
            "flags": [],
            "mean_player_hp_fraction_left": 0,
            "mean_turns": 1,
        }

    monkeypatch.setattr(topn, "full_result", full)
    for threshold, sensitive in ((0.15, False), (0.05, True)):
        ranked = topn.rank_character(
            builds,
            pools,
            k=1,
            rank="grunt",
            battle_date="2026-11-14",
            pause_band=(6, 8),
            pause_threshold=threshold,
        )
        band = ranked[40][0]["pause_band"]
        assert band["threshold"] == threshold
        assert band["sensitive"] is sensitive


@pytest.mark.parametrize("value", ["0", "1", "-0.1", "x"])
def test_invalid_pause_threshold_rejected_before_sources(cache, monkeypatch, value):
    monkeypatch.setattr(calc_cli, "load_sources", lambda *a: pytest.fail("must validate first"))
    with pytest.raises(SystemExit) as exc:
        cli.main([*args(cache), "--pause-threshold", value])
    assert exc.value.code == 2


def margin_grid(margins):
    """Every slot at a 1.0 win rate; margins maps species id to (hp left, turns)."""

    def grid(team, pools, **kwargs):
        species = next(c for c in grid.builds if c.team == team).species_id
        hp, turns = margins[species]
        return [], [
            {
                "slot": slot,
                "win_rate": 1.0,
                "mean_player_hp_fraction_left": hp,
                "mean_turns": turns,
                "rules_grade": "estimate",
                "flags": [],
                "label": "estimate (every number)",
            }
            for slot in range(1, 4)
        ]

    return grid


def test_screen_breaks_saturated_ties_by_hp_left_then_turns(cache):
    builds = [
        topn.Candidate(name, c.attacker, c.move_flags)
        for name, c in zip(("aa", "bb", "cc", "dd"), candidates(cache)[:4], strict=True)
    ]
    grid = margin_grid({"aa": (0.2, 10), "bb": (0.9, 30), "cc": (0.9, 12), "dd": (0.5, 5)})
    grid.builds = builds
    screened = topn.screen_candidates(builds, [], rank="grunt", battle_date="2026-11-14", grid=grid)
    assert [c.species_id for c, _ in screened] == ["cc", "bb", "dd", "aa"]
    assert screened[0][1]["hp_left"] == 0.9
    assert screened[0][1]["turns"] == 12


def test_k_cut_keeps_exact_margin_ties_only(cache, monkeypatch):
    monkeypatch.setattr(solo, "supports", lambda *a: False)
    builds = [
        topn.Candidate(name, c.attacker, c.move_flags)
        for name, c in zip(("aa", "bb", "cc", "dd"), candidates(cache)[:4], strict=True)
    ]
    grid = margin_grid({"aa": (0.2, 10), "bb": (0.9, 12), "cc": (0.9, 12), "dd": (0.5, 5)})
    grid.builds = builds
    finalists = []

    def trial_runner(team, pools, **kwargs):
        finalists.append(next(c.species_id for c in builds if c.team == team))
        kwargs.pop("execution")
        return winrate.trials(team, pools, **kwargs)

    pools = [[winrate.Option("target", builds[0].team[0])]] * 3
    topn.rank_character(
        builds,
        pools,
        k=1,
        rank="grunt",
        battle_date="2026-11-14",
        grid=grid,
        trial_runner=trial_runner,
    )
    assert sorted(finalists) == ["bb", "cc"]


def test_grid_aggregates_report_mean_hp_left_and_turns(cache):
    build = candidates(cache)[0]
    target = candidates(cache)[1].team[0]
    pools = [[winrate.Option("a", target), winrate.Option("b", target)]] * 3
    rows, groups = winrate.grid(build.team, pools, rank="grunt", battle_date="2026-11-14")
    for group in groups:
        mine = [r for r in rows if r["slot"] == group["slot"]]
        assert group["mean_player_hp_fraction_left"] == pytest.approx(
            sum(r["player_hp_fraction_left"] for r in mine) / len(mine)
        )
        assert group["mean_turns"] == pytest.approx(sum(r["turns"] for r in mine) / len(mine))
