"""Guard the ``FIELD_ENCRYPTION_KEY`` rotation contract.

``django-encrypted-model-fields`` builds a ``MultiFernet`` from
``settings.FIELD_ENCRYPTION_KEY``: the FIRST key encrypts new writes, and
ALL keys are tried when decrypting. That fallback is what makes key
rotation possible — old ciphertext stays readable while the re-encryption
pass runs.

The library calls ``Fernet()`` on each list element and never splits on
commas itself. That makes the split in ``config/settings.py`` load-bearing:
a comma-joined string passed as ONE list element is never equivalent to the
keys it holds. HOW it breaks depends on the interpreter, because CPython
changed non-strict base64 decoding within the 3.14 series:

- Older decoders (3.14.3 and before) stop at the ``=`` padding that
  terminates the first key, so the joined string decodes to exactly the
  first key — no exception, no warning — and the old key is discarded.
- Newer decoders (3.14.6, which the backend image and CI run) no longer
  treat padding as a terminator, so the joined string is rejected with
  ``binascii.Error: Incorrect padding`` and ``Fernet()`` re-raises it as
  ``ValueError``.

Either way the old key is gone: values written before the rotation fail to
decrypt, and the ``rotate_field_encryption`` command cannot read the rows
it exists to re-encrypt. The tests below assert that invariant rather than
one interpreter's failure mode, and pin the behaviour end-to-end rather
than asserting on the settings literal, so they keep holding if the
parsing moves elsewhere.
"""

import base64
import binascii

import pytest
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

SECRET = b"DE89370400440532013000"


def _build_crypter(configured_keys):
    """Mirror ``encrypted_model_fields.fields.get_crypter``."""
    return MultiFernet([Fernet(key) for key in configured_keys])


def _decrypt_or_none(configured_keys, token):
    """Decrypt ``token``, collapsing both unsplit-key failure modes to None.

    A key list that cannot read the token either blows up while building
    the crypter (``ValueError`` from ``Fernet`` on a rejected key) or
    builds fine and fails at read time (``InvalidToken`` from a key that
    silently truncated).
    """
    try:
        return _build_crypter(configured_keys).decrypt(token)
    except (ValueError, InvalidToken):
        return None


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


def test_comma_joined_key_never_carries_both_keys():
    """Document the trap, whichever way this interpreter expresses it."""
    new, old = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    joined = f"{new},{old}"

    try:
        decoded = base64.urlsafe_b64decode(joined)
    except binascii.Error:
        # Loud mode: padding is no longer a terminator, so the whole value
        # is rejected and Fernet turns that into a startup ValueError.
        with pytest.raises(ValueError):
            Fernet(joined)
    else:
        # Silent mode: the decode stopped at the "=" ending the first key.
        assert decoded == base64.urlsafe_b64decode(new)
        assert decoded != base64.urlsafe_b64decode(old)


def test_unsplit_key_cannot_decrypt_ciphertext_written_with_the_old_key():
    """The regression itself: rotation breaks existing rows."""
    new, old = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    token = Fernet(old).encrypt(SECRET)

    # What a MISSING split produces: one element holding "new,old".
    assert _decrypt_or_none([f"{new},{old}"], token) is None

    # What the split produces: two keys, old one still readable.
    assert _decrypt_or_none(f"{new},{old}".split(","), token) == SECRET


def test_rotation_reencrypts_under_the_first_key():
    """After re-writing a value, the old key is no longer needed."""
    new, old = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    token_old = Fernet(old).encrypt(SECRET)

    during_rotation = _build_crypter([new, old])
    token_new = during_rotation.encrypt(during_rotation.decrypt(token_old))

    # Dropping the old key (rotation step 4) must keep the rewritten row.
    assert _build_crypter([new]).decrypt(token_new) == SECRET
