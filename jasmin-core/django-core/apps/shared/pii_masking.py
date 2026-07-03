"""Display-masking helpers for sensitive PII (IBAN, account-holder name).

Used by office/admin serializers that must show *enough* of a value for a
human to recognize it (the last 4 of an IBAN) without echoing the full
decrypted secret on every bulk read. Column encryption-at-rest protects the
database; these helpers stop the API boundary from undoing that for casual
reads. Full values are accepted only on WRITE (``write_only`` fields) or
revealed through a dedicated, step-up-gated surface.

These are standalone, domain-free utilities — safe to import from any app
(including ``apps/commissioning``).
"""

from __future__ import annotations

# • — never appears in a real IBAN or a name, so the masked output is also
# unambiguously NOT a value anyone should try to write back.
_BULLET = "•"


def mask_iban(value: str | None) -> str:
    """Return a recognizable-but-masked IBAN: country code + last 4.

    ``"DE89370400440532013000"`` -> ``"DE •••• 3000"``. Empty / ``None``
    yields ``""`` (the absence is itself the signal). Whitespace in the
    stored value is ignored.
    """
    if not value:
        return ""
    compact = value.replace(" ", "")
    if len(compact) <= 4:
        return _BULLET * len(compact)
    return f"{compact[:2]} {_BULLET * 4} {compact[-4:]}"


def mask_account_holder(value: str | None) -> str:
    """Mask a person/company name, keeping the first letter of each token.

    ``"Ada Lovelace"`` -> ``"A•• L•••••••"``. Empty / ``None`` yields ``""``.
    """
    if not value:
        return ""
    masked_tokens = []
    for token in value.split():
        masked_tokens.append(
            token if len(token) <= 1 else token[0] + _BULLET * (len(token) - 1)
        )
    return " ".join(masked_tokens)


# Shared getters for a serializer's masked SEPA display fields.
#
# The consuming serializer keeps declaring its own output fields (the exposed
# names differ per model — ``account_owner_masked`` on Member vs
# ``account_holder_masked`` on BillingProfile — and the declaration site also
# fixes each field's position in the payload); this mixin supplies only the
# method implementations so the masking contract cannot drift between apps::
#
#     class FooSerializer(MaskedIBANFieldMixin, serializers.ModelSerializer):
#         MASKED_ACCOUNT_HOLDER_SOURCE = "account_owner"
#
#         iban_masked = serializers.SerializerMethodField()
#         account_owner_masked = serializers.SerializerMethodField(
#             method_name="get_account_holder_masked"
#         )
#
# ``MASKED_IBAN_SOURCE`` / ``MASKED_ACCOUNT_HOLDER_SOURCE`` name the model
# attributes holding the decrypted values. No DRF import needed here — the
# mixin is plain methods plus class attrs, so this module stays
# framework-light.
#
# Deliberately NOT a docstring: drf-spectacular resolves a serializer's schema
# description by walking the MRO for the first non-DRF class docstring, so a
# docstring here would leak into the description of any consuming serializer
# that lacks its own (e.g. BillingProfileSerializer).
class MaskedIBANFieldMixin:
    MASKED_IBAN_SOURCE: str = "iban"
    MASKED_ACCOUNT_HOLDER_SOURCE: str = "account_holder"

    def get_iban_masked(self, obj) -> str:
        return mask_iban(getattr(obj, self.MASKED_IBAN_SOURCE))

    def get_account_holder_masked(self, obj) -> str:
        return mask_account_holder(getattr(obj, self.MASKED_ACCOUNT_HOLDER_SOURCE))
