"""Drift guard for ``run_periodic_tasks_now``'s TASK_REGISTRY.

The command fires every Huey periodic task synchronously for dev/QA, but it
iterates a STATIC registry — a new ``@db_periodic_task`` / ``@periodic_task``
added without registering it is silently omitted, and the command still reports
all-green (TASK-7). This test AST-scans the app tree for periodic-task
decorators and fails the build when one is neither in TASK_REGISTRY nor
allow-listed as pure infra, so the registry can't drift out of coverage again.
"""

from __future__ import annotations

import ast
from pathlib import Path

from apps.shared.tenants.management.commands.run_periodic_tasks_now import (
    _INFRA_ONLY_PERIODIC_TASKS,
    TASK_REGISTRY,
)

DJANGO_CORE = Path(__file__).resolve().parents[4]
APPS = DJANGO_CORE / "apps"
# Standing instruction: cultivation / economics / staff are out of scope.
IGNORED_APPS = frozenset({"cultivation", "economics", "staff"})
_PERIODIC_DECORATORS = frozenset({"db_periodic_task", "periodic_task"})


def _decorator_name(node: ast.expr) -> str | None:
    """The bare callable name of a decorator (``@x(...)`` or ``@x``)."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _discover_periodic_tasks() -> set[tuple[str, str]]:
    """(module_path, function_name) for every periodic task in the app tree."""
    found: set[tuple[str, str]] = set()
    for path in sorted(APPS.rglob("*.py")):
        parts = path.relative_to(APPS).parts
        if parts[0] in IGNORED_APPS or "tests" in parts or "migrations" in parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if any(
                _decorator_name(dec) in _PERIODIC_DECORATORS
                for dec in node.decorator_list
            ):
                module_path = ".".join(
                    path.relative_to(DJANGO_CORE).with_suffix("").parts
                )
                found.add((module_path, node.name))
    return found


def test_periodic_task_registry_complete() -> None:
    discovered = _discover_periodic_tasks()
    # Non-vacuity guard: a broken scan (empty set) would pass trivially.
    assert discovered, "No periodic tasks discovered — the AST scan is mis-pathed."

    registered = {
        (module_path, name)
        for module_path, names in TASK_REGISTRY.items()
        for name in names
    }
    missing = sorted(
        f"{module_path}.{name}"
        for (module_path, name) in discovered
        if (module_path, name) not in registered
        and name not in _INFRA_ONLY_PERIODIC_TASKS
    )
    assert not missing, (
        "Periodic task(s) not registered in run_periodic_tasks_now.TASK_REGISTRY "
        "(add them there, or to _INFRA_ONLY_PERIODIC_TASKS if pure infra):\n"
        + "\n".join(f"  - {m}" for m in missing)
    )


def test_registry_has_no_phantom_entries() -> None:
    """Every registered (module, name) must actually exist as a periodic task —
    catches a typo or a task that was renamed/removed without updating the list."""
    discovered = _discover_periodic_tasks()
    registered = {
        (module_path, name)
        for module_path, names in TASK_REGISTRY.items()
        for name in names
    }
    phantom = sorted(
        f"{module_path}.{name}"
        for (module_path, name) in registered
        if (module_path, name) not in discovered
    )
    assert not phantom, (
        "TASK_REGISTRY lists task(s) that are not @db_periodic_task/"
        "@periodic_task functions (renamed, removed, or a typo):\n"
        + "\n".join(f"  - {m}" for m in phantom)
    )
