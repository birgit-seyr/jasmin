"""EML-5: ``user_language`` is constrained to the supported language set at
every write ingress — the serializer ``ChoiceField`` (backed by the single
``apps.shared.languages.LanguageChoices`` source) rejects unsupported codes so
an unvalidated value can never be persisted."""

from __future__ import annotations

import pytest

from apps.accounts.serializers import (
    AdminUserCreateRequestSerializer,
    AdminUserUpdateRequestSerializer,
    PublicRegisterRequestSerializer,
    UserProfileUpdateRequestSerializer,
)

# Every serializer that ACCEPTS user_language as input.
WRITE_SERIALIZERS = [
    UserProfileUpdateRequestSerializer,
    PublicRegisterRequestSerializer,
    AdminUserCreateRequestSerializer,
    AdminUserUpdateRequestSerializer,
]


@pytest.mark.parametrize("serializer_cls", WRITE_SERIALIZERS)
@pytest.mark.parametrize("code", ["en", "de", "fr", "it"])
def test_supported_language_is_not_a_user_language_error(serializer_cls, code):
    # Other required fields may still error; user_language must NOT.
    serializer = serializer_cls(data={"user_language": code})
    serializer.is_valid()
    assert "user_language" not in serializer.errors


@pytest.mark.parametrize("serializer_cls", WRITE_SERIALIZERS)
@pytest.mark.parametrize("code", ["deu", "de-DE", "english", "xx", "EN"])
def test_unsupported_language_is_rejected(serializer_cls, code):
    serializer = serializer_cls(data={"user_language": code})
    serializer.is_valid()
    assert "user_language" in serializer.errors
