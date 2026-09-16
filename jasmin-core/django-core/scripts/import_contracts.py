#!/usr/bin/env python
"""Import-direction gate for the backend package layering.

What it enforces
----------------
CLAUDE.md states two one-way layering rules. ESLint's ``no-restricted-imports``
enforces the frontend half of the same idea; this script is the backend half.

1. ``apps/commissioning/`` is meant to be extractable into its own project, so
   the isolation is ONE-WAY: other apps may import FROM commissioning, but
   commissioning may import only the always-shared foundation
   (``accounts``, ``authz``, ``shared``). Every other app import is an edge that
   has to be unwound at extraction.
2. ``apps/shared/`` is the bottom layer: the feature apps build on it, so it
   must not reach back up into them.

Why not import-linter
---------------------
import-linter would do this, but it is a new runtime dependency and CI runs
``poetry check --lock`` — adding it means re-locking the whole graph for a gate
that needs ~100 lines of stdlib ``ast``. This walks the import graph directly
instead, with no dependency at all.

It reads the source rather than importing it, which matters here: the edges that
actually exist are DEFERRED imports inside functions (done precisely to keep the
module-level graph clean), and those are invisible to anything that only
inspects imported modules.

Exemptions
----------
The known extraction blockers are listed in ``EXEMPTIONS`` with the reason and
the unwind plan — named, not silently allowed. The list ratchets in BOTH
directions, like the mypy and ruff baselines: an exemption that no longer
matches any import is itself an error, so a blocker that gets unwound has to be
struck from the list instead of lingering as permission for it to come back.

Usage
-----
    poetry run python scripts/import_contracts.py
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ROOT / "apps"

# The always-shared foundation. ``commissioning`` may depend on these because
# they travel with it at extraction (or are generic enough to vendor).
FOUNDATION = frozenset({"accounts", "authz", "shared"})

# Everything under apps/ that is a feature app rather than foundation. Derived
# from the directory rather than listed, so an app created tomorrow is inside
# both contracts on its first day and no directory can sit unclassified.
FEATURE_APPS = (
    frozenset(
        path.name
        for path in APPS.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    )
    - FOUNDATION
)


@dataclass(frozen=True)
class Contract:
    """One layering rule: files under ``source_dir`` must not import ``forbidden``."""

    name: str
    source_dir: str  # repo-relative, e.g. "apps/commissioning"
    forbidden: frozenset[str]  # app package names, e.g. {"payments"}
    rationale: str


@dataclass(frozen=True)
class Exemption:
    """A known, accepted violation of a contract.

    ``module`` is the repo-relative path of the importing file; ``imports`` the
    dotted prefix it is allowed to import. Both must match for the exemption to
    apply, so an exemption for one file does not quietly cover another.
    """

    module: str
    imports: str
    reason: str


CONTRACTS = [
    Contract(
        name="commissioning is one-way extractable",
        source_dir="apps/commissioning",
        forbidden=frozenset(a for a in FEATURE_APPS if a != "commissioning"),
        rationale=(
            "apps/commissioning is to be extracted into its own project. Other apps may "
            "import FROM it; it may import only accounts/authz/shared."
        ),
    ),
    Contract(
        name="shared is the bottom layer",
        source_dir="apps/shared",
        forbidden=FEATURE_APPS,
        rationale=(
            "apps/shared underpins the feature apps, so it must not reach back up into "
            "them. Move the shared part down, or invert the dependency through a hook "
            "seam like apps/shared/subscription_hooks.py."
        ),
    ),
]

EXEMPTIONS = [
    # ---- Contract: commissioning is one-way extractable -------------------
    Exemption(
        module="apps/commissioning/tasks.py",
        imports="apps.notifications.jobs",
        reason=(
            "Background-job infra (run_job / progress helpers) for bulk-send jobs. "
            "Unwind by relocating that infra, incl. the BackgroundJob model and its "
            "migration, into apps/shared/."
        ),
    ),
    Exemption(
        module="apps/commissioning/views/reseller_views.py",
        imports="apps.notifications.jobs",
        reason=(
            "enqueue_job for the reseller bulk-send endpoints. Same unwind as "
            "apps/commissioning/tasks.py: move the job infra into apps/shared/."
        ),
    ),
    Exemption(
        module="apps/commissioning/viewsets/members_viewsets.py",
        imports="apps.notifications.models",
        reason=(
            "Read-only EmailLog query behind the member 'Sent emails' modal. Unwind by "
            "exposing a shared read interface for sent mail."
        ),
    ),
    # ---- Contract: shared is the bottom layer -----------------------------
    Exemption(
        module="apps/shared/invitations.py",
        imports="apps.commissioning",
        reason=(
            "Invitation flow reads Member / UserInvitation / InvitationStatus. The "
            "invitation models are commissioning-owned domain data; unwind by moving "
            "the invitation models down into shared, or the flow up into commissioning."
        ),
    ),
    Exemption(
        module="apps/shared/super_admin/viewsets.py",
        imports="apps.commissioning",
        reason=(
            "Tenant admin resolves Reseller rows when provisioning tenant users. Unwind "
            "behind a registry the feature app populates, like subscription_hooks."
        ),
    ),
    Exemption(
        module="apps/shared/tenants/email_service.py",
        imports="apps.notifications",
        reason=(
            "Tenant mail rendering uses EmailTemplate / EmailLog / template_renderer / "
            "registry. Unwind by moving the template-rendering core into apps/shared/ "
            "and leaving only dispatch in notifications."
        ),
    ),
]


@dataclass
class Violation:
    module: str
    imported: str
    line: int
    contract: Contract


@dataclass
class Walker:
    """Collects the dotted module names a file imports, including deferred ones."""

    module_path: Path
    found: list[tuple[str, int]] = field(default_factory=list)

    def collect(self) -> list[tuple[str, int]]:
        source = self.module_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(self.module_path))
        package = self._package_parts()
        # ast.walk reaches nested function bodies, which is the point: the real
        # cross-app edges are deliberately deferred imports inside functions.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.found.append((alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                resolved = self._resolve(node, package)
                if resolved == "apps":
                    # ``from apps import notifications`` carries the app name in
                    # the alias, not in the module, so expand it — otherwise the
                    # edge is invisible to app_of and to both contracts.
                    self.found.extend(
                        (f"apps.{alias.name}", node.lineno) for alias in node.names
                    )
                else:
                    self.found.append((resolved, node.lineno))
        return self.found

    def _package_parts(self) -> list[str]:
        """Dotted parts of the package CONTAINING this module, for relative imports."""
        rel = self.module_path.relative_to(ROOT)
        return list(rel.parts[:-1])

    def _resolve(self, node: ast.ImportFrom, package: list[str]) -> str:
        """Turn ``from ..x import y`` into an absolute dotted name."""
        if not node.level:
            return node.module or ""
        # level 1 == current package, level 2 == parent, ...
        base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
        return ".".join([*base, node.module] if node.module else base)


def iter_source_files(source_dir: Path):
    """Every production .py under ``source_dir``.

    Tests and migrations are excluded deliberately. Migrations are generated and
    routinely reference other apps' historical models; test modules legitimately
    reach across apps to build integration fixtures, and they are not what has to
    compile after an extraction. This mirrors the frontend rule, whose ESLint
    boundary blocks likewise ignore ``__tests__``.
    """
    for path in sorted(source_dir.rglob("*.py")):
        parts = set(path.relative_to(ROOT).parts)
        if "tests" in parts or "migrations" in parts or "__pycache__" in parts:
            continue
        yield path


def app_of(dotted: str) -> str | None:
    """``apps.payments.models`` -> ``payments``; anything else -> None."""
    parts = dotted.split(".")
    if len(parts) >= 2 and parts[0] == "apps":
        return parts[1]
    return None


def find_violations() -> tuple[list[Violation], set[int]]:
    """Return every contract violation plus the indices of exemptions that matched."""
    violations: list[Violation] = []
    used_exemptions: set[int] = set()

    for contract in CONTRACTS:
        source_dir = ROOT / contract.source_dir
        for path in iter_source_files(source_dir):
            rel = path.relative_to(ROOT).as_posix()
            for dotted, lineno in Walker(path).collect():
                app = app_of(dotted)
                if app is None or app not in contract.forbidden:
                    continue
                match = next(
                    (
                        index
                        for index, exemption in enumerate(EXEMPTIONS)
                        if exemption.module == rel
                        and (
                            dotted == exemption.imports
                            or dotted.startswith(exemption.imports + ".")
                        )
                    ),
                    None,
                )
                if match is not None:
                    used_exemptions.add(match)
                    continue
                violations.append(Violation(rel, dotted, lineno, contract))

    return violations, used_exemptions


def main() -> int:
    violations, used = find_violations()
    stale = [index for index in range(len(EXEMPTIONS)) if index not in used]

    if violations:
        print("Import-contract violations:\n")
        for contract in CONTRACTS:
            hits = [v for v in violations if v.contract is contract]
            if not hits:
                continue
            print(f"  {contract.name}")
            print(f"    {contract.rationale}\n")
            for v in sorted(hits, key=lambda v: (v.module, v.line)):
                print(f"      {v.module}:{v.line}  imports  {v.imported}")
            print()
        print(
            f"{len(violations)} forbidden import(s). Invert the dependency, move the "
            "shared part\ninto apps/shared/, or — if this is a genuine, documented "
            "extraction blocker —\nadd it to EXEMPTIONS in scripts/import_contracts.py "
            "WITH the unwind plan."
        )

    if stale:
        if violations:
            print()
        print("Stale exemptions — these no longer match any import:\n")
        for index in stale:
            exemption = EXEMPTIONS[index]
            print(f"  {exemption.module}  ->  {exemption.imports}")
        print(
            "\nThe edge is gone, so the permission must go too. Delete the entry from "
            "EXEMPTIONS\nin scripts/import_contracts.py — leaving it would let the "
            "import silently return."
        )

    if violations or stale:
        return 1

    print(
        f"import contracts: {len(CONTRACTS)} contract(s) hold, "
        f"{len(EXEMPTIONS)} documented exemption(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
