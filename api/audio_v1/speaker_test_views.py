from __future__ import annotations

from functools import lru_cache

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from core.orchestration.speaker_test import (
    DEFAULT_RUNTIME_DIRECTORY,
    SpeakerTestController,
    SpeakerTestInvalidChannel,
    SpeakerTestUnavailable,
    discover_speaker_test_outputs,
)

from .base import AudioAPIProblem, AudioV1APIView, require_object


@lru_cache(maxsize=1)
def speaker_test_controller() -> SpeakerTestController:
    return SpeakerTestController(
        runtime_directory=getattr(
            settings,
            "SPEAKER_TEST_RUNTIME_DIRECTORY",
            DEFAULT_RUNTIME_DIRECTORY,
        )
    )


def _outputs():
    return discover_speaker_test_outputs()


class SpeakerTestView(AudioV1APIView):
    permission_classes = (IsAdminUser,)

    def get(self, request):
        return Response(
            {
                "outputs": [output.to_document() for output in _outputs()],
                "active": speaker_test_controller().status(),
            }
        )

    def post(self, request):
        body = require_object(request.data)
        runtime_key = body.get("runtimeKey")
        channel = body.get("channel")
        if not isinstance(runtime_key, str) or not runtime_key:
            raise AudioAPIProblem(
                status.HTTP_400_BAD_REQUEST,
                "speaker-test-runtime-key-required",
                "Output required",
                "runtimeKey must identify one output from the current speaker-test inventory.",
            )
        if not isinstance(channel, str) or not channel:
            raise AudioAPIProblem(
                status.HTTP_400_BAD_REQUEST,
                "speaker-test-channel-required",
                "Channel required",
                "channel must identify one observed output position.",
            )
        output = next((item for item in _outputs() if item.runtime_key == runtime_key), None)
        if output is None:
            raise AudioAPIProblem(
                status.HTTP_409_CONFLICT,
                "speaker-test-output-stale",
                "Output changed",
                "The selected output is no longer current or testable. Refresh the output list.",
            )
        try:
            document = speaker_test_controller().start(output, channel)
        except SpeakerTestInvalidChannel as error:
            raise AudioAPIProblem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "speaker-test-channel-invalid",
                "Channel unavailable",
                str(error),
            ) from error
        except (OSError, SpeakerTestUnavailable) as error:
            raise AudioAPIProblem(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "speaker-test-start-failed",
                "Speaker test unavailable",
                str(error),
            ) from error
        return Response(document, status=status.HTTP_202_ACCEPTED)

    def delete(self, request):
        return Response(speaker_test_controller().stop())
