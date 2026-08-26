from __future__ import annotations

import hashlib
import json

from django.core.serializers.json import DjangoJSONEncoder


def _model_document(model) -> dict[str, object]:
    fields = tuple(field.attname for field in model._meta.concrete_fields)
    rows = list(model.objects.order_by(model._meta.pk.attname).values(*fields))
    canonical = json.dumps(rows, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":"))
    return {
        "count": len(rows),
        "sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }


def dynamic_audio_state_document() -> dict[str, object]:
    """Describe user-owned audio intent independently from runtime projections."""

    from api.models import (
        CamillaDSPProfile,
        GraphActivation,
        GraphDefinition,
        GraphRevision,
        LogicalEndpoint,
        ManagedAudioAdapter,
        ManualOverride,
        OrchestrationEvent,
    )

    intent_models = (
        GraphDefinition,
        GraphRevision,
        GraphActivation,
        LogicalEndpoint,
        CamillaDSPProfile,
        ManagedAudioAdapter,
        ManualOverride,
    )
    models = {
        model._meta.label_lower: _model_document(model)
        for model in intent_models
    }
    canonical = json.dumps(models, sort_keys=True, separators=(",", ":"))
    latest_event = OrchestrationEvent.objects.order_by("-sequence").values("sequence").first()
    return {
        "schemaVersion": 1,
        "intentDigest": hashlib.sha256(canonical.encode()).hexdigest(),
        "models": models,
        "audit": {
            "count": OrchestrationEvent.objects.count(),
            "latestSequence": latest_event["sequence"] if latest_event else None,
        },
    }
