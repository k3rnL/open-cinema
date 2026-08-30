from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from .storage import PluginSecretRepository

_PURPOSE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class CorePluginHostServices:
    plugin_id: str
    instance_id: str

    def private_directory(self, purpose: str) -> str:
        if not isinstance(purpose, str) or not _PURPOSE.fullmatch(purpose):
            raise ValueError("private directory purpose must be a lowercase identifier")
        root = Path(settings.OPEN_CINEMA_PLUGIN_RUNTIME_DIR).resolve()
        directory = (root / self.plugin_id / self.instance_id / purpose).resolve()
        if root not in directory.parents:
            raise ValueError("private runtime directory escaped its plugin root")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        return str(directory)

    def secret_presence(self, secret_id: str) -> bool:
        return PluginSecretRepository.presence(self.plugin_id, secret_id).configured

    def resolve_secret(self, secret_id: str) -> bytes:
        return PluginSecretRepository.resolve_for_owner(
            plugin_id=self.plugin_id,
            secret_id=secret_id,
            owner_plugin_id=self.plugin_id,
        )

    def invoke_automation(self, automation_id: str, payload: Mapping[str, object]) -> object:
        if not isinstance(automation_id, str) or not automation_id or len(automation_id) > 128:
            raise ValueError("automation_id must be between 1 and 128 characters")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > 64 * 1024:
            raise ValueError("automation payload exceeds 65536 bytes")
        from api.apps import PLUGIN_AUTOMATIONS

        return PLUGIN_AUTOMATIONS.invoke(automation_id, dict(payload))

    def logical_endpoint_references(
        self,
        logical_endpoint_id: str,
    ) -> tuple[Mapping[str, object], ...]:
        """Return bounded graph references owned by the same user as this instance."""

        if not isinstance(logical_endpoint_id, str) or not logical_endpoint_id:
            raise ValueError("logical_endpoint_id must be a non-empty string")
        from api.models import GraphRevision, LogicalEndpoint, PluginInstance

        instance = PluginInstance.objects.only("owner_id").get(
            plugin_id=self.plugin_id,
            instance_id=self.instance_id,
        )
        endpoint = LogicalEndpoint.objects.only("owner_id").filter(pk=logical_endpoint_id).first()
        if endpoint is None:
            return ()
        if instance.owner_id is None or endpoint.owner_id != instance.owner_id:
            raise PermissionError("logical endpoint belongs to another plugin instance owner")

        def contains(value: object) -> bool:
            if value == logical_endpoint_id:
                return True
            if isinstance(value, Mapping):
                return any(contains(item) for item in value.values())
            if isinstance(value, (list, tuple)):
                return any(contains(item) for item in value)
            return False

        references = []
        revisions = GraphRevision.objects.filter(
            definition__owner_id=instance.owner_id,
        ).select_related("definition")[:500]
        for revision in revisions:
            if not contains(revision.content):
                continue
            references.append(
                {
                    "definitionId": str(revision.definition_id),
                    "definitionName": revision.definition.name,
                    "revisionId": str(revision.pk),
                    "revisionNumber": revision.revision_number,
                    "state": revision.state,
                }
            )
            if len(references) >= 100:
                break
        return tuple(references)
