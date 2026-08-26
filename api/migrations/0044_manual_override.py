import django.db.models.deletion
import django.utils.timezone
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0043_logical_endpoint"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ManualOverride",
            fields=[
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
                    "scope_type",
                    models.CharField(
                        choices=[
                            ("endpoint", "Endpoint selection"),
                            ("scene", "Scene selection"),
                            ("volume", "Volume"),
                            ("mute", "Mute"),
                            ("route", "Route selection"),
                            ("graph_parameter", "Graph parameter"),
                        ],
                        max_length=32,
                    ),
                ),
                ("scope_id", models.CharField(max_length=255)),
                ("value", models.JSONField()),
                ("priority", models.IntegerField(default=100)),
                ("reason", models.TextField()),
                ("starts_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "cancelled_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="cancelled_audio_overrides",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_audio_overrides",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-priority", "starts_at", "id"),
                "indexes": [
                    models.Index(
                        fields=["scope_type", "scope_id", "priority"],
                        name="api_override_scope_prio_idx",
                    ),
                    models.Index(
                        fields=["starts_at", "expires_at", "cancelled_at"],
                        name="api_override_active_window_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=(
                            models.Q(("expires_at__isnull", True))
                            | models.Q(("expires_at__gt", models.F("starts_at")))
                        ),
                        name="api_manual_override_expiry_after_start",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                ("cancelled_at__isnull", True),
                                ("cancelled_by__isnull", True),
                            )
                            | models.Q(
                                ("cancelled_at__isnull", False),
                                ("cancelled_by__isnull", False),
                            )
                        ),
                        name="api_manual_override_cancellation_pair",
                    ),
                ],
            },
        ),
    ]
