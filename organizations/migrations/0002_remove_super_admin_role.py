from django.db import migrations, models


def reassign_super_admin_memberships(apps, schema_editor):
    """SUPER_ADMIN is not an organization role. Map any rows to OWNER safely.

    Platform administration remains User.is_superuser / User.is_staff.
    No rows are deleted.
    """
    OrganizationMember = apps.get_model("organizations", "OrganizationMember")
    updated = OrganizationMember.objects.filter(role="SUPER_ADMIN").update(role="OWNER")
    if updated:
        # Visible in migration output for operators reviewing the change.
        print(f"Reassigned {updated} OrganizationMember row(s) from SUPER_ADMIN to OWNER.")


def noop_reverse(apps, schema_editor):
    # Irreversible by design: we cannot know which OWNER rows were formerly SUPER_ADMIN.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(reassign_super_admin_memberships, noop_reverse),
        migrations.AlterField(
            model_name="organizationmember",
            name="role",
            field=models.CharField(
                choices=[("OWNER", "Owner"), ("MANAGER", "Manager"), ("STAFF", "Staff")],
                max_length=32,
            ),
        ),
    ]
