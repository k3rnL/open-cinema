from abc import ABC, abstractmethod
from typing import NamedTuple, Any

from api.models import AudioPipelineNode
from api.models.audio.pipeline.audio_pipeline_apply_event import AudioPipelineApplyEvent, EventType
from api.models.audio.pipeline.audio_pipeline_apply_job import AudioPipelineApplyJob, JobStatus


class PipelineJobEventData(NamedTuple):
    graph_errors: list[str] = list()
    node_errors: list[str] = list()

    def to_dict(self) -> dict:
        return self._asdict()


def job_log_success_event(job: AudioPipelineApplyJob):
    AudioPipelineApplyEvent(
        job_id=job.id,
        event_type=EventType.SUCCESS
    ).save()
    job.status = JobStatus.SUCCESS
    job.save()


def job_log_node_start_event(job: AudioPipelineApplyJob, node: AudioPipelineNode):
    AudioPipelineApplyEvent(
        job_id=job.id,
        node=node,
        event_type=EventType.STARTED_NODE
    ).save()
    job.status = JobStatus.RUNNING
    job.save()


def job_log_failure_event(job: AudioPipelineApplyJob, data: PipelineJobEventData):
    AudioPipelineApplyEvent(
        job_id=job.id,
        event_type=EventType.FAILURE,
        data=data.to_dict()
    ).save()
    job.status = JobStatus.FAILED
    job.save()


def job_log_failure_node_event(job: AudioPipelineApplyJob, node: AudioPipelineNode, data: PipelineJobEventData):
    AudioPipelineApplyEvent(
        job_id=job.id,
        node=node,
        event_type=EventType.FAILURE,
        data=data.to_dict()
    ).save()
    job.status = JobStatus.FAILED
    job.save()


def job_log_completed_node_event(job: AudioPipelineApplyJob, node_id: int):
    AudioPipelineApplyEvent(
        job=job,
        event_type=EventType.COMPLETED_NODE,
        node_id=node_id
    ).save()
