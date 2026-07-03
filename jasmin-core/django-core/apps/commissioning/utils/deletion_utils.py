from __future__ import annotations

from typing import Any

from django.core.exceptions import FieldError
from django.db.models import Model
from django.db.models.deletion import CASCADE, PROTECT


def can_delete_instance(
    instance: Model, exclude_models: list | None = None
) -> tuple[bool, dict[str, Any]]:
    """
    Check if a model instance can be deleted without any related objects.

    Returns False if there are ANY related objects, regardless of on_delete behavior.
    This is a fast check that doesn't hit the database for actual deletion.

    Args:
        instance: The model instance to check
        exclude_models: List of model names (strings) or model classes to exclude from the check

    Returns:
        Tuple of (can_delete: bool, info: dict with details)

    Example:
        >>> can_delete, info = can_delete_instance(my_model_instance)
        >>> if not can_delete:
        ...     print(info['message'])
    """
    exclude_model_names = _normalize_model_names(exclude_models or [])
    protected_relations = []

    for related_object in instance._meta.related_objects:
        model_name = related_object.related_model.__name__

        # Skip if this model is in the exclude list
        if model_name in exclude_model_names:
            continue

        # Reverse OneToOne: accessor returns a model instance (or raises
        # RelatedObjectDoesNotExist) instead of a manager.
        if related_object.one_to_one:
            try:
                related_obj = getattr(
                    instance, related_object.get_accessor_name(), None
                )
            except related_object.related_model.DoesNotExist:
                continue
            if related_obj is None:
                continue

            if related_object.on_delete == PROTECT:
                protected_relations.append(
                    {
                        "model": model_name,
                        "field": related_object.field.name,
                        "count": 1,
                    }
                )
            else:
                return False, {
                    "message": "Cannot delete: has related objects",
                    "related_model": model_name,
                    "count": 1,
                    "on_delete": str(related_object.on_delete),
                }
            continue

        related_manager = _get_related_manager(instance, related_object)
        if related_manager is None:
            continue

        # Use exists() instead of count() - much more efficient
        if related_manager.exists():
            count = related_manager.count()

            # If it's a PROTECT relation, we know it will block deletion
            if related_object.on_delete == PROTECT:
                protected_relations.append(
                    {
                        "model": model_name,
                        "field": related_object.field.name,
                        "count": count,
                    }
                )
            else:
                # For non-PROTECT relations, still block if we're checking for ANY relations
                return False, {
                    "message": "Cannot delete: has related objects",
                    "related_model": model_name,
                    "count": count,
                    "on_delete": str(related_object.on_delete),
                }

    # If we found protected relations, return them
    if protected_relations:
        return False, {
            "message": "Cannot delete: has protected relations",
            "protected_relations": protected_relations,
        }

    # If no related objects found, we can delete
    return True, {}


def bulk_deletable_pks(
    model: type[Model],
    pks,
    exclude_models: list | None = None,
) -> tuple[set, bool]:
    """Batched equivalent of :func:`can_delete_instance` for many pks at once.

    Returns ``(deletable_pks, failed)``:

    - ``deletable_pks`` — the subset of ``pks`` with NO related objects on any
      non-excluded reverse relation (same "any related row => not deletable"
      rule as ``can_delete_instance``, PROTECT or not).
    - ``failed`` — ``True`` if a relation can't be batched (m2m, exotic
      manager). The caller should then fall back to the per-instance
      ``can_delete_instance`` so behaviour stays identical.

    Costs R queries total (one ``filter(fk__in=pks)`` per reverse relation)
    instead of R per pk — mirrors ``DeletableListSerializer``.
    """
    exclude_model_names = _normalize_model_names(exclude_models or [])
    pks = list(pks)
    if not pks:
        return set(), False

    non_deletable: set = set()
    for related_object in model._meta.related_objects:
        if related_object.related_model.__name__ in exclude_model_names:
            continue
        # m2m can't be reduced to a single fk__in lookup — bail to per-row.
        if related_object.many_to_many:
            return set(), True

        related_model = related_object.related_model
        fk_attname = related_object.field.attname  # e.g. "linked_reseller_id"
        try:
            related_pks = related_model._base_manager.filter(
                **{f"{fk_attname}__in": pks}
            ).values_list(fk_attname, flat=True)
            non_deletable.update(related_pks)
        # Anything exotic (custom managers, abstract bases, etc.) — bail out
        # and let the caller use the per-instance path.
        except (AttributeError, TypeError, ValueError, FieldError):
            return set(), True

    return set(pks) - non_deletable, False


def _normalize_model_names(models: list) -> set[str]:
    """
    Convert a list of model references to a set of model name strings.

    Args:
        models: List of model names (strings) or model classes

    Returns:
        Set of model name strings
    """
    model_names = set()
    for model in models:
        if isinstance(model, str):
            model_names.add(model)
        else:
            model_names.add(model.__name__)
    return model_names


def _get_related_manager(instance: Model, related_object: Any) -> Any | None:
    """
    Safely get the related manager for a related object.

    Args:
        instance: The model instance
        related_object: The related object descriptor

    Returns:
        Related manager or None if not accessible
    """
    try:
        return getattr(instance, related_object.get_accessor_name())
    except AttributeError:
        return None


def parent_in_use(parent: Model) -> bool:
    """True if ``parent`` is referenced by any dependency that would NOT
    cascade-delete with it — i.e. it is genuinely in use elsewhere.

    Scans EVERY reverse relation, including HIDDEN ones declared with
    ``related_name="+"`` (e.g. ``ShareContent.share_article`` — a member-share
    line) which Django omits from ``_meta.related_objects`` and which
    ``can_delete_instance`` would therefore miss. The parent's own ``CASCADE``-
    owned children (its price rows, default-membership config) are skipped:
    they just cascade away with it and don't represent external usage.
    Everything that ``PROTECT`` / ``SET_NULL``-references it (offers, orders,
    member shares, deliveries, stock, forecasts, a variation's packing crate, …)
    counts as in use.

    Used to make a lookup price (``ShareArticleNetPrice`` / ``CrateNetPrice``)
    non-deletable once the thing it prices is actually in use, even though
    nothing FK-references the price row directly. Short-circuits on the first
    hit; callers cache per parent so a price-history list stays O(parents).
    """
    for relation in type(parent)._meta.get_fields(include_hidden=True):
        # Reverse FK / O2O only (skip forward/concrete fields and m2m).
        if not (
            relation.is_relation
            and relation.auto_created
            and relation.concrete is False
        ):
            continue
        if relation.many_to_many:
            continue
        if getattr(relation, "on_delete", None) is CASCADE:
            continue
        # Query the related model directly — hidden relations have no reverse
        # accessor, so ``getattr(parent, accessor)`` (can_delete_instance's path)
        # would not work here.
        if relation.related_model._base_manager.filter(
            **{relation.field.attname: parent.pk}
        ).exists():
            return True
    return False
