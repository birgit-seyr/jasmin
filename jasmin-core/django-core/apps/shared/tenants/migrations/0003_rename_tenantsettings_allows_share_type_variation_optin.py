from django.db import migrations


class Migration(migrations.Migration):
    """Rename TenantSettings.allows_share_variation_optin ->
    allows_share_type_variation_optin (naming consistency with ShareTypeVariation).

    RenameField (not remove+add) so the existing column's data is preserved.
    """

    dependencies = [
        (
            "tenants",
            "0002_remove_tenantsettings_allows_additional_subscriptions_without_base_share_type",
        ),
    ]

    operations = [
        migrations.RenameField(
            model_name="tenantsettings",
            old_name="allows_share_variation_optin",
            new_name="allows_share_type_variation_optin",
        ),
    ]
