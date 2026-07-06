import django.db.models.deletion
from django.db import migrations, models


def backfill_reseller_contacts(apps, schema_editor):
    """Give every contactless Reseller a placeholder ContactEntity so the
    non-null ``contact`` FK can be enforced.

    Real (office-UI-created) resellers always have a contact — the create
    serializer requires the address fields — so this only touches legacy /
    imported / seed rows. Forward-only: the reverse is a no-op (the placeholder
    contacts can't be meaningfully un-created).
    """
    Reseller = apps.get_model("commissioning", "Reseller")
    ContactEntity = apps.get_model("commissioning", "ContactEntity")
    for reseller in Reseller.objects.filter(contact__isnull=True):
        contact = ContactEntity.objects.create(
            company_name=reseller.name_for_member_pages or "Unbenannt",
            address="(unbekannt)",
            zip_code="00000",
            city="(unbekannt)",
        )
        reseller.contact = contact
        reseller.save(update_fields=["contact"])


class Migration(migrations.Migration):

    dependencies = [
        ("commissioning", "0013_alter_consentdocument_kind"),
    ]

    operations = [
        # Backfill BEFORE the NOT NULL alter so no existing row violates it.
        migrations.RunPython(backfill_reseller_contacts, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="reseller",
            name="contact",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to="commissioning.contactentity",
            ),
        ),
    ]
