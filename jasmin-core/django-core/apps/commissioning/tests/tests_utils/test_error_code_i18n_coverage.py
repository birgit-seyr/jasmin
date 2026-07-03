"""Drift guard: every backend error ``code`` must have a frontend i18n entry.

`JasminError` subclasses carry a stable `code` field (e.g.
`"commissioning.share_days_locked"`) that the frontend looks up in
`react-core/src/shared/i18n/locales/<lang>/errors.json` to render an authored,
localized message. When someone adds a new error class without adding the
matching i18n entry, the user gets the raw backend message (English) until
someone notices. This test fails the build instead, so it gets noticed.

Run: ``poetry run pytest apps/commissioning/tests/tests_utils/test_error_code_i18n_coverage.py``
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

# Anchor on django-core itself (this file is
# apps/commissioning/tests/tests_utils/<file>, i.e. parents[4]) and derive the
# sibling react-core. Anchoring on a fixed directory instead of counting up to
# the repo root keeps these paths correct if the tree is relocated.
DJANGO_CORE = Path(__file__).resolve().parents[4]
REACT_CORE = DJANGO_CORE.parent / "react-core"
ERRORS_FILES = [
    DJANGO_CORE / "core" / "errors.py",
    *sorted((DJANGO_CORE / "apps").glob("*/errors.py")),
]
I18N_LOCALES_DIR = REACT_CORE / "src" / "shared" / "i18n" / "locales"
REQUIRED_LANGS = ("de", "en")

# Apps excluded from the app codebase by standing instruction — their code is
# not held to the current conventions and their error codes aren't backfilled.
IGNORED_APPS = frozenset({"cultivation", "economics", "staff"})

# Helper functions that FORWARD a ``code=`` kwarg into a JasminError (so an
# inline ``code=`` on a call to one of these reaches the wire as the envelope
# code, exactly like constructing the error directly). Kept as a small explicit
# allowlist because they can't be discovered from errors.py.
_CODE_FORWARDING_HELPERS = frozenset({"assert_not_finalized", "parse_composite_pk"})

# Codes that intentionally pass through to DRF/Django's server-side
# translations and shouldn't be translated again on the frontend.
SERVER_TRANSLATED_CODES = frozenset(
    {
        "validation_error",
        "not_authenticated",
    }
)


def _collect_backend_codes() -> set[str]:
    """Parse every errors.py and return the union of `code = "..."` literals."""
    codes: set[str] = set()
    for path in ERRORS_FILES:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                # Match either bare `code = "..."` or annotated `code: str = "..."`
                if isinstance(stmt, ast.Assign):
                    targets = stmt.targets
                elif isinstance(stmt, ast.AnnAssign):
                    targets = [stmt.target]
                else:
                    continue
                for tgt in targets:
                    if (
                        isinstance(tgt, ast.Name)
                        and tgt.id == "code"
                        and isinstance(stmt.value, ast.Constant)
                        and isinstance(stmt.value.value, str)
                    ):
                        codes.add(stmt.value.value)
    return codes


def _jasmin_error_callees() -> set[str]:
    """Names whose call carries a wire-reaching ``code=``: every class defined
    in an errors.py (all ``JasminError`` subclasses by the per-app convention)
    plus the code-forwarding helpers. A Django/DRF ``ValidationError`` is NOT in
    this set — its ``code=`` is flattened to ``validation_error`` by the DRF
    exception handler and never reaches the client as the envelope code, so
    scanning by callee (not just "any ``code=``") avoids demanding i18n for
    field-validation codes that the frontend can't key on."""
    names = set(_CODE_FORWARDING_HELPERS)
    for path in ERRORS_FILES:
        if not path.exists():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
    return names


def _app_modules() -> list[Path]:
    """Every non-test, non-migration app module, excluding the ignored apps."""
    modules: list[Path] = []
    for py in sorted((DJANGO_CORE / "apps").rglob("*.py")):
        parts = py.relative_to(DJANGO_CORE / "apps").parts
        if parts[0] in IGNORED_APPS or "tests" in parts or "migrations" in parts:
            continue
        modules.append(py)
    return modules


def _call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _collect_inline_codes() -> set[str]:
    """Codes raised INLINE as ``SomeJasminError(..., code="x")`` (or via a
    code-forwarding helper) rather than declared as an errors.py class attribute.

    ``JasminError.__init__`` takes a per-instance ``code=``, so a viewset/service
    can mint a wire-reaching code without a dedicated error class — invisible to
    :func:`_collect_backend_codes`. Scanning by callee keeps this to codes that
    actually surface as the envelope ``code`` (see :func:`_jasmin_error_callees`)."""
    callees = _jasmin_error_callees()
    codes: set[str] = set()
    for path in _app_modules():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node) not in callees:
                continue
            for kw in node.keywords:
                if (
                    kw.arg == "code"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    codes.add(kw.value.value)
    return codes


def _flatten(obj: dict, prefix: str = "") -> set[str]:
    """`{a: {b: "..."}}` -> `{"a.b"}`."""
    keys: set[str] = set()
    for k, v in obj.items():
        path = f"{prefix}{k}"
        if isinstance(v, dict):
            keys |= _flatten(v, prefix=f"{path}.")
        else:
            keys.add(path)
    return keys


def _load_i18n_codes(lang: str) -> set[str]:
    path = I18N_LOCALES_DIR / lang / "errors.json"
    if not path.exists():
        return set()
    return _flatten(json.loads(path.read_text()))


@pytest.mark.parametrize("lang", REQUIRED_LANGS)
def test_every_backend_error_code_has_i18n_entry(lang: str) -> None:
    backend_codes = (
        _collect_backend_codes() | _collect_inline_codes()
    ) - SERVER_TRANSLATED_CODES
    # Non-vacuity guard: if the source paths break again, both sets go empty
    # and the coverage assertion below passes trivially. Fail loudly instead.
    assert backend_codes, (
        "No backend error codes collected — ERRORS_FILES is mis-pathed "
        f"({[str(p) for p in ERRORS_FILES]}). This guard must not pass on "
        "an empty set."
    )
    # The inline scan must find something too, or a broken _app_modules() path
    # would silently drop the whole inline dimension of this guard.
    assert _collect_inline_codes(), (
        "No inline error codes collected — _app_modules() is mis-pathed. "
        "This guard must not pass on an empty inline set."
    )
    i18n_codes = _load_i18n_codes(lang)
    assert i18n_codes, (
        f"No i18n codes loaded for {lang!r} — I18N_LOCALES_DIR is mis-pathed "
        f"({I18N_LOCALES_DIR}). This guard must not pass on an empty set."
    )
    missing = sorted(backend_codes - i18n_codes)
    assert not missing, (
        f"{len(missing)} backend error code(s) without an entry in "
        f"src/i18n/locales/{lang}/errors.json:\n"
        + "\n".join(f"  - {c}" for c in missing)
        + "\nAdd them so users see authored, localized error text instead of "
        "the raw backend message."
    )


def test_de_and_en_have_same_keys() -> None:
    """Drift guard the other direction: catch entries that exist in only one
    language so future translation work doesn't silently fall back."""
    de = _load_i18n_codes("de")
    en = _load_i18n_codes("en")
    # Non-vacuity guard: empty sets (mis-pathed locales) would make the
    # parity assertion below pass trivially.
    assert de and en, (
        "errors.json failed to load for de/en — I18N_LOCALES_DIR is mis-pathed "
        f"({I18N_LOCALES_DIR}). This parity guard must not pass on empty sets."
    )
    only_de = sorted(de - en)
    only_en = sorted(en - de)
    assert not only_de and not only_en, (
        f"errors.json key drift between de and en.\n"
        f"  only in de ({len(only_de)}): {only_de}\n"
        f"  only in en ({len(only_en)}): {only_en}"
    )
