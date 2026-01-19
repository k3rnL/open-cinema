import json
from typing import Any

from django.apps import apps
from django.db import models
from django.db.models.fields import Field
from django.http import JsonResponse
from rest_framework import serializers
from rest_framework.views import APIView

from api.models import AudioPipelineNode


class NodeSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    type_name = serializers.CharField(required=True, max_length=255)
    fields = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        required=False,
        default=dict
    )

    def validate_type_name(self, value):
        """Validate that the type_name corresponds to a valid model."""
        cls = find_model_by_name(value)
        if cls is None:
            raise serializers.ValidationError(
                f'Invalid type_name: {value}. No matching model found.'
            )
        return value

    def validate(self, data):
        """Validate field types if present for the specific node type."""
        type_name = data.get('type_name')
        fields_data = data.get('fields', {})

        if type_name and fields_data:
            cls = find_model_by_name(type_name)
            if cls:
                # Validate fields presence
                for field in cls.get_exposed_fields():
                    if '_ptr' in field.name:
                        continue
                    if not field.null and not field.blank and field.default == models.NOT_PROVIDED:
                        if field.name not in fields_data and field.name not in ['id', 'type_name']:
                            raise serializers.ValidationError(
                                f'Field "{field.name}" is required for type {type_name}'
                            )
                # Validate types of provided fields
                for field_name, field_value in fields_data.items():
                    try:
                        field = cls._meta.get_field(field_name)

                        # Skip validation if value is None and field allows null
                        if field_value is None:
                            if not field.null:
                                raise serializers.ValidationError(
                                    f'Field "{field_name}" does not allow null values'
                                )
                            continue

                        # Type validation based on field type
                        if isinstance(field, models.IntegerField):
                            if not isinstance(field_value, int):
                                raise serializers.ValidationError(
                                    f'Field "{field_name}" must be an integer, got {type(field_value).__name__}'
                                )
                        elif isinstance(field, models.FloatField):
                            if not isinstance(field_value, (int, float)):
                                raise serializers.ValidationError(
                                    f'Field "{field_name}" must be a number, got {type(field_value).__name__}'
                                )
                        elif isinstance(field, models.BooleanField):
                            if not isinstance(field_value, bool):
                                raise serializers.ValidationError(
                                    f'Field "{field_name}" must be a boolean, got {type(field_value).__name__}'
                                )
                        elif isinstance(field, (models.CharField, models.TextField)):
                            if not isinstance(field_value, str):
                                raise serializers.ValidationError(
                                    f'Field "{field_name}" must be a string, got {type(field_value).__name__}'
                                )
                            # Check max_length for CharField
                            if isinstance(field, models.CharField) and field.max_length:
                                if len(field_value) > field.max_length:
                                    raise serializers.ValidationError(
                                        f'Field "{field_name}" max length is {field.max_length}, got {len(field_value)}'
                                    )
                        elif field.is_relation:
                            # For foreign keys, check if the ID is an integer
                            if not isinstance(field_value, int):
                                raise serializers.ValidationError(
                                    f'Field "{field_name}" (foreign key) must be an integer ID, got {type(field_value).__name__}'
                                )

                    except Exception as e:
                        if isinstance(e, serializers.ValidationError):
                            raise
                        raise serializers.ValidationError(
                            f'Field "{field_name}" does not exist for type {type_name}'
                        )

        return data


def recursive_subclasses[T](cls: type[T]) -> set[type[T]]:
    """
    Recursively finds all subclasses of a given class.
    """
    return set.union({cls}, *map(recursive_subclasses, cls.__subclasses__()))


def find_model_by_name(name: str) -> type[AudioPipelineNode] | None:
    for model in apps.get_models():
        if model.__name__ == name:
            return model
    return None


def fill_model_from_json(node: AudioPipelineNode, data: dict[str, Any]) -> None:
    fields = node.get_exposed_fields()
    for field in fields:
        if '_ptr' in field.name:
            continue
        if field.name in data['fields']:
            if field.is_relation:
                try:
                    relation_instance = field.remote_field.model.objects.get(id=data['fields'][field.name])
                    setattr(node, field.name, relation_instance)
                except field.remote_field.model.DoesNotExist:
                    raise ReferenceError(
                        f'Relation {field.name} with ID {data["fields"][field.name]} does not exist')
            else:
                setattr(node, field.name, data['fields'][field.name])


def node_to_json(node: AudioPipelineNode) -> dict[str, Any]:
    return {
        'id': node.id,
        'type_name': node.__class__.__name__,
        'slots': [slot.to_dict() for slot in node.slots.all()],
        'fields': get_fields_value(node, node.get_exposed_fields())
    }


def json_node_to_model(data_node) -> AudioPipelineNode:
    class_name = data_node['type_name']

    # Search through all registered models to find the matching class
    cls = find_model_by_name(class_name)

    if cls is None:
        raise ReferenceError(f'Class {class_name} not found in registered Django models')

    node = cls()
    node.type_name = class_name
    fill_model_from_json(node, data_node)

    return node


def get_fields_value(node: AudioPipelineNode, fields: list[Field]) -> dict[str, Any]:
    result = {}

    for field in fields:
        if '_ptr' in field.name:
            continue
        if field.is_relation:
            value = getattr(node, field.name)
            if value is not None:
                result[field.name] = getattr(value, field.remote_field.field_name)
        else:
            result[field.name] = getattr(node, field.name)

    return result


def get_concrete_node(node: AudioPipelineNode) -> AudioPipelineNode:
    """Get the concrete subclass instance from a base AudioPipelineNode."""
    # Find all subclass names by checking for related objects
    for subclass in recursive_subclasses(AudioPipelineNode):
        if subclass == AudioPipelineNode:
            continue
        # Get the related name (lowercase class name + '_ptr')
        related_name = subclass.__name__.lower()
        if hasattr(node, related_name):
            return getattr(node, related_name)
    return node


def update_slots(node: AudioPipelineNode) -> None:
    slots = {s.name: s for s in node.get_manager().get_dynamic_slots_schematics()}
    existing_slots = {s.name: s for s in node.slots.all()}

    # Delete slots that are not in the generated list
    for slot in existing_slots.values():
        if slot.name not in slots:
            slot.delete()

    # Add slots that are not in the database yet
    for slot in slots.values():
        if slot.name not in existing_slots:
            slot.save()


class AudioPipelineNodeList(APIView):

    def get(self, request, pipeline_id):
        nodes = AudioPipelineNode.objects.filter(pipeline_id=pipeline_id).all()
        data = [node_to_json(node) for node in nodes]

        return JsonResponse(data, safe=False)

    def post(self, request, pipeline_id):
        node_json = json.loads(request.body)

        serializer = NodeSerializer(data=node_json)
        if not serializer.is_valid():
            return JsonResponse({'errors': serializer.errors}, status=400)

        node_model = json_node_to_model(serializer.validated_data)
        node_model.pipeline_id = pipeline_id
        node_model.save()
        update_slots(node_model)

        data = node_to_json(node_model)

        return JsonResponse(data, safe=False, status=201)


class AudioPipelineNodeDetail(APIView):
    def get(self, request, pipeline_id, node_id):
        try:
            base_node = AudioPipelineNode.objects.get(id=node_id)
            cls = find_model_by_name(base_node.type_name)
            node = cls.objects.get(id=node_id)
            data = node_to_json(node)
        except AudioPipelineNode.DoesNotExist:
            return JsonResponse({'error': 'Node not found'}, status=404)

        return JsonResponse(data, safe=False)

    def patch(self, request, pipeline_id, node_id):
        node_json = json.loads(request.body)

        serializer = NodeSerializer(data=node_json, partial=True)
        if not serializer.is_valid():
            return JsonResponse({'errors': serializer.errors}, status=400)

        validated = serializer.validated_data
        cls = find_model_by_name(validated['type_name'])
        node_model = cls.objects.get(id=node_id)

        fill_model_from_json(node_model, validated)

        node_model.save()
        update_slots(node_model)

        data = node_to_json(node_model)

        return JsonResponse(data, safe=False, status=200)

    def delete(self, request, pipeline_id, node_id):
        try:
            node = AudioPipelineNode.objects.get(id=node_id)
        except AudioPipelineNode.DoesNotExist:
            return JsonResponse({'error': 'Node not found'}, status=404)

        node.delete()
        return JsonResponse({}, status=204)
