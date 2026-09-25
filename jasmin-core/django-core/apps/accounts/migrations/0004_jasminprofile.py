import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0003_alter_jasminuser_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="JasminProfile",
            fields=[
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="jasmin_profile",
                        serialize=False,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "roles",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="List of roles this user has",
                        null=True,
                    ),
                ),
            ],
        ),
    ]
