"""Natural-key resolvers shared by the data-list import serializers.

An import row names its related rows by a human-readable key, never by DB id.
A key that resolves to nothing raises a coded error the row loop reports as
that row's error.
"""

from __future__ import annotations

from ..errors import MemberNumberUnknown
from ..models import Member


def resolve_member_by_number(number: int) -> Member:
    """The member carrying ``member_number``; ``MemberNumberUnknown`` if none."""
    member = Member.objects.filter(member_number=number).first()
    if member is None:
        raise MemberNumberUnknown(
            f"No member with number {number}.",
            field="member_number",
            details={"member_number": number},
        )
    return member
