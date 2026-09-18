#!/usr/bin/env python
"""Drift report for the numeric-constants inventory.

The numeric-constants inventory it reports against is a curated page:
constants grouped by what they govern, each with the reason it holds the value
it does. A generator cannot reproduce that, so this script does not rewrite
it. It reads the constant names that page already mentions, sweeps the code
for module-level numeric constants, and prints what appears in one but not the
other — the one thing the page cannot do for itself, and the reason it carries
a "this is a snapshot" caveat.

That page is NOT under version control (the ``code_audit`` tree is
gitignored), so on a checkout without it the drift comparison is skipped and
you get the plain census instead. ``--list`` works either way.

It is a review aid, not a gate, and exits 0 even when it finds drift: adding a
constant is not a defect, it is something to write down. Expect some noise,
because the inventory deliberately describes a few groups as prose (PDF column
geometry, for one) instead of naming every member. ``--strict`` exits non-zero
on drift, for wiring into CI if that friction is ever wanted.

Usage
-----
    poetry run python scripts/tunables.py            # drift report
    poetry run python scripts/tunables.py --list     # every constant found
    poetry run python scripts/tunables.py --strict   # non-zero when drifted
"""

from __future__ import annotations

import argparse
import ast
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent.parent
INVENTORY = REPO / "docs" / "code_audit" / "numeric-constants-inventory.md"
FRONTEND = REPO / "jasmin-core" / "react-core" / "src"

BACKEND_DIRS = ("apps", "core", "config", "scripts")
SKIP_PARTS = {
    "migrations",
    "__pycache__",
    "tests",
    "venv",
    "staticfiles",
    "media",
    "node_modules",
    "generated",
}

# A name counts as documented when it appears anywhere inside a backticked
# span, not only when the span is exactly the name: the inventory writes some
# entries as ``DEMO_CUSTOMER_NUMBER_START = 90001``, value included.
CODE_SPAN = re.compile(r"`([^`]+)`")
DOCUMENTED_NAME = re.compile(r"\b(_?[A-Z][A-Z0-9_]{2,})\b")
TS_CONSTANT = re.compile(
    r"^[ \t]*(?:export[ \t]+)?const[ \t]+(_?[A-Z][A-Z0-9_]*)"
    r"[ \t]*(?::[^=]+)?=[ \t]*(-?\d[\d_]*(?:\.\d+)?)[ \t]*;?[ \t]*$",
    re.MULTILINE,
)

_BINARY_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Pow: lambda a, b: a**b,
}


class Constant(NamedTuple):
    name: str
    where: str
    value: str


def _worth_scanning(path: Path) -> bool:
    if SKIP_PARTS & set(path.parts):
        return False
    # ``test_x.py`` on the backend, ``x.test.tsx`` / ``x.spec.ts`` on the front.
    return not path.name.startswith("test_") and not re.search(
        r"\.(test|spec)\.", path.name
    )


def _iter_files(base: Path, suffixes: tuple[str, ...]) -> Iterator[Path]:
    for path in sorted(base.rglob("*")):
        if path.suffix in suffixes and path.is_file() and _worth_scanning(path):
            yield path


def _numeric(node: ast.expr) -> float | None:
    """The node's value if it is a plain number or arithmetic over numbers
    (``15 * 60``), else ``None``. Anything referring to a name is not a
    literal tunable and is skipped."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            return None
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _numeric(node.operand)
        return None if inner is None else -inner
    if isinstance(node, ast.BinOp):
        operation = _BINARY_OPS.get(type(node.op))
        left, right = _numeric(node.left), _numeric(node.right)
        if operation is None or left is None or right is None:
            return None
        try:
            return operation(left, right)
        except (ArithmeticError, ValueError):
            return None
    return None


def _format(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def _assigned_names(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def backend_constants() -> list[Constant]:
    found: list[Constant] = []
    for directory in BACKEND_DIRS:
        base = ROOT / directory
        if not base.is_dir():
            continue
        for path in _iter_files(base, (".py",)):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, ValueError):
                continue
            where = path.relative_to(ROOT).as_posix()
            for node in tree.body:
                if not isinstance(node, ast.Assign | ast.AnnAssign):
                    continue
                # ``AnnAssign`` carries no value for a bare declaration.
                value = _numeric(node.value) if node.value is not None else None
                if value is None:
                    continue
                for name in _assigned_names(node):
                    if name.lstrip("_").isupper():
                        found.append(Constant(name, where, _format(value)))
    return found


def frontend_constants() -> list[Constant]:
    if not FRONTEND.is_dir():
        return []
    found: list[Constant] = []
    for path in _iter_files(FRONTEND, (".ts", ".tsx")):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        where = path.relative_to(FRONTEND.parent).as_posix()
        for name, raw in TS_CONSTANT.findall(source):
            found.append(Constant(name, where, raw))
    return found


def documented_names() -> set[str] | None:
    """Every constant name the inventory mentions, or ``None`` when the file
    is out of reach (the backend container does not mount ``docs/``)."""
    try:
        text = INVENTORY.read_text(encoding="utf-8")
    except OSError:
        return None
    names: set[str] = set()
    for span in CODE_SPAN.findall(text):
        names.update(DOCUMENTED_NAME.findall(span))
    return names


def _report(label: str, rows: list[Constant]) -> None:
    print(f"\n{label} ({len(rows)}):\n")
    for row in sorted(rows):
        print(f"  {row.name} = {row.value}  ({row.where})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list", action="store_true", help="print every constant found"
    )
    parser.add_argument(
        "--strict", action="store_true", help="exit non-zero when drifted"
    )
    args = parser.parse_args()

    backend = backend_constants()
    frontend = frontend_constants()
    swept = backend + frontend

    print(
        f"tunables: {len(backend)} backend, {len(frontend)} frontend "
        f"module-level numeric constants."
    )
    if not frontend:
        print("  (frontend tree not reachable from here — backend only)")

    if args.list:
        _report("Backend", backend)
        _report("Frontend", frontend)

    documented = documented_names()
    if documented is None:
        print(f"\nNo inventory at {INVENTORY} — skipping the drift report.")
        return 0

    swept_names = {row.name for row in swept}
    undocumented = [row for row in swept if row.name not in documented]
    vanished = sorted(documented - swept_names)

    if undocumented:
        _report("In the code, not named in the inventory", undocumented)
    if vanished:
        print(f"\nNamed in the inventory, not found in the sweep ({len(vanished)}):\n")
        for name in vanished:
            print(f"  {name}")
        print(
            "\n  (some of these are prose references to settings, throttle rates\n"
            "   or query-param bounds rather than module-level constants)"
        )
    if not undocumented and not vanished:
        print("\nInventory and code agree.")

    return 1 if args.strict and (undocumented or vanished) else 0


if __name__ == "__main__":
    raise SystemExit(main())
