from django.db import migrations


def create_profiles(apps, schema_editor):
    """Give every existing user a profile carrying their current roles.

    The list is copied VERBATIM — no sorting, no de-duplication, no dropping
    of unknown values. The JWT ``user_role`` claim is ``roles[0]``, so
    reordering here would hand existing users a different claim on their next
    login, and silently dropping a value would revoke access the row still
    grants today. Normalisation is the application's job, on the next write.
    """
    user_model = apps.get_model("accounts", "JasminUser")
    profile_model = apps.get_model("accounts", "JasminProfile")

    already = set(profile_model.objects.values_list("user_id", flat=True))
    profile_model.objects.bulk_create(
        [
            profile_model(user_id=pk, roles=roles)
            for pk, roles in user_model.objects.values_list("id", "roles")
            if pk not in already
        ],
        batch_size=500,
    )

    # A user without a profile reads as role-less: the permission classes ask
    # the profile for the roles, and an absent row denies everything. Refuse
    # to finish the migration in that state rather than discover it in
    # production as an unexplained 403.
    users = user_model.objects.count()
    profiles = profile_model.objects.count()
    if users != profiles:
        raise RuntimeError(
            f"Backfill incomplete in this schema: {users} users but "
            f"{profiles} profiles. Refusing to continue — every user needs "
            "a profile row or they lose all roles."
        )


def drop_profiles(apps, schema_editor):
    """Remove the profiles again.

    Genuinely reversible while the mirrored ``roles`` column is still present
    and still written on every role change: the data being deleted here exists
    in full on the user row. Once the follow-up migration drops that column
    this stops being true.
    """
    apps.get_model("accounts", "JasminProfile").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_jasminprofile"),
    ]

    operations = [
        migrations.RunPython(create_profiles, drop_profiles),
    ]
