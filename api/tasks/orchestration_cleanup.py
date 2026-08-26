from celery import shared_task

from core.orchestration.retention import cleanup_orchestration_data


@shared_task(name="api.cleanup_audio_orchestration_data")
def cleanup_audio_orchestration_data() -> dict[str, int]:
    return cleanup_orchestration_data().as_dict()
