#!/usr/bin/env python
"""Frozen-baseline gate for the ruff hygiene rules.

Why a baseline
--------------
``[tool.ruff.lint] select`` carries two kinds of rule. The strict set
(``E,F,B,BLE,UP,I``) is clean and contributes no baseline entry — a finding
there is a defect introduced by the change under review. The hygiene set (``N``
naming, ``C901`` complexity, ``PLR0913``/``PLR0915`` signature and function
size) carries 201 accepted findings. Blocking every pull request on all of them
would stop delivery; holding the count still and refusing new ones does not.

``ruff-baseline.txt`` records exactly the findings accepted at the last
``freeze``. ``check`` re-runs ruff and compares:

* a finding that is **not** in the baseline fails the build — that is a
  hygiene regression the change introduced;
* a baseline entry that ruff **no longer** reports also fails the build, asking
  for a re-freeze — otherwise the file silently keeps room for a finding to slip
  back in unnoticed. The ratchet only turns one way.

Entries are compared without line numbers, so moving code around does not churn
the file; they ARE compared by count per (file, message), so making the same
mistake a second time in the same file is caught. Because ruff bakes the
measured value into the message (``too complex (13 > 10)``), a function that
gets MORE complex changes its key and reads as a new finding — the numbers
ratchet down too, not just the count.

How precise a key is depends on the rule. ``C901`` names the function it
measured (```save`` is too complex (11 > 10)``), so its key is per-function.
``PLR0913``/``PLR0915`` name none — "Too many arguments in function definition
(7 > 5)" is the whole message — so two same-sized functions in one file share a
key, and fixing one while adding another of the same size in that file nets out
to no change. The measured value in the message still ratchets, and the 56
``C901`` entries are unaffected.

Usage
-----
    poetry run python scripts/ruff_baseline.py check    # CI gate
    poetry run python scripts/ruff_baseline.py freeze   # after fixing findings

``freeze`` rewrites the baseline from the current run. Run it whenever ``check``
reports the baseline is out of date, and commit the result — a shrinking file is
the point.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "ruff-baseline.txt"
TARGETS = ["apps", "config", "core", "scripts"]


def run_ruff() -> list[dict]:
    """Return ruff's findings as parsed JSON. Exits non-zero only on a crash."""
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *TARGETS, "--output-format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    # 0 = clean, 1 = findings, anything else = bad invocation / internal error.
    if proc.returncode not in (0, 1):
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"ruff failed to run (exit {proc.returncode}).")
    return json.loads(proc.stdout or "[]")


def parse(findings: list[dict]) -> tuple[Counter[str], dict[str, list[str]]]:
    """Split ruff's findings into a countable key set plus the real locations.

    A key is ``path: CODE message``; the locations map keeps the ``path:line``
    strings so a failure can point at the actual code rather than at a
    de-numbered key.
    """
    counts: Counter[str] = Counter()
    locations: dict[str, list[str]] = {}
    for finding in findings:
        path = Path(finding["filename"])
        try:
            rel = path.relative_to(ROOT).as_posix()
        except ValueError:  # ruff ran outside ROOT — keep the absolute path
            rel = path.as_posix()
        key = f"{rel}: {finding['code']} {finding['message']}"
        counts[key] += 1
        locations.setdefault(key, []).append(f"{rel}:{finding['location']['row']}")
    return counts, locations


def read_baseline() -> Counter[str]:
    if not BASELINE.exists():
        raise SystemExit(
            f"No baseline at {BASELINE.relative_to(ROOT)} — create one with:\n"
            f"    poetry run python scripts/ruff_baseline.py freeze"
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
        "# ruff baseline — hygiene findings that predate the naming/complexity gate.",
        "# Managed by scripts/ruff_baseline.py; do not hand-edit.",
        "# Regenerate after fixing findings:",
        "#     poetry run python scripts/ruff_baseline.py freeze",
        f"# {total} finding(s).",
        "",
    ]
    body: list[str] = []
    for key in sorted(counts):
        body.extend([key] * counts[key])
    BASELINE.write_text("\n".join(header + body) + "\n")


def cmd_freeze() -> int:
    current, _ = parse(run_ruff())
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
    current, locations = parse(run_ruff())
    baseline = read_baseline()

    added = current - baseline
    removed = baseline - current

    if added:
        print("New ruff findings (not in the baseline):\n")
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
            f"\n{sum(added.values())} new finding(s). Fix them — split the function, "
            "name the\nvariable properly, or group the arguments into a dataclass. "
            "Baselining a NEW\nfinding defeats the gate."
        )

    if removed:
        if added:
            print()
        print("Baseline is out of date — these findings are gone:\n")
        for key in sorted(removed):
            print(f"  ({removed[key]}x) {key}")
        print(
            f"\n{sum(removed.values())} finding(s) fixed. Re-freeze and commit:\n"
            "    poetry run python scripts/ruff_baseline.py freeze"
        )

    if added or removed:
        return 1

    print(f"ruff: no new findings ({sum(current.values())} baselined).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "freeze"))
    args = parser.parse_args()
    return cmd_check() if args.command == "check" else cmd_freeze()


if __name__ == "__main__":
    raise SystemExit(main())
