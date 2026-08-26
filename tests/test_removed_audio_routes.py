import pytest


@pytest.mark.parametrize(
    "path",
    (
        "/api/devices",
        "/api/pipelines",
        "/api/preferences/audio-backends",
        "/api/camilladsp/pipelines",
    ),
)
def test_removed_audio_routes_have_no_compatibility_handler(client, path):
    assert client.get(path).status_code == 404
