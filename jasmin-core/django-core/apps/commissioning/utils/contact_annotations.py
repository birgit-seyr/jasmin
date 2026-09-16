from __future__ import annotations

from django.db.models import F


def get_contact_annotations() -> dict[str, F]:
    """Return ``{field_name: F("contact__field_name")}`` for every scalar field
    on ``ContactEntity``.

    Used by viewsets that flatten a contact onto a parent row (DeliveryStation,
    Reseller, …) so a serializer can read ``record["phone"]`` etc. without
    every viewset spelling out the contact field list.
    """
    # Local import: ContactEntity lives in commissioning.models, and a
    # module-level import would create a circular through utils/__init__.
    from ..models import ContactEntity

    excluded_fields = {"id", "created_at", "updated_at"}
    return {
        field.name: F(f"contact__{field.name}")
        for field in ContactEntity._meta.get_fields()
        if not field.many_to_many
        and not field.one_to_many
        and not field.one_to_one
        and field.name not in excluded_fields
    }
