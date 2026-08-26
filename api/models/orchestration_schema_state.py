from django.core.exceptions import ValidationError
from django.db import models


class OrchestrationSchemaState(models.Model):
    """Singleton marker for the durable orchestration document/data contract."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    version = models.PositiveIntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1),
                name="api_orchestration_schema_state_singleton",
            )
        ]

    def clean(self):
        if self.pk != 1:
            raise ValidationError({"id": "The orchestration schema marker must use id=1."})
