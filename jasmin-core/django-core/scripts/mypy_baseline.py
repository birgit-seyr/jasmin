#!/usr/bin/env python
"""Frozen-baseline gate for mypy.

Why a baseline
--------------
Type-checking was switched on over a codebase that predates it, so the first
clean run reported hundreds of findings. Two options were available: block every
pull request until all of them are gone (nothing else ships for weeks), or hold
the current count still and refuse anything NEW. This is the second.

``mypy-baseline.txt`` records exactly the findings that existed when the gate was
installed. ``check`` re-runs mypy and compares:

* a finding that is **not** in the baseline fails the build — that is a type
  error introduced by the change under review;
* a baseline entry that mypy **no longer** reports also fails the build, asking
  for a re-freeze — otherwise the file silently keeps room for a future error to
  slip back in unnoticed. The ratchet only turns one way.

Entries are compared without line numbers, so moving code around does not churn
the file; they ARE compared by count per (file, message), so making the same
mistake a second time in the same file is caught.

Usage
-----
    poetry run python scripts/mypy_baseline.py check    # CI gate
    poetry run python scripts/mypy_baseline.py freeze   # after fixing findings

``freeze`` rewrites the baseline from the current run. Run it whenever ``check``
reports the baseline is out of date, and commit the result — a shrinking file is
the point.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

# mypy needs the Django settings module importable to load its plugin, and
# ``config.settings`` refuses to import with production-shaped defaults unless
# DEBUG is on (the boot guards). Static analysis is not a deploy, and manage.py
# does the same for local CLI use, so default it on here too — an explicitly set
# DEBUG still wins.
os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "mypy-baseline.txt"
TARGETS = ["apps", "config", "core", "scripts"]

# "apps/x/y.py:123: error: message  [code]" -> drop the line number, which is the
# only part that moves when unrelated code above it changes.
ERROR_LINE = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+): error: (?P<message>.*)$")


def run_mypy() -> list[str]:
    """Return mypy's raw stdout lines. Exits non-zero only on a mypy crash."""
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", *TARGETS],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 1):  # 0 = clean, 1 = findings, 2 = crash/usage
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"mypy failed to run (exit {proc.returncode}).")
    return proc.stdout.splitlines()


def parse(lines: list[str]) -> tuple[Counter[str], dict[str, list[str]]]:
    """Split mypy output into a countable key set plus the original locations.

    Returns ``(counts, locations)`` where a key is ``path: message`` and the
    locations map keeps the real ``path:line`` strings so a failure can point at
    the actual code rather than at a de-numbered key.
    """
    counts: Counter[str] = Counter()
    locations: dict[str, list[str]] = {}
    for line in lines:
        match = ERROR_LINE.match(line)
        if not match:  # notes, summaries, blank lines
            continue
        key = f"{match['path']}: {match['message']}"
        counts[key] += 1
        locations.setdefault(key, []).append(f"{match['path']}:{match['line']}")
    return counts, locations


def read_baseline() -> Counter[str]:
    if not BASELINE.exists():
        raise SystemExit(
            f"No baseline at {BASELINE.relative_to(ROOT)} — create one with:\n"
            f"    poetry run python scripts/mypy_baseline.py freeze"
        )
    counts: Counter[str] = Counter()
    for line in BASELINE.read_text().splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        counts[line] += 1
    return counts


def write_baseline(counts: Counter[str]) -> None:
    total = sum(counts.values())
    header = [
        "# mypy baseline — findings that predate the type-check gate.",
        "# Managed by scripts/mypy_baseline.py; do not hand-edit.",
        "# Regenerate after fixing findings:",
        "#     poetry run python scripts/mypy_baseline.py freeze",
        f"# {total} finding(s).",
        "",
    ]
    body = []
    for key in sorted(counts):
        body.extend([key] * counts[key])
    BASELINE.write_text("\n".join(header + body) + "\n")


def cmd_freeze() -> int:
    current, _ = parse(run_mypy())
    previous = sum(read_baseline().values()) if BASELINE.exists() else None
    write_baseline(current)
    total = sum(current.values())
    if previous is None:
        print(f"Wrote {BASELINE.relative_to(ROOT)} with {total} finding(s).")
    else:
        print(
            f"Wrote {BASELINE.relative_to(ROOT)}: {previous} -> {total} finding(s) "
            f"({previous - total:+d})."
        )
    return 0


def cmd_check() -> int:
    current, locations = parse(run_mypy())
    baseline = read_baseline()

    added = current - baseline
    removed = baseline - current

    if added:
        print("New type errors (not in the baseline):\n")
        for key in sorted(added):
            _, message = key.split(": ", 1)
            places = locations[key]
            # When the same finding already existed elsewhere in the file, the
            # baseline cannot say WHICH occurrence is the new one — list them all
            # and name how many are new rather than picking one arbitrarily.
            if added[key] < len(places):
                print(f"  {added[key]} new of {len(places)}: {message}")
                for where in places:
                    print(f"      {where}")
            else:
                for where in places:
                    print(f"  {where}: {message}")
        print(
            f"\n{sum(added.values())} new finding(s). Fix them, or — if a finding "
            "is a stub gap\nrather than a real defect — narrow the type at the "
            "source the way\ncore/tenant_db.py and apps/shared/request_utils.py do."
        )

    if removed:
        if added:
            print()
        print("Baseline is out of date — these findings are gone:\n")
        for key in sorted(removed):
            print(f"  ({removed[key]}x) {key}")
        print(
            f"\n{sum(removed.values())} finding(s) fixed. Re-freeze and commit:\n"
            "    poetry run python scripts/mypy_baseline.py freeze"
        )

    if added or removed:
        return 1

    print(f"mypy: no new findings ({sum(current.values())} baselined).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "freeze"))
    args = parser.parse_args()
    return cmd_check() if args.command == "check" else cmd_freeze()


if __name__ == "__main__":
    raise SystemExit(main())
