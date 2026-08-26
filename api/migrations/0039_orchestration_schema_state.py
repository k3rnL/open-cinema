from django.db import migrations, models


ORCHESTRATION_SCHEMA_VERSION = 1


def initialize_orchestration_schema_state(apps, schema_editor):
    state_model = apps.get_model("api", "OrchestrationSchemaState")
    state_model.objects.create(id=1, version=ORCHESTRATION_SCHEMA_VERSION)


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0038_alter_pulseaudiotunnelnodestate_device"),
    ]
    operations = [
        migrations.CreateModel(
            name="OrchestrationSchemaState",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("version", models.PositiveIntegerField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("id", 1)),
                        name="api_orchestration_schema_state_singleton",
                    )
                ]
            },
        ),
        migrations.RunPython(
            initialize_orchestration_schema_state,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
