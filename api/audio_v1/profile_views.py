from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.response import Response

from api.models import CamillaDSPProfile

from .base import AudioAPIProblem, AudioV1APIView, paginated, require_object
from .representations import camilladsp_profile_document


def _profile_for(request, revision_id):
    return CamillaDSPProfile.objects.visible_to(request.user).get(pk=revision_id)


def _profile_id(value: object) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as error:
        raise AudioAPIProblem(
            status.HTTP_400_BAD_REQUEST,
            "invalid-profile-id",
            "Invalid CamillaDSP profile ID",
            "profileId must be a UUID identifying an existing profile lineage.",
        ) from error


class CamillaDSPProfileListView(AudioV1APIView):
    def get(self, request):
        queryset = CamillaDSPProfile.objects.visible_to(request.user).select_related("owner")
        lineage = _profile_id(request.query_params.get("profileId"))
        if lineage is not None:
            queryset = queryset.filter(profile_id=lineage)
        elif request.query_params.get("allVersions", "false").lower() != "true":
            queryset = queryset.latest_versions()
        queryset = queryset.order_by("name", "profile_id", "-version")
        return paginated(
            request,
            queryset,
            lambda item: camilladsp_profile_document(item, include_content=True),
        )

    def post(self, request):
        body = require_object(request.data)
        unknown = set(body) - {"profileId", "name", "description", "content"}
        if unknown:
            raise AudioAPIProblem(
                status.HTTP_400_BAD_REQUEST,
                "unknown-fields",
                "Unknown fields",
                f"Unsupported CamillaDSP profile fields: {', '.join(sorted(unknown))}.",
            )
        content = require_object(body.get("content"), field="content")
        lineage = _profile_id(body.get("profileId"))
        requested_name = body.get("name")
        if requested_name is not None and (
            not isinstance(requested_name, str) or not requested_name.strip()
        ):
            raise AudioAPIProblem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "profile-name-invalid",
                "CamillaDSP profile name invalid",
                "name must be a non-empty string.",
            )
        try:
            with transaction.atomic():
                if lineage is None:
                    profile = CamillaDSPProfile(
                        version=1,
                        owner=request.user,
                        name=body.get("name", ""),
                        description=body.get("description", ""),
                        content=dict(content),
                    )
                else:
                    latest = (
                        CamillaDSPProfile.objects.visible_to(request.user)
                        .select_for_update()
                        .filter(profile_id=lineage)
                        .order_by("-version")
                        .first()
                    )
                    if latest is None:
                        raise AudioAPIProblem(
                            status.HTTP_404_NOT_FOUND,
                            "profile-not-found",
                            "CamillaDSP profile not found",
                            "The requested profile lineage is not visible to this user.",
                        )
                    profile = latest.new_version(
                        content=dict(content),
                        author=request.user,
                        name=body.get("name", latest.name),
                        description=body.get("description", latest.description),
                    )
                profile.save()
        except IntegrityError as error:
            raise AudioAPIProblem(
                status.HTTP_409_CONFLICT,
                "profile-version-conflict",
                "CamillaDSP profile changed",
                "A competing request created the next profile version.",
            ) from error
        response = Response(
            camilladsp_profile_document(profile),
            status=status.HTTP_201_CREATED,
        )
        response["Location"] = f"/api/audio/v1/camilladsp/profiles/{profile.pk}"
        return response


class CamillaDSPProfileDetailView(AudioV1APIView):
    def get(self, request, revision_id):
        return Response(camilladsp_profile_document(_profile_for(request, revision_id)))
