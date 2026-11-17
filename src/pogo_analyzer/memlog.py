"""Memory readings at refresh phase boundaries (owner pick, 17 Nov 2026: measure first).

Logging only: one stderr line per call, no behaviour change. Reads the process's cgroup v2
counters (the systemd unit's, under the refresh timer) and the main process's resident size;
missing files are skipped.
"""

import sys
from pathlib import Path


def _gib(value):
    return f"{int(value) / 2**30:.1f}G"


def _cgroup():
    try:
        line = Path("/proc/self/cgroup").read_text().splitlines()[0]
    except (OSError, IndexError):
        return None
    if not line.startswith("0::"):
        return None
    return Path("/sys/fs/cgroup") / line[3:].lstrip("/")


def reading(cgroup=None, status=Path("/proc/self/status")):
    """One line: cgroup current/peak/swap and the main process's RSS, whatever is readable."""
    parts = []
    group = cgroup if cgroup is not None else _cgroup()
    if group is not None:
        for name, label in (
            ("memory.current", "cgroup"),
            ("memory.peak", "peak"),
            ("memory.swap.current", "swap"),
        ):
            try:
                parts.append(f"{label} {_gib((group / name).read_text().split()[0])}")
            except (OSError, IndexError, ValueError):
                pass
    try:
        for line in status.read_text().splitlines():
            if line.startswith("VmRSS:"):
                parts.append(f"main RSS {_gib(int(line.split()[1]) * 1024)}")
    except (OSError, IndexError, ValueError):
        pass
    return ", ".join(parts) or "not readable"


def log(phase, file=None):
    print(f"memory: {phase}: {reading()}", file=file or sys.stderr)
