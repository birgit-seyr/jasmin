from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0016_tenant_app_icon_tenant_app_short_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantsettings",
            name="onboarding_mode",
            field=models.BooleanField(default=False),
        ),
    ]
