from time import sleep

from celery import shared_task

from api.models.audio.audio_pipeline import AudioPipeline
from api.models.audio.pipeline.audio_pipeline_apply_job import AudioPipelineApplyJob, JobStatus
from core.audio.pipeline.audio_pipeline_graph import AudioPipelineGraph, AudioPipelineGraphNode
from core.audio.pipeline.audio_pipeline_job_utils import job_log_success_event, job_log_failure_event, PipelineJobEventData, \
    job_log_failure_node_event, job_log_node_start_event, job_log_completed_node_event


@shared_task(bind=True)
def apply_audio_pipeline(self, pipeline_id: int, job_id: int):
    job = AudioPipelineApplyJob.objects.get(id=job_id)
    pipeline = AudioPipeline.objects.get(id=pipeline_id)
    graph = AudioPipelineGraph(pipeline)

    job.status = JobStatus.RUNNING
    job.save()
    roots = graph.get_roots()
    if len(roots) == 0:
        job_log_success_event(job)
        return 0
    if len(roots) > 1:
        job_log_failure_event(job, PipelineJobEventData(graph_errors=['Multiple roots found']))
        return 0

    root = roots[0]
    to_process: list[AudioPipelineGraphNode] = [root]
    while len(to_process) > 0:
        node = to_process.pop(0)
        job_log_node_start_event(job, node.data)
        to_process.extend([edge.to_node for edge in node.outgoing])
        try:
            node.data.get_manager().apply(node, graph)
            job_log_completed_node_event(job, node.data.id)
        except Exception as e:
            job_log_failure_node_event(job, node.data, PipelineJobEventData(node_errors=[str(e)]))
            pipeline.stale = True
            pipeline.save()
            return None
    job_log_success_event(job)
    pipeline.active = True
    pipeline.stale = False
    pipeline.save()

    return None


@shared_task(bind=True)
def unapply_audio_pipeline(self, pipeline_id: int, job_id: int):
    job = AudioPipelineApplyJob.objects.get(id=job_id)
    pipeline = AudioPipeline.objects.get(id=pipeline_id)
    graph = AudioPipelineGraph(pipeline)

    job.status = JobStatus.RUNNING
    job.save()
    roots = graph.get_roots()
    if len(roots) == 0:
        job_log_success_event(job)
        return 0
    if len(roots) > 1:
        job_log_failure_event(job, PipelineJobEventData(graph_errors=['Multiple roots found']))
        return 0

    root = roots[0]
    to_process: list[AudioPipelineGraphNode] = [root]
    while len(to_process) > 0:
        node = to_process.pop(0)
        job_log_node_start_event(job, node.data)
        to_process.extend([edge.to_node for edge in node.outgoing])
        try:
            node.data.get_manager().unapply(node, graph)
            job_log_completed_node_event(job, node.data.id)
        except Exception as e:
            job_log_failure_node_event(job, node.data, PipelineJobEventData(node_errors=[f'Error unapplying node: {str(e)}']))
            pipeline.stale = True
            pipeline.save()
            return None
    job_log_success_event(job)
    pipeline.active = False
    pipeline.stale = False
    pipeline.save()

    return None
