import logging

import yaml
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json

from api.models import CamillaDSPPipeline, KnownAudioDevice
from core.camilladsp import CamillaDSPManager

logger = logging.getLogger(__name__)


@csrf_exempt
def pipelines(request):
    """Handle GET (list) and POST (create) for pipelines collection."""
    if request.method == "GET":
        return list_pipelines(request)
    elif request.method == "POST":
        return create_pipeline(request)
    else:
        return JsonResponse({'error': 'Method not allowed'}, status=405)


@require_http_methods(["GET"])
def list_pipelines(request):
    """List all pipelines."""
    pipelines = CamillaDSPPipeline.objects.all()

    pipelines_data = [
        {
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'input_device': {
                'id': p.input_device.id,
                'name': p.input_device.name,
                'active': p.input_device.active
            },
            'output_device': {
                'id': p.output_device.id,
                'name': p.output_device.name,
                'active': p.output_device.active
            },
            'samplerate': p.samplerate,
            'chunksize': p.chunksize,
            'mixer': {
                'id': p.mixer.id,
                'name': p.mixer.name,
                'input_channels': p.mixer.input_channels,
                'output_channels': p.mixer.output_channels
            } if p.mixer else None,
            'enabled': p.enabled,
            'active': p.active,
            'created_at': p.created_at.isoformat(),
            'updated_at': p.updated_at.isoformat()
        }
        for p in pipelines
    ]

    return JsonResponse(pipelines_data, safe=False)


@csrf_exempt
def pipeline_detail(request, pipeline_id):
    """Handle GET, PUT, DELETE for a specific pipeline."""
    if request.method == "GET":
        return get_pipeline(request, pipeline_id)
    elif request.method == "PUT":
        return update_pipeline(request, pipeline_id)
    elif request.method == "DELETE":
        return delete_pipeline(request, pipeline_id)
    else:
        return JsonResponse({'error': 'Method not allowed'}, status=405)


@require_http_methods(["GET"])
def get_pipeline(request, pipeline_id):
    """Get details of a specific pipeline."""
    try:
        pipeline = CamillaDSPPipeline.objects.get(id=pipeline_id)

        pipeline_data = {
            'id': pipeline.id,
            'name': pipeline.name,
            'description': pipeline.description,
            'input_device': {
                'id': pipeline.input_device.id,
                'name': pipeline.input_device.name,
                'backend': pipeline.input_device.backend,
                'device_type': pipeline.input_device.device_type,
                'format': pipeline.input_device.format,
                'sample_rate': pipeline.input_device.sample_rate,
                'channels': pipeline.input_device.channels,
                'active': pipeline.input_device.active
            },
            'output_device': {
                'id': pipeline.output_device.id,
                'name': pipeline.output_device.name,
                'backend': pipeline.output_device.backend,
                'device_type': pipeline.output_device.device_type,
                'format': pipeline.output_device.format,
                'sample_rate': pipeline.output_device.sample_rate,
                'channels': pipeline.output_device.channels,
                'active': pipeline.output_device.active
            },
            'filters': [
                {
                    'id': f.id,
                    'filter_type': f.filter_type,
                    'order': f.order,
                    'config': f.config,
                    'enabled': f.enabled
                }
                for f in pipeline.filters.all()
            ],
            'samplerate': pipeline.samplerate,
            'chunksize': pipeline.chunksize,
            'mixer': {
                'id': pipeline.mixer.id,
                'name': pipeline.mixer.name,
                'input_channels': pipeline.mixer.input_channels,
                'output_channels': pipeline.mixer.output_channels
            } if pipeline.mixer else None,
            'enabled': pipeline.enabled,
            'active': pipeline.active,
            'created_at': pipeline.created_at.isoformat(),
            'updated_at': pipeline.updated_at.isoformat()
        }

        return JsonResponse(pipeline_data)

    except CamillaDSPPipeline.DoesNotExist:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)

@require_http_methods(["GET"])
def get_yaml_pipeline(request, pipeline_id):
    try:
        pipeline = CamillaDSPPipeline.objects.get(id=pipeline_id)
        manager = CamillaDSPManager()
        config_dict = manager.get_config_for_pipeline(pipeline)
        if config_dict is None:
            return JsonResponse({'error': 'Failed to generate config for pipeline'}, status=500)
        config_yaml = yaml.dump(config_dict, default_flow_style=False, sort_keys=False)
        return JsonResponse({'yaml': config_yaml})
    except CamillaDSPPipeline.DoesNotExist:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)

@require_http_methods(["POST"])
def create_pipeline(request):
    """Create a new pipeline."""
    try:
        data = json.loads(request.body)

        # Validate required fields
        required_fields = ['name', 'input_device_id', 'output_device_id', 'samplerate']
        for field in required_fields:
            if field not in data:
                return JsonResponse({'error': f'Missing required field: {field}'}, status=400)

        # Get devices
        try:
            input_device = KnownAudioDevice.objects.get(id=data['input_device_id'])
            output_device = KnownAudioDevice.objects.get(id=data['output_device_id'])
        except KnownAudioDevice.DoesNotExist:
            return JsonResponse({'error': 'Invalid device ID'}, status=400)

        # Validate device types
        if input_device.device_type != 'CAPTURE':
            return JsonResponse({'error': f'Input device must be a CAPTURE device (actual: {input_device.device_type})'}, status=400)

        if output_device.device_type != 'PLAYBACK':
            return JsonResponse({'error': f'Output device must be a PLAYBACK device (actual: {output_device.device_type})'}, status=400)

        # Create or get mixer if channels differ
        mixer = None
        if input_device.channels != output_device.channels:
            from api.models import Mixer
            mixer_name = f"auto_{input_device.channels}ch_to_{output_device.channels}ch"
            mixer = Mixer.objects.filter(name=mixer_name).first()

            if not mixer:
                # Create default mixer
                mixer = Mixer.create_default_mixer(input_device.channels, output_device.channels)
                mixer.save()

        # Create pipeline
        pipeline = CamillaDSPPipeline.objects.create(
            name=data['name'],
            description=data.get('description', ''),
            input_device=input_device,
            output_device=output_device,
            samplerate=data['samplerate'],
            chunksize=data.get('chunksize', 1024),
            mixer=mixer,
            enabled=data.get('enabled', True)
        )

        return JsonResponse({
            'id': pipeline.id,
            'name': pipeline.name,
            'message': 'Pipeline created successfully'
        }, status=201)

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error creating pipeline: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["PUT"])
def update_pipeline(request, pipeline_id):
    """Update an existing pipeline."""
    try:
        pipeline = CamillaDSPPipeline.objects.get(id=pipeline_id)
        data = json.loads(request.body)

        # Update fields if provided
        if 'name' in data:
            pipeline.name = data['name']
        if 'description' in data:
            pipeline.description = data['description']
        if 'enabled' in data:
            pipeline.enabled = data['enabled']
        if 'samplerate' in data:
            pipeline.samplerate = data['samplerate']
        if 'chunksize' in data:
            pipeline.chunksize = data['chunksize']

        if 'mixer_id' in data:
            from api.models import Mixer
            if data['mixer_id'] is None:
                pipeline.mixer = None
            else:
                try:
                    mixer = Mixer.objects.get(id=data['mixer_id'])
                    # Validate mixer channels match devices
                    if mixer.input_channels != pipeline.input_device.channels:
                        return JsonResponse({
                            'error': f'Mixer input channels ({mixer.input_channels}) must match input device channels ({pipeline.input_device.channels})'
                        }, status=400)
                    if mixer.output_channels != pipeline.output_device.channels:
                        return JsonResponse({
                            'error': f'Mixer output channels ({mixer.output_channels}) must match output device channels ({pipeline.output_device.channels})'
                        }, status=400)
                    pipeline.mixer = mixer
                except Mixer.DoesNotExist:
                    return JsonResponse({'error': 'Invalid mixer ID'}, status=400)

        if 'input_device_id' in data:
            input_device = KnownAudioDevice.objects.get(id=data['input_device_id'])
            if input_device.device_type != 'CAPTURE':
                return JsonResponse({'error': f'Input device must be a CAPTURE device (actual: {input_device.device_type})'}, status=400)
            pipeline.input_device = input_device

        if 'output_device_id' in data:
            output_device = KnownAudioDevice.objects.get(id=data['output_device_id'])
            if output_device.device_type != 'PLAYBACK':
                return JsonResponse({'error': f'Output device must be a PLAYBACK device (actual: {output_device.device_type})'}, status=400)
            pipeline.output_device = output_device

        pipeline.save()

        return JsonResponse({
            'id': pipeline.id,
            'name': pipeline.name,
            'message': 'Pipeline updated successfully'
        })

    except CamillaDSPPipeline.DoesNotExist:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)
    except KnownAudioDevice.DoesNotExist:
        return JsonResponse({'error': 'Invalid device ID'}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error updating pipeline: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["DELETE"])
def delete_pipeline(request, pipeline_id):
    """Delete a pipeline."""
    try:
        pipeline = CamillaDSPPipeline.objects.get(id=pipeline_id)

        if pipeline.active:
            return JsonResponse(
                {'error': 'Cannot delete active pipeline. Deactivate it first.'},
                status=400
            )

        pipeline.delete()
        return JsonResponse({'message': 'Pipeline deleted successfully'})

    except CamillaDSPPipeline.DoesNotExist:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)
    except Exception as e:
        logger.error(f"Error deleting pipeline: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def activate_pipeline(request, pipeline_id):
    """Activate a pipeline."""
    try:
        pipeline = CamillaDSPPipeline.objects.get(id=pipeline_id)

        if not pipeline.enabled:
            return JsonResponse({'error': 'Pipeline is not enabled'}, status=400)

        manager = CamillaDSPManager()
        success, message = manager.activate_pipeline(pipeline)

        if success:
            return JsonResponse({
                'message': message,
                'pipeline_id': pipeline.id,
                'pipeline_name': pipeline.name
            })
        else:
            return JsonResponse({'error': message}, status=400)

    except CamillaDSPPipeline.DoesNotExist:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)
    except Exception as e:
        logger.error(f"Error activating pipeline: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def deactivate_pipeline(request, pipeline_id):
    """Deactivate a pipeline."""
    try:
        pipeline = CamillaDSPPipeline.objects.get(id=pipeline_id)

        manager = CamillaDSPManager()
        success, message = manager.deactivate_pipeline(pipeline)

        if success:
            return JsonResponse({'message': message})
        else:
            return JsonResponse({'error': message}, status=400)

    except CamillaDSPPipeline.DoesNotExist:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)
    except Exception as e:
        logger.error(f"Error deactivating pipeline: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)
