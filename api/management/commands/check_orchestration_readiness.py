from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from core.orchestration.readiness import inspect_orchestration_readiness


class Command(BaseCommand):
    help = "Verify database/schema and persisted audio orchestration readiness."

    def handle(self, *args, **options) -> None:
        report = inspect_orchestration_readiness()
        document = report.to_document()
        encoded = json.dumps(document, sort_keys=True)
        if not report.ready:
            raise CommandError(encoded)
        self.stdout.write(encoded)
