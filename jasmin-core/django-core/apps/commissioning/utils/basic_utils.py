from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.db.models import Case, IntegerField, TextChoices, Value, When

from ..models.choices_text import SizeOptions, SizeVegetableOptions, UnitOptions


def size_order_annotation():
    """Build a Case/When annotation that maps SizeOptions to their enum index."""
    whens = [
        When(size=choice[0], then=Value(idx))
        for idx, choice in enumerate(SizeOptions.choices)
    ]
    return Case(*whens, default=Value(999), output_field=IntegerField())


def extract_amounts_from_keys(
    data: dict[str, Any], prefix: str = "amount_"
) -> dict[str, Any]:
    """
    Extract IDs and amounts from data keys with a specific prefix pattern.

    Args:
        data: Dictionary containing keys like 'amount_<id>'
        prefix: The prefix to look for (default: 'amount_')

    Returns:
        Dictionary mapping IDs to their amounts

    Example:
        >>> data = {'amount_V9uWuNNgV0h6': '10.5', 'amount_UJVEq_SRG4RY': '20.0'}
        >>> extract_amounts_from_keys(data)
        {'V9uWuNNgV0h6': '10.5', 'UJVEq_SRG4RY': '20.0'}
    """
    amounts = {}
    prefix_len = len(prefix)

    for key, value in data.items():
        if key.startswith(prefix) and len(key) > prefix_len:
            # Extract ID by removing prefix
            extracted_id = key[prefix_len:]
            amounts[extracted_id] = value

    return amounts


def create_share_article_sorter(
    unit_choices: type[TextChoices] | None = None,
    size_choices: type[TextChoices] | None = None,
) -> Callable[[dict[str, Any]], tuple[str, int, int]]:
    """
    Create a sorting function for share articles.

    Args:
        unit_choices: Django TextChoices class for units (defaults to UnitOptions)
        size_choices: Django TextChoices class for sizes (defaults to SizeVegetableOptions)

    Returns:
        A function that can be used as a key for sorting

    Example:
        >>> sorter = create_share_article_sorter()
        >>> data = [{'share_article_name': 'Tomato', 'unit': 'kg', 'size': 'L'}]
        >>> sorted(data, key=sorter)
    """
    # Use defaults if not provided
    unit_choices = unit_choices or UnitOptions
    size_choices = size_choices or SizeVegetableOptions

    # Create ordering mappings (1-indexed for clarity)
    unit_order = {choice[0]: idx for idx, choice in enumerate(unit_choices.choices, 1)}
    size_order = {choice[0]: idx for idx, choice in enumerate(size_choices.choices, 1)}

    # Default value for unknown choices
    UNKNOWN_ORDER = 999

    def get_sort_key(item: dict[str, Any]) -> tuple[str, int, int]:
        """
        Custom sorting function for share articles.

        Sorts by: share_article_name -> unit -> size
        """
        share_article_name = item.get("share_article_name") or ""
        unit = item.get("unit") or ""
        size = item.get("size") or ""

        # Get numeric order for unit and size
        unit_order_value = unit_order.get(unit, UNKNOWN_ORDER)
        size_order_value = size_order.get(size, UNKNOWN_ORDER)

        return (share_article_name, unit_order_value, size_order_value)

    return get_sort_key


def sort_share_articles(
    data: list[dict[str, Any]],
    unit_choices: type[TextChoices] | None = None,
    size_choices: type[TextChoices] | None = None,
) -> list[dict[str, Any]]:
    """
    Sort a list of share article data.

    Args:
        data: List of dictionaries containing share article data
        unit_choices: Django TextChoices class for units (defaults to UnitOptions)
        size_choices: Django TextChoices class for sizes (defaults to SizeVegetableOptions)

    Returns:
        Sorted list of share articles

    Example:
        >>> articles = [
        ...     {'share_article_name': 'Tomato', 'unit': 'kg', 'size': 'L'},
        ...     {'share_article_name': 'Apple', 'unit': 'pieces', 'size': 'M'}
        ... ]
        >>> sorted_articles = sort_share_articles(articles)
    """
    sorter = create_share_article_sorter(unit_choices, size_choices)
    return sorted(data, key=sorter)
