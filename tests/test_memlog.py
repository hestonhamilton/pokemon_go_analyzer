import io

from pogo_analyzer import memlog


def test_reading_uses_cgroup_counters_and_rss(tmp_path):
    group = tmp_path / "unit"
    group.mkdir()
    (group / "memory.current").write_text(f"{3 * 2**30}\n")
    (group / "memory.peak").write_text(f"{12 * 2**30}\n")
    (group / "memory.swap.current").write_text("0\n")
    status = tmp_path / "status"
    status.write_text("Name:\tpython\nVmRSS:\t  1048576 kB\n")
    assert memlog.reading(group, status) == "cgroup 3.0G, peak 12.0G, swap 0.0G, main RSS 1.0G"


def test_reading_skips_missing_files(tmp_path):
    assert memlog.reading(tmp_path / "gone", tmp_path / "gone") == "not readable"


def test_log_line():
    out = io.StringIO()
    memlog.log("overall", file=out)
    assert out.getvalue().startswith("memory: overall: ")
