"""Tests for the email template registry — the single source of truth
that lists every tenant-editable email slug shipped by Jasmin.

If a slug disappears or its on-disk default template stops existing,
tenants who customised it would suddenly see broken emails. These tests
lock that invariant down: every registered slug must have its file on
disk, in every supported language."""

from __future__ import annotations

import pytest
from django.template import TemplateDoesNotExist
from django.template.loader import get_template, select_template

from apps.notifications.registry import (
    DEFAULT_LANGUAGE,
    REGISTRY,
    SUPPORTED_LANGUAGES,
    all_specs,
    get_spec,
    normalize_language,
    template_path,
)
from apps.notifications.template_renderer import (
    RAW_KEYS,
    extract_placeholders,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("de", "de"),
        ("DE", "de"),
        ("de-DE", "de"),
        ("de_DE", "de"),
        ("deu", "de"),
        ("german", "de"),
        ("deutsch", "de"),
        ("en", "en"),
        ("en-US", "en"),
        ("english", "en"),
        ("  De  ", "de"),
        ("fr", "fr"),
        ("fr-FR", "fr"),
        ("it", "it"),
        ("it-IT", "it"),
        # Unsupported / junk → None, so callers fall through to the default.
        ("ja", None),
        ("", None),
        (None, None),
        ("xx", None),
    ],
)
def test_normalize_language(raw, expected):
    assert normalize_language(raw) == expected


def test_registry_is_not_empty():
    assert len(REGISTRY) > 0


def test_get_spec_returns_known_entry():
    spec = get_spec("accounts.invitation")
    assert spec.slug == "accounts.invitation"


def test_get_spec_unknown_raises():
    with pytest.raises(KeyError):
        get_spec("does.not.exist")


def test_default_language_is_in_supported():
    assert DEFAULT_LANGUAGE in SUPPORTED_LANGUAGES


@pytest.mark.parametrize("spec", all_specs(), ids=lambda s: s.slug)
def test_default_html_template_exists_in_default_language(spec):
    """Every shipped slug MUST have an HTML template in DEFAULT_LANGUAGE."""
    path = template_path(spec.default_template, DEFAULT_LANGUAGE, "html")
    # ``select_template`` raises TemplateDoesNotExist on miss.
    select_template([path])


@pytest.mark.parametrize("spec", all_specs(), ids=lambda s: s.slug)
def test_default_subject_is_non_empty(spec):
    assert (
        spec.default_subject.strip()
    ), f"Slug {spec.slug!r} has an empty default_subject"


@pytest.mark.parametrize("spec", all_specs(), ids=lambda s: s.slug)
def test_english_bodied_template_defines_english_subject(spec):
    """Every slug that ships an English body MUST also define
    ``default_subject_en`` — otherwise an English send pairs the English
    body with the German ``default_subject``."""
    try:
        select_template([template_path(spec.default_template, "en", "html")])
    except TemplateDoesNotExist:
        # No English body shipped: the send falls back to the
        # DEFAULT_LANGUAGE body, which pairs with ``default_subject``.
        return
    assert spec.default_subject_en and spec.default_subject_en.strip(), (
        f"Slug {spec.slug!r} ships an English body template but defines no "
        "default_subject_en — an English send would carry the German subject."
    )


@pytest.mark.parametrize("spec", all_specs(), ids=lambda s: s.slug)
def test_each_variable_has_label(spec):
    for var in spec.variables:
        assert var.name, f"Slug {spec.slug!r}: variable missing name"
        assert var.label, f"Slug {spec.slug!r}/{var.name}: missing label"


def test_all_slugs_are_namespaced():
    """Slugs must be ``app.thing`` so the admin UI can group them."""
    for slug in REGISTRY:
        assert "." in slug, f"Slug {slug!r} is not namespaced"


def _declared_allows(path: str, declared_names: set[str]) -> bool:
    """Mirror the EML-10 write-time validator's accept rule: a placeholder is
    declared when its exact path is declared, a declared dotted name shares its
    root (the object is opted-in), or it is a trusted raw key."""
    if path in declared_names or path in RAW_KEYS:
        return True
    root = path.split(".", 1)[0]
    object_roots = {name.split(".", 1)[0] for name in declared_names if "." in name}
    return "." in path and root in object_roots


@pytest.mark.parametrize("spec", all_specs(), ids=lambda s: s.slug)
def test_default_template_placeholders_are_declared(spec):
    """EML-10 completeness invariant: every ``{{ placeholder }}`` used by a
    shipped default template (HTML + text, every supported language) MUST be a
    declared spec variable (or a trusted raw key).

    Without this, a tenant who copies the shipped default into an override and
    saves it would be rejected by the strict write-time validator — a worse
    regression than the silent-empty render the validator fixes. This test is
    the durable guard that keeps the registry and the on-disk templates in
    sync, so a future template edit that introduces a new placeholder fails CI
    until the spec declares it."""
    declared_names = {variable.name for variable in spec.variables}
    for language in SUPPORTED_LANGUAGES:
        for ext in ("html", "txt"):
            path = template_path(spec.default_template, language, ext)
            source = get_template(path).template.source
            for placeholder in extract_placeholders(source):
                assert _declared_allows(placeholder, declared_names), (
                    f"{spec.slug} ({path}): placeholder {{{{ {placeholder} }}}} "
                    "is not declared in the registry spec — declare it as an "
                    "EmailVariable or it will be rejected when a tenant edits "
                    "this template."
                )
