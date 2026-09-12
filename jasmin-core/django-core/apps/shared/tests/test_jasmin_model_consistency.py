"""Guard: every app's copy of ``JasminModel`` must stay byte-identical.

``JasminModel`` and ``generate_jasmin_id`` are deliberately DUPLICATED per app
rather than shared from one module, so each app stays independently
extractable (no cross-app model import, and each app's historical migrations
keep resolving ``apps.<app>.….generate_jasmin_id``).

The cost of that choice is drift, and drift already happened once: four apps
were missing the PK-collision retry in ``save()``, and three were generating
IDs from a *different* alphabet that included the visually ambiguous
``I/l/1/O/0``. This test makes that class of divergence impossible to merge.

Copies are DISCOVERED by scanning ``apps/`` — a new app that adds its own
``JasminModel`` is picked up automatically and must match the others.

If this test fails: you changed one copy. Apply the identical change to every
module listed in the failure output.
"""

import inspect
import pathlib
import re
from importlib import import_module

# Ambiguity-free, URL-safe alphabet. Excludes I/l/1/O/0 (misread by humans)
# and "_" (reserved as the composite-key delimiter).
EXPECTED_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
EXPECTED_ID_LENGTH = 12

_APPS_DIR = pathlib.Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _APPS_DIR.parent


def _modules_defining_jasmin_model() -> list[str]:
    """Dotted paths of every non-test, non-migration module defining JasminModel."""
    modules = []
    for path in sorted(_APPS_DIR.rglob("*.py")):
        if {"migrations", "tests", "__pycache__"} & set(path.parts):
            continue
        if not re.search(r"^class JasminModel\(", path.read_text(), re.M):
            continue
        rel = path.relative_to(_PROJECT_ROOT).with_suffix("")
        modules.append(".".join(rel.parts))
    return modules


def _normalize(source: str) -> str:
    return "\n".join(line.rstrip() for line in source.strip().splitlines())


def test_jasmin_model_copies_are_identical():
    modules = _modules_defining_jasmin_model()
    assert len(modules) > 1, f"expected several copies, found {modules}"

    sources = {}
    for dotted in modules:
        model = import_module(dotted).JasminModel
        sources[dotted] = _normalize(inspect.getsource(model))

    reference_module, reference_source = next(iter(sources.items()))
    drifted = [m for m, src in sources.items() if src != reference_source]
    assert not drifted, (
        "JasminModel has DRIFTED between apps.\n"
        f"  reference: {reference_module}\n"
        f"  differs:   {', '.join(drifted)}\n"
        "These copies are intentional (per-app extractability) but must stay "
        "identical — apply your change to every copy."
    )


def test_generate_jasmin_id_copies_are_identical():
    sources = {}
    for dotted in _modules_defining_jasmin_model():
        func = import_module(dotted).generate_jasmin_id
        sources[dotted] = _normalize(inspect.getsource(func))

    reference_module, reference_source = next(iter(sources.items()))
    drifted = [m for m, src in sources.items() if src != reference_source]
    assert not drifted, (
        "generate_jasmin_id has DRIFTED between apps.\n"
        f"  reference: {reference_module}\n"
        f"  differs:   {', '.join(drifted)}"
    )


def test_every_app_generates_ids_from_the_same_alphabet():
    """Behavioural check — catches a diverging alphabet/length even if the
    source text were refactored into a different but equivalent shape."""
    allowed = set(EXPECTED_ALPHABET)
    for dotted in _modules_defining_jasmin_model():
        generate_id = import_module(dotted).generate_jasmin_id
        for _ in range(50):
            value = generate_id()
            assert len(value) == EXPECTED_ID_LENGTH, (
                f"{dotted}.generate_jasmin_id() returned length {len(value)}, "
                f"expected {EXPECTED_ID_LENGTH}"
            )
            illegal = set(value) - allowed
            assert not illegal, (
                f"{dotted}.generate_jasmin_id() produced disallowed character(s) "
                f"{sorted(illegal)} — it is not using the ambiguity-free alphabet."
            )


def test_id_field_definition_is_identical_everywhere():
    """The ``id`` column must deconstruct identically, or the apps would drift
    apart in migration state (and in DRF read-only behaviour)."""
    definitions = {}
    for dotted in _modules_defining_jasmin_model():
        module = import_module(dotted)
        field = module.JasminModel._meta.get_field("id")
        _name, _path, _args, kwargs = field.deconstruct()

        # ``default`` is deliberately a DIFFERENT function object per app —
        # each app owns its own ``generate_jasmin_id`` so its historical
        # migrations keep resolving. Assert that ownership, then compare the
        # rest of the definition for equality.
        assert kwargs.pop("default") is module.generate_jasmin_id, (
            f"{dotted}.JasminModel.id must default to that app's OWN "
            "generate_jasmin_id (a cross-app default re-couples the apps and "
            "would break extraction)."
        )
        definitions[dotted] = kwargs

    reference_module, reference_kwargs = next(iter(definitions.items()))
    for dotted, kwargs in definitions.items():
        assert kwargs == reference_kwargs, (
            f"id field differs between {reference_module} and {dotted}:\n"
            f"  {reference_kwargs}\n  {kwargs}"
        )
    assert reference_kwargs["editable"] is False
    assert reference_kwargs["primary_key"] is True
    assert reference_kwargs["max_length"] == EXPECTED_ID_LENGTH
