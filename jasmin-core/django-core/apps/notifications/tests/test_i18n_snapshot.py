"""i18n snapshot test for one representative slug.

Locks the rendered HTML body of ``accounts.invitation`` in both ``de``
and ``en`` so an accidental edit to a shipped template — or to the
template-loader code path — fails CI immediately. The check is intentionally
loose (substring asserts on the merged sample variables) so cosmetic
whitespace / tag-attribute changes don't break it.

If you intentionally change the wording, update the substrings below.
"""

from __future__ import annotations

import pytest
from django.template.loader import render_to_string

from apps.notifications.registry import get_spec, template_path

SLUG = "accounts.invitation"


def _render(language: str) -> str:
    spec = get_spec(SLUG)
    path = template_path(spec.default_template, language, "html")
    return render_to_string(path, spec.sample)


@pytest.mark.parametrize(
    "language, expected_phrase",
    [
        ("de", "eingeladen"),  # "Du wurdest zu ... eingeladen"
        ("en", "invited"),
    ],
)
def test_invitation_html_contains_localised_phrase(language, expected_phrase):
    body = _render(language).lower()
    assert expected_phrase in body, (
        f"Expected localised phrase {expected_phrase!r} in {language} render of "
        f"{SLUG}; got first 200 chars: {body[:200]!r}"
    )


@pytest.mark.parametrize("language", ["de", "en"])
def test_invitation_html_substitutes_sample_variables(language):
    """The shipped sample context MUST drive every {{ var }} placeholder
    so the preview endpoint shows realistic output."""
    body = _render(language)
    sample = get_spec(SLUG).sample
    # tenant_name and accept_url are non-trivial top-level keys in the
    # sample; if either fails to substitute the renderer is broken.
    assert sample["tenant_name"] in body
    assert sample["accept_url"] in body


@pytest.mark.parametrize("language", ["de", "en"])
def test_invitation_html_does_not_leak_template_syntax(language):
    """No ``{{`` or ``{%`` should survive a successful render — that
    would mean a placeholder/tag failed to resolve."""
    body = _render(language)
    assert "{{" not in body, f"Unrendered '{{{{' in {language}: {body[:200]!r}"
    assert "{%" not in body, f"Unrendered '{{%' in {language}: {body[:200]!r}"
