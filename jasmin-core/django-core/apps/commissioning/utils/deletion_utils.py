from __future__ import annotations

from typing import Any

from django.core.exceptions import FieldError
from django.db.models import Exists, ForeignObjectRel, Model, OuterRef
from django.db.models.deletion import CASCADE, PROTECT


def can_delete_instance(
    instance: Model,
    exclude_models: list | None = None,
    *,
    include_hidden: bool = False,
) -> tuple[bool, dict[str, Any]]:
    """
    Check if a model instance can be deleted without any related objects.

    Returns False if there are ANY related objects, regardless of on_delete
    behavior, on any reverse relation. ``include_hidden`` also counts the
    relations declared with ``related_name="+"`` (see
    :func:`_reverse_relations`): a delete itself checks them, while the
    ``can_be_deleted`` flag a list shows leaves them out, as the many lines
    behind them (every share content of a station or an article) would cost
    each list a scan.

    Args:
        instance: The model instance to check
        exclude_models: Model names (strings) or model classes to exclude from
            the check, or ``"Model.field"`` for one key of a model with several
        include_hidden: Count the hidden relations too

    Returns:
        Tuple of (can_delete: bool, info: dict with details)

    Example:
        >>> can_delete, info = can_delete_instance(my_model_instance)
        >>> if not can_delete:
        ...     print(info['message'])
    """
    exclude_model_names = _normalize_model_names(exclude_models or [])
    protected_relations = []

    for relation in _reverse_relations(
        type(instance), exclude_model_names, include_hidden=include_hidden
    ):
        model_name = relation.related_model.__name__
        if not (
            relation.related_model._base_manager.filter(
                **{relation.field.attname: instance.pk}
            ).exists()
        ):
            continue

        # A PROTECT relation blocks the delete itself; collect them all.
        if relation.on_delete == PROTECT:
            protected_relations.append(
                {"model": model_name, "field": relation.field.name}
            )
        else:
            return False, {
                "message": "Cannot delete: has related objects",
                "related_model": model_name,
                "on_delete": str(relation.on_delete),
            }

    if protected_relations:
        return False, {
            "message": "Cannot delete: has protected relations",
            "protected_relations": protected_relations,
        }

    return True, {}


def bulk_deletable_pks(
    model: type[Model],
    pks,
    exclude_models: list | None = None,
) -> tuple[set, bool]:
    """Batched equivalent of :func:`can_delete_instance` (without the hidden
    relations) for many pks at once.

    Returns ``(deletable_pks, failed)``:

    - ``deletable_pks`` — the subset of ``pks`` with NO related objects on any
      non-excluded reverse relation (same "any related row => not deletable"
      rule as ``can_delete_instance``, PROTECT or not).
    - ``failed`` — ``True`` if a relation can't be batched (exotic manager).
      The caller should then fall back to the per-instance
      ``can_delete_instance`` so behaviour stays identical.

    Costs R queries total (one per reverse relation) instead of R per pk —
    mirrors ``DeletableListSerializer``. Each asks per pk whether a related row
    exists, so it reads at most one index entry per pk however many lines
    point at it.
    """
    exclude_model_names = _normalize_model_names(exclude_models or [])
    pks = list(pks)
    if not pks:
        return set(), False

    candidates = model._base_manager.filter(pk__in=pks)
    non_deletable: set = set()
    for relation in _reverse_relations(
        model, exclude_model_names, include_hidden=False
    ):
        try:
            referenced = relation.related_model._base_manager.filter(
                **{relation.field.attname: OuterRef("pk")}
            )
            non_deletable.update(
                candidates.filter(Exists(referenced)).values_list("pk", flat=True)
            )
        # Anything exotic (custom managers, abstract bases, etc.) — bail out
        # and let the caller use the per-instance path.
        except (AttributeError, TypeError, ValueError, FieldError):
            return set(), True

    return set(pks) - non_deletable, False


def _reverse_relations(
    model: type[Model], exclude_model_names: set[str], *, include_hidden: bool
) -> list[ForeignObjectRel]:
    """Every reverse FK / O2O pointing at ``model``; with ``include_hidden``
    also those declared with ``related_name="+"`` (``ShareContent.share_article``,
    a coop share's member, …), which ``_meta.related_objects`` leaves out. A
    hidden relation has no reverse accessor, so callers query the related model
    directly.

    A many-to-many is skipped: the foreign key of its through table is a
    reverse FK of its own, so the link is counted there, once. Django hides
    the keys of a through table it creates; such a key counts as hidden when
    its many-to-many is. An excluded model name also excludes the through table
    Django creates for a many-to-many that model declares; an explicit through
    model (``VirtualVariationComponent``) goes by its own name.

    A model's name leaves out all its keys to ``model``; ``"Model.field"``
    leaves out that one key. ``VirtualVariationComponent`` has two to a share
    size: ``virtual_variation``, a virtual size's own components, which go with
    it, and ``physical_variation``, a size being part of one.
    """
    relations = []
    for relation in model._meta.get_fields(include_hidden=True):
        if not (isinstance(relation, ForeignObjectRel) and not relation.many_to_many):
            continue
        related_model = relation.related_model
        names = {
            related_model.__name__,
            f"{related_model.__name__}.{relation.field.name}",
        }
        # An auto-created through table names the model that declares it.
        declaring_model = related_model._meta.auto_created
        hidden = relation.hidden
        if isinstance(declaring_model, type):
            names.add(declaring_model.__name__)
            hidden = any(
                field.remote_field.hidden
                for field in declaring_model._meta.many_to_many
                if field.remote_field.through is related_model
            )
        if names & exclude_model_names or (hidden and not include_hidden):
            continue
        relations.append(relation)
    return relations


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


def parent_in_use(parent: Model) -> bool:
    """True if ``parent`` is referenced by any dependency that would NOT
    cascade-delete with it — i.e. it is genuinely in use elsewhere.

    Walks every reverse relation, hidden ones included (e.g.
    ``ShareContent.share_article`` — a member-share line), but skips the
    parent's own ``CASCADE``-owned children (its price rows, default-membership
    config, the through rows of its many-to-manys): they just cascade away
    with it and don't represent external usage. Everything that ``PROTECT`` /
    ``SET_NULL``-references it (offers, orders, member shares, deliveries,
    stock, forecasts, a variation's packing crate, …) counts as in use.

    Used to make a lookup price (``ShareArticleNetPrice`` / ``CrateNetPrice``)
    non-deletable once the thing it prices is actually in use, even though
    nothing FK-references the price row directly. Short-circuits on the first
    hit; callers cache per parent so a price-history list stays O(parents).
    """
    for relation in _reverse_relations(type(parent), set(), include_hidden=True):
        if relation.on_delete is CASCADE:
            continue
        if relation.related_model._base_manager.filter(
            **{relation.field.attname: parent.pk}
        ).exists():
            return True
    return False
