import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json

from api.models import Pipeline, KnownAudioDevice
from core.camilladsp import CamillaDSPManager

logger = logging.getLogger(__name__)


@require_http_methods(["GET"])
def list_pipelines(request):
    """List all pipelines."""
    pipelines = Pipeline.objects.all()

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
            'enabled': p.enabled,
            'active': p.active,
            'created_at': p.created_at.isoformat(),
            'updated_at': p.updated_at.isoformat()
        }
        for p in pipelines
    ]

    return JsonResponse(pipelines_data, safe=False)


@require_http_methods(["GET"])
def get_pipeline(request, pipeline_id):
    """Get details of a specific pipeline."""
    try:
        pipeline = Pipeline.objects.get(id=pipeline_id)

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
            'enabled': pipeline.enabled,
            'active': pipeline.active,
            'created_at': pipeline.created_at.isoformat(),
            'updated_at': pipeline.updated_at.isoformat()
        }

        return JsonResponse(pipeline_data)

    except Pipeline.DoesNotExist:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)


@csrf_exempt
@require_http_methods(["POST"])
def create_pipeline(request):
    """Create a new pipeline."""
    try:
        data = json.loads(request.body)

        # Validate required fields
        required_fields = ['name', 'input_device_id', 'output_device_id']
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

        # Create pipeline
        pipeline = Pipeline.objects.create(
            name=data['name'],
            description=data.get('description', ''),
            input_device=input_device,
            output_device=output_device,
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


@csrf_exempt
@require_http_methods(["PUT"])
def update_pipeline(request, pipeline_id):
    """Update an existing pipeline."""
    try:
        pipeline = Pipeline.objects.get(id=pipeline_id)
        data = json.loads(request.body)

        # Update fields if provided
        if 'name' in data:
            pipeline.name = data['name']
        if 'description' in data:
            pipeline.description = data['description']
        if 'enabled' in data:
            pipeline.enabled = data['enabled']

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

    except Pipeline.DoesNotExist:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)
    except KnownAudioDevice.DoesNotExist:
        return JsonResponse({'error': 'Invalid device ID'}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error updating pipeline: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["DELETE"])
def delete_pipeline(request, pipeline_id):
    """Delete a pipeline."""
    try:
        pipeline = Pipeline.objects.get(id=pipeline_id)

        if pipeline.active:
            return JsonResponse(
                {'error': 'Cannot delete active pipeline. Deactivate it first.'},
                status=400
            )

        pipeline.delete()
        return JsonResponse({'message': 'Pipeline deleted successfully'})

    except Pipeline.DoesNotExist:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)
    except Exception as e:
        logger.error(f"Error deleting pipeline: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def activate_pipeline(request, pipeline_id):
    """Activate a pipeline."""
    try:
        pipeline = Pipeline.objects.get(id=pipeline_id)

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

    except Pipeline.DoesNotExist:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)
    except Exception as e:
        logger.error(f"Error activating pipeline: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def deactivate_pipeline(request, pipeline_id):
    """Deactivate a pipeline."""
    try:
        pipeline = Pipeline.objects.get(id=pipeline_id)

        manager = CamillaDSPManager()
        success, message = manager.deactivate_pipeline(pipeline)

        if success:
            return JsonResponse({'message': message})
        else:
            return JsonResponse({'error': message}, status=400)

    except Pipeline.DoesNotExist:
        return JsonResponse({'error': 'Pipeline not found'}, status=404)
    except Exception as e:
        logger.error(f"Error deactivating pipeline: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)
