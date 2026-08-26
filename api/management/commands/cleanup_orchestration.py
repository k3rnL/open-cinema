import json

from django.core.management.base import BaseCommand

from core.orchestration.retention import cleanup_orchestration_data


class Command(BaseCommand):
    help = "Remove expired audio-orchestration operational history."

    def handle(self, *args, **options):
        report = cleanup_orchestration_data()
        self.stdout.write(json.dumps(report.as_dict(), sort_keys=True))
