from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsGraphDefinitionOwnerOrStaff(BasePermission):
    """Require authentication and keep private graph definitions owner-scoped."""

    message = "Graph definitions are accessible only to their owner or staff."

    def has_permission(self, request, view) -> bool:
        return bool(getattr(request.user, "is_authenticated", False))

    def has_object_permission(self, request, view, graph_definition) -> bool:
        if request.method in SAFE_METHODS:
            return graph_definition.can_view(request.user)
        return graph_definition.can_change(request.user)


class IsLogicalEndpointOwnerOrStaff(BasePermission):
    """Keep logical endpoint reads and writes scoped to their owner or staff."""

    message = "Logical endpoints are accessible only to their owner or staff."

    def has_permission(self, request, view) -> bool:
        return bool(getattr(request.user, "is_authenticated", False))

    def has_object_permission(self, request, view, endpoint) -> bool:
        if request.method in SAFE_METHODS:
            return endpoint.can_view(request.user)
        return endpoint.can_change(request.user)
