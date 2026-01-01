import logging
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from api.models import Mixer

logger = logging.getLogger(__name__)


@csrf_exempt
def mixers(request):
    """Handle GET (list) and POST (create) for mixers collection."""
    if request.method == "GET":
        return list_mixers(request)
    elif request.method == "POST":
        return create_mixer(request)
    else:
        return JsonResponse({'error': 'Method not allowed'}, status=405)


@require_http_methods(["GET"])
def list_mixers(request):
    """List all mixers."""
    mixers = Mixer.objects.all()

    mixers_data = [
        {
            'id': m.id,
            'name': m.name,
            'description': m.description,
            'input_channels': m.input_channels,
            'output_channels': m.output_channels,
            'mapping': m.mapping,
            'created_at': m.created_at.isoformat(),
            'updated_at': m.updated_at.isoformat()
        }
        for m in mixers
    ]

    return JsonResponse(mixers_data, safe=False)


@csrf_exempt
def mixer_detail(request, mixer_id):
    """Handle GET, PUT, PATCH, DELETE for a specific mixer."""
    if request.method == "GET":
        return get_mixer(request, mixer_id)
    elif request.method in ["PUT", "PATCH"]:
        return update_mixer(request, mixer_id)
    elif request.method == "DELETE":
        return delete_mixer(request, mixer_id)
    else:
        return JsonResponse({'error': 'Method not allowed'}, status=405)


@require_http_methods(["GET"])
def get_mixer(request, mixer_id):
    """Get details of a specific mixer."""
    try:
        mixer = Mixer.objects.get(id=mixer_id)

        mixer_data = {
            'id': mixer.id,
            'name': mixer.name,
            'description': mixer.description,
            'input_channels': mixer.input_channels,
            'output_channels': mixer.output_channels,
            'mapping': mixer.mapping,
            'created_at': mixer.created_at.isoformat(),
            'updated_at': mixer.updated_at.isoformat()
        }

        return JsonResponse(mixer_data)

    except Mixer.DoesNotExist:
        return JsonResponse({'error': 'Mixer not found'}, status=404)


@require_http_methods(["POST"])
def create_mixer(request):
    """Create a new mixer."""
    try:
        data = json.loads(request.body)

        # Validate required fields
        required_fields = ['name', 'input_channels', 'output_channels', 'mapping']
        for field in required_fields:
            if field not in data:
                return JsonResponse({'error': f'Missing required field: {field}'}, status=400)

        # Check if mixer with this name already exists
        if Mixer.objects.filter(name=data['name']).exists():
            return JsonResponse({'error': f"Mixer with name '{data['name']}' already exists"}, status=400)

        # Create mixer
        mixer = Mixer.objects.create(
            name=data['name'],
            description=data.get('description', ''),
            input_channels=data['input_channels'],
            output_channels=data['output_channels'],
            mapping=data['mapping']
        )

        return JsonResponse({
            'id': mixer.id,
            'name': mixer.name,
            'message': 'Mixer created successfully'
        }, status=201)

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error creating mixer: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["PUT", "PATCH"])
def update_mixer(request, mixer_id):
    """Update an existing mixer."""
    try:
        mixer = Mixer.objects.get(id=mixer_id)
        data = json.loads(request.body)

        # Update fields if provided
        if 'name' in data:
            # Check if new name conflicts with another mixer
            if Mixer.objects.filter(name=data['name']).exclude(id=mixer_id).exists():
                return JsonResponse({'error': f"Mixer with name '{data['name']}' already exists"}, status=400)
            mixer.name = data['name']

        if 'description' in data:
            mixer.description = data['description']

        if 'input_channels' in data:
            mixer.input_channels = data['input_channels']

        if 'output_channels' in data:
            mixer.output_channels = data['output_channels']

        if 'mapping' in data:
            mixer.mapping = data['mapping']

        mixer.save()

        return JsonResponse({
            'id': mixer.id,
            'name': mixer.name,
            'message': 'Mixer updated successfully'
        })

    except Mixer.DoesNotExist:
        return JsonResponse({'error': 'Mixer not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error updating mixer: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["DELETE"])
def delete_mixer(request, mixer_id):
    """Delete a mixer."""
    try:
        mixer = Mixer.objects.get(id=mixer_id)

        # Check if mixer is used by any pipelines
        if mixer.pipelines.exists():
            pipeline_names = ', '.join([p.name for p in mixer.pipelines.all()])
            return JsonResponse(
                {'error': f'Cannot delete mixer. It is used by pipelines: {pipeline_names}'},
                status=400
            )

        mixer.delete()
        return JsonResponse({'message': 'Mixer deleted successfully'})

    except Mixer.DoesNotExist:
        return JsonResponse({'error': 'Mixer not found'}, status=404)
    except Exception as e:
        logger.error(f"Error deleting mixer: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)
