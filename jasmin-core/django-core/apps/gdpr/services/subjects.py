"""Who an erasure or an export is about.

A data subject is a login user, a member, a reseller, or a combination: a
member's login, a reseller's login, or a person who is both through one login.
The office also handles people without a login, so every entry point resolves
the subject to the same three slots before anything is read or scrubbed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.authz.roles import STAFF_ROLES, Role
from apps.commissioning.models import Member, Reseller

from ..field_classes import get_classification

if TYPE_CHECKING:
    from apps.accounts.models import JasminUser

# Anonymization rewrites a user's email to ``deleted_<pk>@deleted.invalid``.
ANONYMIZED_EMAIL_SUFFIX = "@deleted.invalid"


@dataclass(frozen=True)
class ErasureSubject:
    user: JasminUser | None = None
    member: Member | None = None
    reseller: Reseller | None = None

    @classmethod
    def of_user(cls, user: JasminUser) -> ErasureSubject:
        return cls(
            user=user,
            member=Member.objects.filter(user=user).first(),
            reseller=Reseller.objects.filter(linked_user=user).first(),
        )

    @classmethod
    def of_member(cls, member: Member) -> ErasureSubject:
        """A member with a login is that login's whole subject, so a reseller
        account on the same login is erased with it."""
        user = member.user
        if user is not None:
            return cls.of_user(user)
        return cls(member=member)

    @classmethod
    def of_ex_member(cls, member: Member) -> ErasureSubject:
        """What the retention sweep erases once ``member``'s exit is past the
        retention period: :meth:`of_member`, unless the member's login holds a
        staff or customer role.

        Such a login serves more than the membership, so it stays and the
        erasure releases it from the member. The member create and the CSV
        import link any login whose email matches, an admin's included, and the
        office dates the exit, to any past day while the member has no entry
        date. Erasing such a login is an admin's decision, made with step-up.
        """
        user = member.user
        if user is not None and user.has_any_role(STAFF_ROLES | {Role.CUSTOMER}):
            return cls(member=member)
        return cls.of_member(member)

    @classmethod
    def of_reseller(cls, reseller: Reseller) -> ErasureSubject:
        user = reseller.linked_user
        if user is not None:
            return cls.of_user(user)
        return cls(reseller=reseller)

    @classmethod
    def from_keys(
        cls, *, user_pk: str = "", member_pk: str = "", reseller_pk: str = ""
    ) -> ErasureSubject | None:
        """The subject a deletion-log row names, or None when none of its
        rows exist (any more, or yet).

        A row without a login names a member erased without one: a login the
        member is linked to now, after a restore, outlived that erasure (see
        :meth:`of_ex_member`) and isn't part of the subject."""
        if user_pk:
            user = get_user_model().objects.filter(pk=user_pk).first()
            if user is not None:
                return cls.of_user(user)
        if member_pk:
            member = Member.objects.filter(pk=member_pk).first()
            if member is not None:
                return cls.of_member(member) if user_pk else cls(member=member)
        if reseller_pk:
            reseller = Reseller.objects.filter(pk=reseller_pk).first()
            if reseller is not None:
                return cls.of_reseller(reseller)
        return None

    @property
    def email(self) -> str:
        """The address the subject is best known by, or "" when there is
        none: the login's, else the member's, else the reseller contact's."""
        if self.user is not None and self.user.email:
            return self.user.email
        if self.member is not None and self.member.email:
            return self.member.email
        if self.reseller is not None and self.reseller.contact.email:
            return self.reseller.contact.email
        return ""

    @property
    def is_erased(self) -> bool:
        """True once anonymization has run on every part of the subject."""
        if self.user is not None and not self.user.email.endswith(
            ANONYMIZED_EMAIL_SUFFIX
        ):
            return False
        if self.member is not None and not _is_anonymized_member(self.member):
            return False
        if self.reseller is not None and not _is_anonymized_reseller(self.reseller):
            return False
        return any((self.user, self.member, self.reseller))


def _tombstone(model_label: str, field: str) -> object:
    return get_classification(model_label)[field][1]


def _is_anonymized_member(member: Member) -> bool:
    return (
        member.first_name == _tombstone("commissioning.Member", "first_name")
        and member.last_name == _tombstone("commissioning.Member", "last_name")
        and not member.email
    )


def _is_anonymized_reseller(reseller: Reseller) -> bool:
    return (
        reseller.name_for_member_pages
        == _tombstone("commissioning.Reseller", "name_for_member_pages")
        and not reseller.invoice_email
        and reseller.linked_user_id is None
    )


def anonymized_member_q() -> Q:
    """The members anonymization has run on, as :func:`_is_anonymized_member`
    tells them apart — for a query."""
    return Q(
        first_name=_tombstone("commissioning.Member", "first_name"),
        last_name=_tombstone("commissioning.Member", "last_name"),
    ) & (Q(email__isnull=True) | Q(email=""))


def anonymized_reseller_q() -> Q:
    """The resellers anonymization has run on, as
    :func:`_is_anonymized_reseller` tells them apart — for a query."""
    return Q(
        name_for_member_pages=_tombstone(
            "commissioning.Reseller", "name_for_member_pages"
        ),
        linked_user__isnull=True,
    ) & (Q(invoice_email__isnull=True) | Q(invoice_email=""))
