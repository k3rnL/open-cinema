from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.response import Response

from .base import AudioV1APIView
from .catalogue import catalogue_items
from .schemas import api_json_schemas, openapi_document, schema_metadata


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SchemaMetadataView(AudioV1APIView):
    """Return the contract metadata and bootstrap browser CSRF protection."""

    def get(self, request):
        return Response(schema_metadata())


class JSONSchemasView(AudioV1APIView):
    def get(self, request):
        return Response(
            {
                "apiVersion": 1,
                "schemas": api_json_schemas(),
            }
        )


class OpenAPIView(AudioV1APIView):
    def get(self, request):
        return Response(openapi_document())


class NodeTypeCatalogueView(AudioV1APIView):
    def get(self, request):
        source = request.query_params.get("source")
        category = request.query_params.get("category")
        items = catalogue_items()
        if source:
            items = [item for item in items if item["source"] == source]
        if category:
            items = [item for item in items if item["category"] == category]
        return Response(
            {
                "schemaVersion": 1,
                "items": items,
            }
        )
