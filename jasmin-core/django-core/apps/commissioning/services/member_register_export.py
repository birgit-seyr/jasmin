"""GenG §30 Mitgliederliste — date-range member-register CSV export.

The cooperative must keep a member list documenting, per member, their name +
address, date of joining (Eintritt) and leaving (Austritt), and the cooperative
shares + paid-in capital held. This builds that register for a [date_from,
date_to] window: every member who was a member at any point in the window —
including those who left mid-window — so the Austritt column carries real data.

Headers are deliberately German + untranslated (machine-readable export; only
delimiter / decimal separator / date format are localized via the tenant's
``csv_format`` — see ``utils/csv_format.py``).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

from django.db.models import Q
from django.http import StreamingHttpResponse

from apps.shared.csv_safety import CsvEchoBuffer, escape_csv_row

from ..models import CoopShare, Member
from ..models.mixin import PRICE_QUANTIZE as _CENT
from ..utils.csv_format import get_csv_dialect

_HEADERS = [
    "Mitgliedsnummer",
    "Name",
    "Adresse",
    "PLZ",
    "Ort",
    "Eintrittsdatum",
    "Austrittsdatum",
    "Anzahl Geschäftsanteile",
    "Geschäftsguthaben",
]


def _member_name(member: Member) -> str:
    if member.company_name:
        return member.company_name
    return " ".join(p for p in (member.last_name, member.first_name) if p)


def build_member_register_csv_response(
    *, date_from: date, date_to: date
) -> StreamingHttpResponse:
    """Stream the GenG §30 register for ``[date_from, date_to]``.

    A member is in the window if they were admitted by its end (``entry_date``
    set and ``<= date_to``) and had not yet left at its start (no exit date, or
    exit on/after ``date_from``). Holdings are reported AS OF ``date_to`` (a
    share counts unless it was cancelled on or before that day).
    """
    members = list(
        Member.objects.filter(
            admin_confirmed=True,
            entry_date__isnull=False,
            entry_date__lte=date_to,
        )
        .filter(
            Q(cancelled_effective_at__isnull=True)
            | Q(cancelled_effective_at__gte=date_from)
        )
        .order_by("member_number", "last_name", "first_name")
    )

    # One grouped query for everyone's confirmed shares (CoopShare.member has
    # related_name="+", so there's no reverse accessor to prefetch — group by
    # member_id in Python instead of an N+1 per-member query).
    member_ids = [m.id for m in members]
    holdings: dict[str, list[Decimal]] = defaultdict(
        lambda: [Decimal("0"), Decimal("0")]  # [share count, paid-in capital]
    )
    if member_ids:
        coop_shares = CoopShare.objects.filter(
            member_id__in=member_ids, admin_confirmed=True
        ).only(
            "member_id",
            "amount_of_coop_shares",
            "value_one_coop_share",
            "cancelled_at",
        )
        for share in coop_shares:
            # As-of-date_to: skip shares already divested by the window end.
            if share.cancelled_at is not None and share.cancelled_at.date() <= date_to:
                continue
            amount = share.amount_of_coop_shares or Decimal("0")
            bucket = holdings[share.member_id]
            bucket[0] += amount
            bucket[1] += amount * Decimal(share.value_one_coop_share)

    dialect = get_csv_dialect()
    writer = csv.writer(CsvEchoBuffer(), delimiter=dialect.delimiter)

    def rows() -> Iterator[str]:
        yield "﻿"  # BOM first so Excel opens UTF-8 correctly.
        yield writer.writerow(escape_csv_row(_HEADERS))
        for member in members:
            count, capital = holdings.get(member.id, [Decimal("0"), Decimal("0")])
            yield writer.writerow(
                escape_csv_row(
                    [
                        (
                            str(member.member_number)
                            if member.member_number is not None
                            else ""
                        ),
                        _member_name(member),
                        member.address or "",
                        member.zip_code or "",
                        member.city or "",
                        dialect.format(member.entry_date),
                        dialect.format(member.cancelled_effective_at),
                        dialect.format(count),
                        dialect.format(capital.quantize(_CENT)),
                    ]
                )
            )

    response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
    filename = f"mitgliederliste_{date_from.isoformat()}_{date_to.isoformat()}"
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    return response
