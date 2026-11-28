from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0025_tenantsettings_has_purchases"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantsettings",
            name="uses_organic_documentation",
            field=models.BooleanField(db_default=True, default=True),
        ),
    ]
