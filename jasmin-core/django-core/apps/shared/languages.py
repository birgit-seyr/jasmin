"""Single source of truth for the languages the platform ships UI + email
templates for.

Lives in ``apps/shared`` (a foundational, always-shared module) so both the
``accounts`` ``user_language`` field/serializers and the ``notifications``
template registry (``SUPPORTED_LANGUAGES`` / ``DEFAULT_LANGUAGE``) derive from
ONE list — no drift between "what a user can pick" and "what we can render".
"""

from __future__ import annotations

from django.db import models


class LanguageChoices(models.TextChoices):
    EN = "en", "English"
    DE = "de", "German"


# The fallback when a requested language has no on-disk template or DB override.
DEFAULT_LANGUAGE_CODE: str = LanguageChoices.EN.value

# Tuple of bare codes (e.g. ("en", "de")) for membership checks.
SUPPORTED_LANGUAGE_CODES: tuple[str, ...] = tuple(LanguageChoices.values)
