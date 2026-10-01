# Generated manually for Phase 5.5 retention booking attribution.

import django.db.models.deletion
from django.db import migrations, models

import customers.models


def populate_public_references(apps, schema_editor):
    CustomerRetentionMessage = apps.get_model("customers", "CustomerRetentionMessage")
    seen = set()
    for row in CustomerRetentionMessage.objects.all().iterator():
        ref = customers.models.generate_retention_public_reference()
        while ref in seen or CustomerRetentionMessage.objects.filter(public_reference=ref).exclude(
            pk=row.pk
        ).exists():
            ref = customers.models.generate_retention_public_reference()
        seen.add(ref)
        row.public_reference = ref
        row.save(update_fields=["public_reference"])


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0004_alter_customerretentionsettings_enabled_help"),
        ("locations", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="customerretentionmessage",
            name="location",
            field=models.ForeignKey(
                blank=True,
                help_text="Location used in the retention booking URL (set when the message is queued).",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="customer_retention_messages",
                to="locations.location",
            ),
        ),
        migrations.AddField(
            model_name="customerretentionmessage",
            name="public_reference",
            field=models.CharField(
                blank=True,
                default="",
                editable=False,
                help_text="Opaque ref for ?source=retention&ref=… booking URLs.",
                max_length=32,
            ),
        ),
        migrations.RunPython(populate_public_references, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="customerretentionmessage",
            name="public_reference",
            field=models.CharField(
                default=customers.models.generate_retention_public_reference,
                editable=False,
                help_text="Opaque ref for ?source=retention&ref=… booking URLs.",
                max_length=32,
                unique=True,
            ),
        ),
        migrations.AddIndex(
            model_name="customerretentionmessage",
            index=models.Index(
                fields=["location", "status"],
                name="cust_ret_msg_loc_status_idx",
            ),
        ),
    ]
