"""Guard the ``FIELD_ENCRYPTION_KEY`` rotation contract.

``django-encrypted-model-fields`` builds a ``MultiFernet`` from
``settings.FIELD_ENCRYPTION_KEY``: the FIRST key encrypts new writes, and
ALL keys are tried when decrypting. That fallback is what makes key
rotation possible — old ciphertext stays readable while the re-encryption
pass runs.

The library calls ``Fernet()`` on each list element and never splits on
commas itself. That makes the split in ``config/settings.py`` load-bearing
in a way that fails SILENTLY if it is ever removed:

``Fernet`` base64-decodes its key, and ``base64.urlsafe_b64decode`` stops
at the ``=`` padding that terminates the first key. So a comma-joined
string passed as ONE list element decodes to exactly the first key — no
exception, no warning — and the old key is discarded. Every value written
before the rotation then fails to decrypt with ``InvalidToken``, and the
``rotate_field_encryption`` command cannot read the rows it exists to
re-encrypt.

These tests pin the behaviour end-to-end rather than asserting on the
settings literal, so they keep holding if the parsing moves elsewhere.
"""

import base64

import pytest
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

SECRET = b"DE89370400440532013000"


def _build_crypter(configured_keys):
    """Mirror ``encrypted_model_fields.fields.get_crypter``."""
    return MultiFernet([Fernet(key) for key in configured_keys])


def test_settings_key_is_a_list_of_individually_valid_fernet_keys():
    """Every entry must stand alone as a Fernet key."""
    configured = settings.FIELD_ENCRYPTION_KEY

    assert isinstance(configured, (list, tuple)), (
        "FIELD_ENCRYPTION_KEY must be a list — the library only tries "
        "multiple keys when it is one."
    )
    assert configured, "FIELD_ENCRYPTION_KEY must not be empty."
    for key in configured:
        assert "," not in key, (
            f"FIELD_ENCRYPTION_KEY entry {key[:8]}... still contains a comma: "
            "the env value was not split, so only the first key is live."
        )
        Fernet(key)  # raises if the entry is not a valid standalone key


def test_comma_joined_key_silently_collapses_to_the_first_key():
    """Document the trap: no exception, the old key just vanishes.

    If this ever starts raising instead, the failure mode became loud and
    the settings comment should be updated to match.
    """
    new, old = Fernet.generate_key().decode(), Fernet.generate_key().decode()

    collapsed = base64.urlsafe_b64decode(f"{new},{old}")

    assert collapsed == base64.urlsafe_b64decode(new)
    assert collapsed != base64.urlsafe_b64decode(old)


def test_unsplit_key_cannot_decrypt_ciphertext_written_with_the_old_key():
    """The regression itself: rotation silently breaks existing rows."""
    new, old = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    token = Fernet(old).encrypt(SECRET)

    # What a MISSING split produces: one element holding "new,old".
    unsplit = _build_crypter([f"{new},{old}"])
    with pytest.raises(InvalidToken):
        unsplit.decrypt(token)

    # What the split produces: two keys, old one still readable.
    assert _build_crypter(f"{new},{old}".split(",")).decrypt(token) == SECRET


def test_rotation_reencrypts_under_the_first_key():
    """After re-writing a value, the old key is no longer needed."""
    new, old = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    token_old = Fernet(old).encrypt(SECRET)

    during_rotation = _build_crypter([new, old])
    token_new = during_rotation.encrypt(during_rotation.decrypt(token_old))

    # Dropping the old key (rotation step 4) must keep the rewritten row.
    assert _build_crypter([new]).decrypt(token_new) == SECRET
