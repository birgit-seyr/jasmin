from __future__ import annotations

from typing import Any

from django.db import transaction

from ..errors import RequiredFieldMissing
from ..models import (
    ContactEntity,
    DeliveryStation,
    Reseller,
)
from ..utils.deletion_utils import can_delete_instance


class ResellerAndDeliveryStationService:
    @transaction.atomic
    def create_reseller(self, validated_data: dict[str, Any]) -> Reseller:
        contact_data = self._extract_contact_data(validated_data)
        contact = None

        if contact_data:
            contact = self._create_contact_from_data(contact_data)

        validated_data["contact"] = contact
        # Transient flag from the serializer — not a model field.
        is_also_delivery_station = validated_data.pop("is_also_delivery_station", False)
        reseller = Reseller.objects.create(**validated_data)

        if is_also_delivery_station and contact:
            delivery_station, _ = DeliveryStation.objects.get_or_create(contact=contact)
            delivery_station.linked_reseller = reseller
            delivery_station.is_also_reseller = reseller.is_reseller
            delivery_station.is_also_seller = reseller.is_seller
            delivery_station.save()

        self._apply_invoice_defaults(reseller)

        return reseller

    @transaction.atomic
    def create_delivery_station(
        self, validated_data: dict[str, Any]
    ) -> DeliveryStation:
        contact_data = self._extract_contact_data(validated_data)
        contact = None

        if contact_data:
            contact = self._create_contact_from_data(contact_data)

        validated_data["contact"] = contact
        delivery_station = DeliveryStation.objects.create(**validated_data)

        if (
            delivery_station.is_also_reseller or delivery_station.is_also_seller
        ) and contact:
            reseller, created = Reseller.objects.get_or_create(contact=contact)
            reseller.is_reseller = (
                reseller.is_reseller or delivery_station.is_also_reseller
            )
            reseller.is_seller = reseller.is_seller or delivery_station.is_also_seller
            reseller.save()
            delivery_station.linked_reseller = reseller
            delivery_station.save(update_fields=["linked_reseller"])

        return delivery_station

    @transaction.atomic
    def update_reseller(
        self, instance: Reseller, validated_data: dict[str, Any]
    ) -> Reseller:
        contact_data = self._extract_contact_data(validated_data)

        self._update_contact(instance.contact, contact_data)

        # Transient flag (not a model field) drives auto-link to a
        # ``DeliveryStation``. The link itself lives on the DS side.
        is_also_delivery_station = validated_data.pop("is_also_delivery_station", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if is_also_delivery_station is True and instance.contact:
            delivery_station, _ = DeliveryStation.objects.get_or_create(
                contact=instance.contact
            )
            delivery_station.is_active = True
            delivery_station.is_also_reseller = True
            delivery_station.linked_reseller = instance
            delivery_station.save()
        elif is_also_delivery_station is False and instance.contact:
            try:
                delivery_station = DeliveryStation.objects.get(linked_reseller=instance)
                can_delete, _ = can_delete_instance(
                    delivery_station, exclude_models=["Reseller"]
                )
                if can_delete:
                    delivery_station.delete()
                # Otherwise the DS still has dependants — silently ignore the
                # unlink so we don't orphan it. The frontend mirrors this via
                # ``linked_delivery_station_can_be_deleted`` (disabled checkbox).
            except DeliveryStation.DoesNotExist:
                pass

        self._apply_invoice_defaults(instance)

        return instance

    @staticmethod
    def _apply_invoice_defaults(reseller: Reseller) -> None:
        """Pre-fill ``invoice_*`` fields from the linked contact when
        they're blank — never overwrite an existing value.

        Real-world semantics: a fresh reseller row needs an invoice
        recipient block and an invoice email; the office shouldn't
        have to retype the same address twice on the same form. But
        once the office has customised the invoice block (storefront
        and accounting office at different addresses, for example),
        future edits to the BASE contact must not silently clobber
        that customisation. Hence the strict ``if not getattr(...)``
        guard.

        Mapping:
            invoice_name     <- contact.company_name OR
                                "{first_name} {last_name}"
            invoice_address  <- contact.address
            invoice_plz      <- contact.zip_code
            invoice_city     <- contact.city
            invoice_email    <- contact.email

        ``invoice_name2`` (line 2 / c/o / department), ``invoice_via_
        email``, customer/filial numbers, IBAN, UID, and payment
        conditions are intentionally LEFT alone — they don't have an
        obvious base-field counterpart, and the office types them
        explicitly when they need them.
        """
        contact = reseller.contact
        if not contact:
            return

        fallback_name = contact.company_name or (
            f"{contact.first_name or ''} {contact.last_name or ''}".strip()
        )
        mapping = {
            "invoice_name": fallback_name or "",
            "invoice_address": contact.address,
            "invoice_plz": contact.zip_code,
            "invoice_city": contact.city,
            "invoice_email": contact.email,
        }
        update_fields: list[str] = []
        for field, source_value in mapping.items():
            if not getattr(reseller, field) and source_value:
                setattr(reseller, field, source_value)
                update_fields.append(field)
        if update_fields:
            reseller.save(update_fields=update_fields)

    @transaction.atomic
    def update_delivery_station(
        self, instance: DeliveryStation, validated_data: dict[str, Any]
    ) -> DeliveryStation:
        contact_data = self._extract_contact_data(validated_data)

        self._update_contact(instance.contact, contact_data)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if (instance.is_also_reseller or instance.is_also_seller) and instance.contact:
            reseller, created = Reseller.objects.get_or_create(contact=instance.contact)
            reseller.is_reseller = reseller.is_reseller or instance.is_also_reseller
            reseller.is_seller = reseller.is_seller or instance.is_also_seller
            reseller.save()

            instance.linked_reseller = reseller
            instance.save(update_fields=["linked_reseller"])
        else:
            try:
                reseller = Reseller.objects.get(contact=instance.contact)
                can_delete, _ = can_delete_instance(
                    reseller, exclude_models=["DeliveryStation"]
                )
                if can_delete:
                    reseller.delete()
                    instance.linked_reseller = None
                    instance.save(update_fields=["linked_reseller"])
                else:
                    # Reseller has related objects — keep the link intact
                    instance.is_also_reseller = reseller.is_reseller
                    instance.is_also_seller = reseller.is_seller
                    instance.save(update_fields=["is_also_reseller", "is_also_seller"])
            except Reseller.DoesNotExist:
                pass

        return instance

    @transaction.atomic
    def delete_reseller(
        self, instance: Reseller, delete_context: str | None = None
    ) -> None:
        if delete_context == "sellers":
            if instance.is_reseller:
                instance.is_seller = False
                instance.save()
            else:
                self._unlink_and_delete_reseller(instance)

        elif delete_context == "resellers":
            if instance.is_seller:
                instance.is_reseller = False
                instance.save()
            else:
                self._unlink_and_delete_reseller(instance)

    @transaction.atomic
    def delete_delivery_station(self, instance: DeliveryStation) -> None:
        # A station's pickup days CASCADE to ShareDelivery (the billing basis).
        # Refuse to delete while any delivery still hangs off the station —
        # otherwise the delete silently wipes billing/history with no recompute.
        from ..errors import DeliveryStationInUse
        from ..models import ShareDelivery

        delivery_count = ShareDelivery.objects.filter(
            delivery_station_day__delivery_station=instance
        ).count()
        if delivery_count:
            raise DeliveryStationInUse(station=instance, delivery_count=delivery_count)

        contact = instance.contact

        # Unlink from reseller if one exists — the OneToOne lives on this side,
        # so deleting ``instance`` (or setting its ``linked_reseller`` to None)
        # is sufficient. Nothing to write on the Reseller.
        instance.delete()

        # Delete orphaned contact
        if contact and not Reseller.objects.filter(contact=contact).exists():
            contact.delete()

    def _unlink_and_delete_reseller(self, instance: Reseller) -> None:
        """Unlink from delivery station, delete reseller, and clean up orphaned contact."""
        try:
            delivery_station = DeliveryStation.objects.get(contact=instance.contact)
            delivery_station.is_also_reseller = False
            delivery_station.is_also_seller = False
            delivery_station.linked_reseller = None
            delivery_station.save(
                update_fields=[
                    "is_also_reseller",
                    "is_also_seller",
                    "linked_reseller",
                ]
            )
            instance.delete()
        except DeliveryStation.DoesNotExist:
            contact = instance.contact
            instance.delete()
            if contact:
                contact.delete()

    def _create_contact_from_data(self, contact_data: dict[str, Any]) -> ContactEntity:
        """Create a fresh ContactEntity from validated data.

        Deliberately a plain ``create`` — NOT ``get_or_create``. There is no
        unique constraint to make an all-fields ``get_or_create`` race-safe, and
        the field-value match it did was already broken single-threaded (the
        lookup included the ``EncryptedCharField`` iban, whose ciphertext is
        never equal by value, so any populated bank field guaranteed a fresh
        row anyway). Each reseller / delivery-station therefore gets its own
        contact; the supported reseller↔station merge is the within-call
        ``is_also_*`` path (which shares this one contact), not a fragile
        retype-identical-data dedup across separate creates.
        """
        required_fields = ["address", "zip_code", "city"]
        missing_fields = [
            field for field in required_fields if not contact_data.get(field)
        ]

        if missing_fields:
            raise RequiredFieldMissing(
                f"Missing required contact fields: {', '.join(missing_fields)}",
                details={"missing_fields": missing_fields},
            )

        return ContactEntity.objects.create(**contact_data)

    @transaction.atomic
    def _update_contact(
        self,
        contact: ContactEntity | None,
        contact_data: dict[str, Any],
    ) -> None:
        """Update existing contact."""
        if not contact or not contact_data:
            return

        for attr, value in contact_data.items():
            setattr(contact, attr, value)
        contact.save()

    def _extract_contact_data(self, validated_data: dict[str, Any]) -> dict[str, Any]:
        """Extract contact-related fields from validated_data."""
        excluded_fields = {"id"}
        contact_fields = [
            field.name
            for field in ContactEntity._meta.get_fields()
            if (
                not field.many_to_many
                and not field.one_to_many
                and not field.one_to_one
                and field.name not in excluded_fields
            )
        ]

        contact_data: dict[str, Any] = {}
        for field in contact_fields:
            if field in validated_data:
                contact_data[field] = validated_data.pop(field)

        return contact_data
