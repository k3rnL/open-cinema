from pathlib import Path

import yaml

MATRIX_PATH = Path(__file__).parents[1] / "deployment" / "compatibility.yml"
DEVELOPMENT_MANIFEST_PATH = Path(__file__).parents[1] / "deployment" / "development-manifest.yml"


def load_matrix() -> dict:
    with MATRIX_PATH.open(encoding="utf-8") as matrix_file:
        return yaml.safe_load(matrix_file)


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def test_platform_matrix_is_machine_readable_and_complete() -> None:
    matrix = load_matrix()
    production = matrix["platform"]["production"]

    assert matrix["schema_version"] == 1
    assert production["distribution_major_versions"]
    assert production["distribution_codenames"]
    assert production["architectures"] == ["aarch64"]
    assert production["raspberry_pi_models"] == [
        {"name": "Raspberry Pi 5 Model B", "minimum_memory_mb": 7500}
    ]
    assert "Raspberry Pi 4 Model B" in {
        model["name"] for model in matrix["platform"]["experimental"]["raspberry_pi_models"]
    }
    experimental_pi5 = next(
        model
        for model in matrix["platform"]["experimental"]["raspberry_pi_models"]
        if model["name"] == "Raspberry Pi 5 Model B"
    )
    assert experimental_pi5["maximum_memory_mb_exclusive"] == 7500

    required_components = {
        "bluez",
        "c_compiler",
        "celery",
        "django",
        "ffmpeg",
        "gunicorn",
        "make",
        "nginx",
        "pipewire",
        "pkg_config",
        "pcm_auto_decoder",
        "pycamilladsp",
        "redis",
        "sqlite",
        "wireplumber",
        "wyreplumber",
        "camilladsp",
        "python",
        "rust",
        "node",
        "uv",
    }
    assert set(matrix["components"]) == required_components


def test_every_bounded_component_range_is_ordered() -> None:
    for component in load_matrix()["components"].values():
        if "maximum_exclusive" in component:
            assert version_tuple(component["minimum"]) < version_tuple(
                component["maximum_exclusive"]
            )


def test_production_matrix_selects_one_wireplumber_api_family() -> None:
    wireplumber = load_matrix()["components"]["wireplumber"]

    assert wireplumber["api_family"] == "0.5"
    assert wireplumber["pkg_config"] == "wireplumber-0.5"
    assert version_tuple(wireplumber["minimum"]) >= (0, 5)
    assert version_tuple(wireplumber["maximum_exclusive"]) <= (0, 6, 0)


def test_selected_processors_are_native_pipewire_contracts() -> None:
    matrix = load_matrix()

    assert matrix["components"]["wyreplumber"]["minimum"] == "0.2.0"
    assert matrix["components"]["camilladsp"]["backend"] == "pipewire"
    assert matrix["components"]["pcm_auto_decoder"]["backend"] == "pipewire"
    assert matrix["components"]["pcm_auto_decoder"]["minimum"] == "0.2.2"
    assert matrix["components"]["pcm_auto_decoder"]["status_protocol"] == 2
    assert matrix["processor_policy"]["decoder_transport"] == "pipewire-native"


def test_preflight_enforces_the_model_specific_memory_tier() -> None:
    preflight = (
        Path(__file__).parents[1] / "deployment" / "roles" / "preflight" / "tasks" / "main.yml"
    ).read_text(encoding="utf-8")

    assert "open_cinema_preflight_matching_production_models" in preflight
    assert "requirement.minimum_memory_mb" in preflight
    assert "requirement.maximum_memory_mb_exclusive" in preflight


def test_development_manifest_covers_the_coordinated_boundary() -> None:
    manifest = yaml.safe_load(DEVELOPMENT_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 1
    assert manifest["status"] == "experimental"
    assert manifest["promotable"] is False
    assert manifest["platform"]["compatibility_matrix"] == load_matrix()["matrix_id"]
    assert manifest["runtime_profile"] == "full"
    assert manifest["rollback"]["strategy"] == "private-full-generation-replacement"
    assert manifest["rollback"]["previous"]["verified"] is True

    required_artifacts = {
        "open_cinema",
        "wyreplumber",
        "management_ui",
        "pcm_auto_decoder",
        "camilladsp",
    }
    assert required_artifacts <= set(manifest["components"])
    for component in required_artifacts - {"camilladsp"}:
        assert manifest["components"][component]["immutable"] is False
    assert manifest["components"]["camilladsp"]["immutable"] is True
    assert manifest["processor_requirements"] == {
        "camilladsp_instances": 1,
        "decoder_instances": 1,
    }
