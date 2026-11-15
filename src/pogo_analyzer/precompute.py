"""Resumable, atomic static reports from the offline top-N engine."""

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

from . import __version__, sim_cli, topn_cli
from .sim.rocket import rule_data


def add_parser(commands):
    sub = commands.add_parser("precompute", help="Write cached top-N estimates for a static site")
    sub.add_argument("--out", type=Path, required=True)
    sub.add_argument("--character")
    topn_cli.add_options(sub)
    sub.add_argument("--workers", type=int, default=3)
    sub.add_argument("--nice", type=int, default=10)
    sub.add_argument("--force", action="store_true")


def _json_bytes(value):
    # The source cache stores parsed JSON bodies, so hash their canonical JSON bytes.
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _hash(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def code_hash():
    """Hash package code and data from the installed package, independent of cwd."""
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.suffix in (".py", ".json")):
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
    key = _hash(
        {
            "sources": [s["sha256"] for s in sources],
            "code_hash": package_hash,
            # Dates within the same era share results (and the extrapolation flag).
            "params": {k: v for k, v in data["params"].items() if k != "battle_date"},
            "era": data["era"],
            "extrapolated": data["battle_date"] > rule_data()["latest_source_date"],
            "validation_label": data["validation_label"],
        }
    )
    header = {k: v for k, v in data.items() if k != "characters"}
    jobs, slugs = [], set()
    for index, report in enumerate(data["characters"]):
        slug = _slug(report["name"])
        if slug in slugs:
            raise ValueError(f"duplicate character filename: {slug}")
        slugs.add(slug)
        file = f"characters/{slug}.json"
        cached = _cached(args.out / file, key, args.force)
        if cached is not None:
            data["characters"][index] = cached["character"]
        jobs.append((file, slug, cached))

    overall_key = _hash([key for _ in jobs])
    cached_overall = (
        _cached(args.out / "overall.json", overall_key, args.force) if args.all else None
    )
    changed = any(cached is None for _, _, cached in jobs)
    need_overall = args.all and (changed or cached_overall is None)
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

        for report, (file, slug, cached) in zip(data["characters"], jobs, strict=True):
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
            entries.append(
                {
                    "name": report["name"],
                    "slug": slug,
                    "rank": report["rank"],
                    "key": key,
                    "file": file,
                    "status": status,
                    "runtime_seconds": time.perf_counter() - character_start,
                }
            )
        overall = {"key": None, "file": None, "status": "unavailable"}
        if args.all:
            if need_overall:
                result = topn_cli.complete_overall(data, planned, candidates, args, mapper=mapper)
                atomic_json(args.out / "overall.json", {**header, **result, "key": overall_key})
            overall = {
                "key": overall_key,
                "file": "overall.json",
                "status": "computed" if need_overall else "reused",
            }
            print(f"estimate: overall: {overall['status']}.", file=sys.stderr)
    manifest = {
        "tool_version": __version__,
        "code_hash": package_hash,
        "params": data["params"],
        "battle_date": data["battle_date"],
        "battle_date_source": data["battle_date_source"],
        "era": data["era"],
        "validation_label": data["validation_label"],
        "sources": sources,
        "workers": args.workers,
        "niceness": niceness,
        "characters": entries,
        "overall": overall,
        "runtime_seconds": time.perf_counter() - start,
        "peak_memory": _peak_memory(),
    }
    atomic_json(args.out / "manifest.json", manifest)
    return manifest


def run(args):
    start = time.perf_counter()
    if not 1 <= args.workers <= (os.cpu_count() or 1):
        raise ValueError(f"--workers must be between 1 and {os.cpu_count() or 1}")
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
