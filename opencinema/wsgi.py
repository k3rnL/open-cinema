"""
WSGI config for opencinema project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from opencinema_plugin_bootstrap import activate_plugin_overlay

activate_plugin_overlay()

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "opencinema.settings")

application = get_wsgi_application()

from api.apps import PLUGIN_REGISTRY, initialize_plugin_runtime
from core.orchestration.schema_version import ensure_persistent_orchestration_schema_compatible
from core.plugin_system.operations import finalize_startup_operations

ensure_persistent_orchestration_schema_compatible()
initialize_plugin_runtime()
finalize_startup_operations(PLUGIN_REGISTRY)
