from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from core.orchestration.deployment_state import dynamic_audio_state_document


class Command(BaseCommand):
    help = "Report a stable digest of user-owned audio intent for upgrade and rollback checks."

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(dynamic_audio_state_document(), sort_keys=True))
