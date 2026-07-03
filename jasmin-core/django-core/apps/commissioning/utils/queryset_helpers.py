from collections.abc import Callable, Sequence
from typing import Any

from django.db.models import QuerySet

# A filter spec is one of:
#   "field"                       — param name == model field
#   ("param", "field__lookup")    — rename / related lookup
#   ("param", "field", transform) — value transform (e.g. exclude_trial_members
#                                   -> is_trial = not value)
FilterSpec = str | tuple[str, str] | tuple[str, str, Callable[[Any], Any]]


def apply_optional_filters(
    queryset: QuerySet,
    params: dict[str, Any],
    specs: Sequence[FilterSpec],
) -> QuerySet:
    """Apply ``filter(<field>=<value>)`` for each spec whose param is not None —
    the one-armed optional-filter idiom hand-copied across viewsets (8 identical
    lines in resellers). Each spec maps a centrally-extracted query param to a
    model field; a ``None`` param is skipped (the param wasn't supplied)."""
    for spec in specs:
        if isinstance(spec, str):
            param_name, field, transform = spec, spec, None
        elif len(spec) == 2:
            param_name, field = spec
            transform = None
        else:
            param_name, field, transform = spec
        value = params.get(param_name)
        if value is None:
            continue
        if transform is not None:
            value = transform(value)
        queryset = queryset.filter(**{field: value})
    return queryset
