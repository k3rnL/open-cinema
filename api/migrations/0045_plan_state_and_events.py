import django.db.models.deletion
import django.utils.timezone
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0044_manual_override"),
    ]

    operations = [
        migrations.CreateModel(
            name="ResolvedPlan",
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
                ("schema_version", models.PositiveIntegerField(default=1)),
                ("desired_state_version", models.PositiveBigIntegerField()),
                ("world_generation", models.PositiveBigIntegerField()),
                ("world_sequence", models.PositiveBigIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("resolved", "Resolved"),
                            ("waiting", "Waiting"),
                            ("degraded", "Degraded"),
                            ("conflicted", "Conflicted"),
                            ("invalid", "Invalid"),
                        ],
                        max_length=16,
                    ),
                ),
                ("document", models.JSONField()),
                ("explanation", models.JSONField(default=dict)),
                ("plan_digest", models.CharField(editable=False, max_length=64)),
                ("correlation_id", models.UUIDField(db_index=True, default=uuid.uuid4)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "graph_definition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="resolved_plans",
                        to="api.graphdefinition",
                    ),
                ),
                (
                    "graph_revision",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="resolved_plans",
                        to="api.graphrevision",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at", "id"),
                "indexes": [
                    models.Index(
                        fields=["graph_definition", "created_at"],
                        name="api_plan_graph_time_idx",
                    ),
                    models.Index(
                        fields=["status", "created_at"],
                        name="api_plan_status_time_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("schema_version__gte", 1)),
                        name="api_resolved_plan_schema_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("desired_state_version__gte", 1)),
                        name="api_resolved_plan_desired_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("world_generation__gte", 1)),
                        name="api_resolved_plan_world_generation_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="AppliedPlanState",
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
                ("transition_generation", models.PositiveBigIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("idle", "Idle"),
                            ("applying", "Applying"),
                            ("converged", "Converged"),
                            ("degraded", "Degraded"),
                            ("failed", "Failed"),
                        ],
                        default="idle",
                        max_length=16,
                    ),
                ),
                ("correlation_id", models.UUIDField(db_index=True, default=uuid.uuid4)),
                ("last_error", models.JSONField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "current_plan",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="current_applied_states",
                        to="api.resolvedplan",
                    ),
                ),
                (
                    "graph_definition",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="applied_plan_state",
                        to="api.graphdefinition",
                    ),
                ),
                (
                    "previous_plan",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="previous_applied_states",
                        to="api.resolvedplan",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["status", "updated_at"],
                        name="api_applied_plan_status_idx",
                    )
                ]
            },
        ),
        migrations.CreateModel(
            name="TransitionJournal",
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
                ("generation", models.PositiveBigIntegerField()),
                ("correlation_id", models.UUIDField(db_index=True)),
                (
                    "phase",
                    models.CharField(
                        choices=[
                            ("prepare", "Prepare"),
                            ("suppress", "Suppress"),
                            ("configure", "Configure"),
                            ("route", "Route"),
                            ("verify", "Verify"),
                            ("unsuppress", "Unsuppress"),
                            ("cleanup", "Cleanup"),
                            ("completed", "Completed"),
                        ],
                        default="prepare",
                        max_length=16,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                            ("rolled_back", "Rolled back"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("entries", models.JSONField(default=list)),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "graph_definition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transition_journals",
                        to="api.graphdefinition",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transition_journals",
                        to="api.resolvedplan",
                    ),
                ),
            ],
            options={
                "ordering": ("graph_definition_id", "generation"),
                "indexes": [
                    models.Index(
                        fields=["status", "updated_at"],
                        name="api_transition_status_time_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("graph_definition", "generation"),
                        name="api_transition_graph_generation_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("generation__gte", 1)),
                        name="api_transition_generation_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="OrchestrationEvent",
            fields=[
                ("sequence", models.BigAutoField(primary_key=True, serialize=False)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("correlation_id", models.UUIDField(db_index=True)),
                ("event_type", models.CharField(max_length=128)),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("debug", "Debug"),
                            ("info", "Info"),
                            ("warning", "Warning"),
                            ("error", "Error"),
                        ],
                        default="info",
                        max_length=16,
                    ),
                ),
                ("payload", models.JSONField(default=dict)),
                ("occurred_at", models.DateTimeField(auto_now_add=True)),
                (
                    "graph_definition",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="orchestration_events",
                        to="api.graphdefinition",
                    ),
                ),
            ],
            options={
                "ordering": ("sequence",),
                "indexes": [
                    models.Index(
                        fields=["event_type", "occurred_at"],
                        name="api_orch_event_type_time_idx",
                    ),
                    models.Index(
                        fields=["graph_definition", "sequence"],
                        name="api_orch_event_graph_seq_idx",
                    ),
                ],
            },
        ),
    ]
