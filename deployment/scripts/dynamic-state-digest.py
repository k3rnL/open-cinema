#!/usr/bin/env python3
"""Report a stable digest of Open Cinema's user-owned audio intent."""

from __future__ import annotations

import hashlib
import json
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "opencinema.settings")

import django  # noqa: E402
from django.core.serializers.json import DjangoJSONEncoder  # noqa: E402

django.setup()

from api.models import (  # noqa: E402
    CamillaDSPProfile,
    GraphActivation,
    GraphDefinition,
    GraphRevision,
    LogicalEndpoint,
    ManagedAudioAdapter,
    ManualOverride,
    OrchestrationEvent,
)


INTENT_MODELS = (
    GraphDefinition,
    GraphRevision,
    GraphActivation,
    LogicalEndpoint,
    CamillaDSPProfile,
    ManagedAudioAdapter,
    ManualOverride,
)


def model_document(model) -> dict[str, object]:
    fields = tuple(field.attname for field in model._meta.concrete_fields)
    rows = list(model.objects.order_by(model._meta.pk.attname).values(*fields))
    canonical = json.dumps(rows, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":"))
    return {
        "count": len(rows),
        "sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }


models = {
    model._meta.label_lower: model_document(model)
    for model in INTENT_MODELS
}
intent_json = json.dumps(models, sort_keys=True, separators=(",", ":"))
latest_event = OrchestrationEvent.objects.order_by("-sequence").values("sequence").first()
print(
    json.dumps(
        {
            "schemaVersion": 1,
            "intentDigest": hashlib.sha256(intent_json.encode()).hexdigest(),
            "models": models,
            "audit": {
                "count": OrchestrationEvent.objects.count(),
                "latestSequence": latest_event["sequence"] if latest_event else None,
            },
        },
        sort_keys=True,
    )
)
