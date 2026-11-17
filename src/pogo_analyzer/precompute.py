"""Resumable, atomic static reports from the offline top-N engine."""

import ast
import fcntl
import hashlib
import json
import os
import re
import resource
import sys
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path

from . import __version__, memlog, sim_cli, topn_cli
from .lineups import PVPOKE_GM_URL
from .sim.rocket import rule_data


def add_parser(commands):
    sub = commands.add_parser("precompute", help="Write cached top-N estimates for a static site")
    sub.add_argument("--out", type=Path, required=True)
    sub.add_argument("--character")
    topn_cli.add_options(sub)
    sub.add_argument("--workers", type=int, default=3)
    sub.add_argument("--nice", type=int, default=10)
    sub.add_argument("--force", action="store_true")
    sub.add_argument(
        "--skip-overall",
        action="store_true",
        help="Refresh characters without changing the overall",
    )


def _json_bytes(value):
    # The source cache stores parsed JSON bodies, so hash their canonical JSON bytes.
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _hash(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _relative_imports(path, root):
    """Package modules one file imports with relative imports (`from . import x`, `from .a import
    b`), resolved to files under root."""
    package = list(path.relative_to(root).parent.parts)
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        base = package[: len(package) - (node.level - 1)] + (
            node.module.split(".") if node.module else []
        )
        for parts in (base, *(base + [alias.name] for alias in node.names)):
            for candidate in (
                root.joinpath(*parts).with_suffix(".py"),
                root.joinpath(*parts, "__init__.py"),
            ):
                if parts and candidate.is_file():
                    found.add(candidate)
        found.add(root / "__init__.py")
    return found


def result_modules(root=None):
    """The package files results depend on: precompute.py and everything it imports, followed
    through relative imports. The site renderer and the CLI wrappers are outside it, so a
    site-only change keeps the reuse key (bead pgo-r8d)."""
    root = Path(root or Path(__file__).resolve().parent)
    seen, todo = set(), [root / "precompute.py"]
    while todo:
        path = todo.pop()
        if path not in seen:
            seen.add(path)
            todo.extend(_relative_imports(path, root))
    return sorted(seen)


def code_hash():
    """Hash the result code (result_modules) and the package's data JSON, independent of cwd."""
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    files = [*result_modules(root), *(p for p in root.rglob("*.json"))]
    for path in sorted(set(files)):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _sources(cache_dir, sources):
    records = []
    for source in sources:
        filename = hashlib.sha256(source["url"].encode()).hexdigest() + ".json"
        entry = json.loads((cache_dir / "sources" / filename).read_text())
        if entry["url"] != source["url"] or entry["status"] != 200:
            raise ValueError(f"missing successful source cache entry: {source['url']}")
        records.append({**source, "sha256": _hash(entry["body"])})
    return records


def atomic_json(path, value):
    """Replace only after a complete, flushed and synced write beside the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, separators=(",", ":"))
            stream.flush()
            umask = os.umask(0)
            os.umask(umask)
            os.fchmod(stream.fileno(), 0o666 & ~umask)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _cached(path, key, force):
    if not force:
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict) and data.get("key") == key:
                return data
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            pass
    return None


def _slug(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    if not slug:
        raise ValueError(f"cannot make a filename for character {name!r}")
    return slug


def _character_key(shared_key, report, planned, unresolved):
    _, pools, records = planned
    return _hash(
        {
            "shared_key": shared_key,
            "name": report["name"],
            "rank": report["rank"],
            "pools": [
                [
                    {
                        "species": option.species,
                        "fast": option.combatant.fast.id,
                        "charged": [move.id for move in option.combatant.charged],
                    }
                    for option in pool
                ]
                for pool in pools
            ],
            "unresolved": [row for row in unresolved if row["character"] == report["name"]],
            "defenders": records,
        }
    )


def _merge_target(args, shared_key):
    """Reject incompatible partial runs before publishing any character files."""
    path = args.out / "manifest.json"
    if args.all or not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot merge --character into invalid manifest: {path}") from exc
    if not isinstance(manifest, dict) or manifest.get("shared_key") != shared_key:
        raise ValueError(
            f"cannot merge --character: existing manifest has a different shared key: {path}; "
            "use a separate --out directory or run all characters"
        )
    return manifest


def _provenance(data):
    return {
        field: data[field]
        for field in (
            "computed_for_battle_date",
            "computed_for_battle_date_source",
            "valid_for",
        )
    }


def _skipped_overall(out, key, force):
    """Retain the previous overall without changing its file or computation date."""
    try:
        manifest = json.loads((out / "manifest.json").read_text())
    except (OSError, ValueError):
        manifest = None
    previous = manifest.get("overall") if isinstance(manifest, dict) else None
    if (
        isinstance(previous, dict)
        and previous.get("file") is not None
        and (out / "overall.json").exists()
    ):
        cached = _cached(out / "overall.json", key, force) if previous["file"] else None
        if cached is not None:
            return {
                "key": key,
                "file": "overall.json",
                "status": "reused",
                **_provenance(cached),
            }
        if previous.get("key") is not None:
            return {**previous, "status": "stale"}
    return {"key": None, "file": None, "status": "skipped"}


def _peak_memory():
    # Linux reports KiB; macOS reports bytes.
    divisor = 1024 if sys.platform == "darwin" else 1
    return {
        "parent_ru_maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // divisor,
        "max_child_ru_maxrss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        // divisor,
    }


def _run_locked(args, start, niceness):
    args.all = args.character is None
    data, planned, candidates = topn_cli.prepare_output(args)
    data["params"].update(
        battle_date=data["battle_date"],
        rcpm_table=args.rcpm_table,
        candidates=None
        if args.candidates is None
        else sorted(selector.strip() for selector in args.candidates.split(",")),
    )
    sources = _sources(args.cache_dir, data["sources"])
    package_hash = code_hash()
    valid_for = {
        "era": data["era"],
        "extrapolated": data["battle_date"] > rule_data()["latest_source_date"],
    }
    shared_key = _hash(
        {
            "gamemaster": next(s["sha256"] for s in sources if s["url"] == PVPOKE_GM_URL),
            "code_hash": package_hash,
            # Dates within the same era share results (and the extrapolation flag).
            "params": {k: v for k, v in data["params"].items() if k != "battle_date"},
            **valid_for,
            "validation_hash": _hash(data["validation"]),
        }
    )
    existing = _merge_target(args, shared_key)
    header = {
        **{k: v for k, v in data.items() if k != "characters"},
        "computed_for_battle_date": data["battle_date"],
        "computed_for_battle_date_source": data["battle_date_source"],
        "valid_for": valid_for,
    }
    jobs, slugs = [], set()
    existing_slugs = (
        {entry["slug"]: entry["name"] for entry in existing["characters"]} if existing else {}
    )
    for index, report in enumerate(data["characters"]):
        slug = _slug(report["name"])
        if slug in slugs or existing_slugs.get(slug, report["name"]) != report["name"]:
            raise ValueError(f"duplicate character filename: {slug}")
        slugs.add(slug)
        file = f"characters/{slug}.json"
        key = _character_key(shared_key, report, planned[report["name"]], data["unresolved"])
        cached = _cached(args.out / file, key, args.force)
        if cached is not None:
            data["characters"][index] = cached["character"]
        jobs.append((file, slug, key, cached))

    overall_key = _hash(
        sorted(
            (report["name"], job[2]) for report, job in zip(data["characters"], jobs, strict=True)
        )
    )
    cached_overall = (
        _cached(args.out / "overall.json", overall_key, args.force)
        if args.all and not args.skip_overall
        else None
    )
    changed = any(cached is None for _, _, _, cached in jobs)
    need_overall = args.all and not args.skip_overall and (changed or cached_overall is None)
    need_pool = args.workers > 1 and (changed or need_overall)
    context = (
        sim_cli._pool_context().Pool(args.workers, initializer=sim_cli._ignore_interrupt)
        if need_pool
        else nullcontext(None)
    )
    entries = []
    with context as pool:

        def mapper(function, items):
            if pool is None:
                return map(function, items)
            chunksize = max(1, min(16, len(items) // (args.workers * 4)))
            return pool.imap(function, items, chunksize=chunksize)

        for report, (file, slug, key, cached) in zip(data["characters"], jobs, strict=True):
            character_start = time.perf_counter()
            if cached is None:
                if "reason" not in report:
                    print(
                        f"estimate: {report['name']}: screening {len(candidates)} builds; "
                        f"full battles for up to {args.k} species per level.",
                        file=sys.stderr,
                    )
                topn_cli.rank_report(
                    report,
                    planned[report["name"]],
                    candidates,
                    args,
                    data["validation"],
                    mapper=mapper,
                    battle_date=data["battle_date"],
                )
                character_header = {
                    **header,
                    **{
                        field: [row for row in data[field] if row["character"] == report["name"]]
                        for field in ("unresolved", "unavailable")
                    },
                }
                atomic_json(args.out / file, {**character_header, "character": report, "key": key})
            status = "reused" if cached is not None else "computed"
            if "reason" in report:
                status = "unavailable"
            print(f"estimate: {report['name']}: {status} ({file}).", file=sys.stderr)
            memlog.log(report["name"])
            entries.append(
                {
                    "name": report["name"],
                    "slug": slug,
                    "rank": report["rank"],
                    "key": key,
                    "file": file,
                    "status": status,
                    **_provenance(cached if cached is not None else header),
                    "runtime_seconds": time.perf_counter() - character_start,
                }
            )
        overall = {"key": None, "file": None, "status": "unavailable"}
        if args.skip_overall:
            overall = _skipped_overall(args.out, overall_key, args.force)
            print(f"estimate: overall: skipped ({overall['status']}).", file=sys.stderr)
        elif args.all:
            if need_overall:
                result = topn_cli.complete_overall(data, planned, candidates, args, mapper=mapper)
                atomic_json(args.out / "overall.json", {**header, **result, "key": overall_key})
            overall = {
                "key": overall_key,
                "file": "overall.json",
                "status": "computed" if need_overall else "reused",
                **_provenance(header if need_overall else cached_overall),
            }
            print(f"estimate: overall: {overall['status']}.", file=sys.stderr)
            memlog.log("overall")
    if existing is not None:
        merged = {entry["name"]: entry for entry in existing["characters"]}
        entries_changed = changed or any(
            entry["key"] != merged.get(entry["name"], {}).get("key") for entry in entries
        )
        merged.update((entry["name"], entry) for entry in entries)
        entries = list(merged.values())
        overall = dict(existing["overall"])
        if entries_changed and overall["file"] is not None:
            overall["status"] = "stale"
    manifest = {
        "tool_version": __version__,
        "code_hash": package_hash,
        "shared_key": shared_key,
        "params": data["params"],
        "battle_date": data["battle_date"],
        "battle_date_source": data["battle_date_source"],
        "era": data["era"],
        "valid_for": valid_for,
        "validation_label": data["validation_label"],
        "sources": sources,
        "workers": args.workers,
        "skip_overall": args.skip_overall,
        "niceness": niceness,
        "characters": entries,
        "overall": overall,
        "runtime_seconds": time.perf_counter() - start,
        "peak_memory": _peak_memory(),
    }
    atomic_json(args.out / "manifest.json", manifest)
    return manifest


def run(args):
    if args.skip_overall and args.character is not None:
        raise ValueError(
            "--skip-overall needs an all-characters run; --character never computes the overall"
        )
    start = time.perf_counter()
    try:
        worker_limit = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        worker_limit = os.cpu_count() or 1
    if not 1 <= args.workers <= worker_limit:
        raise ValueError(f"--workers must be between 1 and {worker_limit}")
    niceness = os.nice(args.nice) if args.nice else os.getpriority(os.PRIO_PROCESS, 0)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(
                f"precompute already running: output directory is locked: {args.out}"
            ) from None
        # Keep the lock held until after the pool is reaped and the manifest is replaced.
        return _run_locked(args, start, niceness)


def main_precompute(args, arg_parser):
    try:
        run(args)
    except (ValueError, OSError) as exc:
        arg_parser.error(str(exc))
    return 0
