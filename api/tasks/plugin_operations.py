from celery import shared_task

from core.plugin_system.operations import execute_plugin_operation


@shared_task(
    name="api.execute_plugin_operation",
    autoretry_for=(),
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_plugin_operation(operation_id: str) -> None:
    execute_plugin_operation(operation_id)
