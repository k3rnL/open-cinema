# Set the default Django settings module for the 'celery' program.
import os

from opencinema_plugin_bootstrap import activate_plugin_overlay

activate_plugin_overlay()

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'opencinema.settings')

app = Celery('proj')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()
