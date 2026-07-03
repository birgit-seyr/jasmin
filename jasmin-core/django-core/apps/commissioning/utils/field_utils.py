from __future__ import annotations

from typing import Any

from django.db.models import F, QuerySet


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


def extract_selected_storage_id(data: dict[str, Any]) -> str | None:
    """
    Extract the storage ID that is set to True from the data.

    Looks for keys in format 'storage_<id>' with value True.

    Args:
        data: Dictionary containing storage fields like 'storage_123': True

    Returns:
        Storage ID as string, or None if no storage is selected

    Example:
        >>> data = {'storage_abc123': True, 'storage_xyz789': False}
        >>> extract_selected_storage_id(data)
        'abc123'
    """
    storage_prefix = "storage_"
    prefix_len = len(storage_prefix)

    for key, value in data.items():
        if key.startswith(storage_prefix) and len(key) > prefix_len and value is True:
            return key[prefix_len:]  # Remove "storage_" prefix

    return None


def clean_storage_fields(data: dict[str, Any]) -> None:
    """
    Remove all storage_* fields from the data in-place.

    Modifies the dictionary to remove all keys starting with 'storage_'.

    Args:
        data: Dictionary to clean (modified in-place)

    Example:
        >>> data = {'name': 'Test', 'storage_123': True, 'storage_456': False}
        >>> clean_storage_fields(data)
        >>> print(data)
        {'name': 'Test'}
    """
    keys_to_remove = [key for key in data.keys() if key.startswith("storage_")]
    for key in keys_to_remove:
        del data[key]


def build_storage_fields(
    entry: Any | None = None, active_storages: Any | None = None
) -> dict[str, bool]:
    """
    Build storage fields dictionary for serializer/response.

    Creates a dictionary with one boolean field per active storage.
    If an entry is provided and has a storage, that storage's field is set to True.

    Args:
        entry: Optional model instance with storage_id attribute
        active_storages: Optional pre-fetched active Storage list. Pass this
            when building fields for many rows so the active-storage query runs
            once for the batch instead of once per call (the per-row N+1).

    Returns:
        Dictionary with 'storage_<id>': bool pairs for all active storages

    Example:
        >>> fields = build_storage_fields(harvest_entry)
        >>> # Returns: {'storage_1': True, 'storage_2': False, 'storage_3': False}
    """

    if active_storages is None:
        active_storages = _get_active_storages()
    storage_fields = {}

    entry_storage_id = (
        entry.storage_id if entry and hasattr(entry, "storage_id") else None
    )

    for storage in active_storages:
        storage_key = f"storage_{storage.id}"
        storage_fields[storage_key] = entry_storage_id == storage.id

    return storage_fields


def extract_storage_fields_from_data(
    data: dict[str, Any], active_storages: Any | None = None
) -> dict[str, Any]:
    """
    Extract only storage fields from incoming request data.

    Filters the data to only include storage_* fields that correspond to active storages.
    Useful for serializer validation.

    Args:
        data: Dictionary containing request data
        active_storages: Optional pre-fetched active Storage list (see
            ``build_storage_fields``).

    Returns:
        Dictionary with only storage_* fields that exist in data

    Example:
        >>> request_data = {'name': 'Test', 'storage_1': True, 'storage_2': False}
        >>> extract_storage_fields_from_data(request_data)
        {'storage_1': True, 'storage_2': False}
    """
    if active_storages is None:
        active_storages = _get_active_storages()
    storage_fields = {}

    for storage in active_storages:
        field_name = f"storage_{storage.id}"
        if field_name in data:
            storage_fields[field_name] = data[field_name]

    return storage_fields


def _get_active_storages() -> QuerySet:
    """
    Get all active storages.

    Extracted to reduce duplication and make testing easier.

    Returns:
        QuerySet of active Storage objects
    """
    from ..models.basics import Storage

    return Storage.objects.filter(is_active=True)
