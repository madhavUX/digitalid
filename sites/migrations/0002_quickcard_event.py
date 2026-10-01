import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("businesses", "0007_google_review_url"),
        ("locations", "0001_initial"),
        ("organizations", "0002_remove_super_admin_role"),
        ("sites", "0001_quickcard_mvp"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuickCardEvent",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("PAGE_VIEW", "Page view"),
                            ("CTA_CLICK", "CTA click"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "cta_type",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("BOOK", "Book"),
                            ("WHATSAPP", "WhatsApp"),
                            ("CALL", "Call"),
                            ("DIRECTIONS", "Directions"),
                            ("REVIEW", "Review"),
                            ("SHARE", "Share"),
                        ],
                        default="",
                        max_length=16,
                    ),
                ),
                ("occurred_at", models.DateTimeField()),
                ("referrer", models.CharField(blank=True, default="", max_length=500)),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="quickcard_events",
                        to="businesses.business",
                    ),
                ),
                (
                    "location",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="quickcard_events",
                        to="locations.location",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="quickcard_events",
                        to="organizations.organization",
                    ),
                ),
                (
                    "quickcard",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="events",
                        to="sites.quickcard",
                    ),
                ),
            ],
            options={
                "ordering": ["-occurred_at"],
                "indexes": [
                    models.Index(
                        fields=["business", "occurred_at"],
                        name="qc_event_biz_time_idx",
                    ),
                    models.Index(
                        fields=["quickcard", "event_type", "occurred_at"],
                        name="qc_event_card_type_idx",
                    ),
                    models.Index(
                        fields=["business", "cta_type", "occurred_at"],
                        name="qc_event_cta_time_idx",
                    ),
                ],
            },
        ),
    ]
