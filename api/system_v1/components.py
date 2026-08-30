from __future__ import annotations

import re
import shutil
import subprocess
from importlib import metadata
from pathlib import Path

import yaml  # type: ignore[import-untyped]
from django.conf import settings

from api.models import RuntimeProjection
from core.orchestration.feature_flags import get_audio_orchestration_feature_flags

from .probes import timestamp

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_COMPONENTS = {
    "open-cinema": "open_cinema",
    "open-cinema-orchestrator": "open_cinema",
    "management-ui": "management_ui",
    "wyreplumber": "wyreplumber",
    "camilladsp": "camilladsp",
    "pcm-auto-decoder": "pcm_auto_decoder",
}
_PACKAGE_NAMES = {
    "open-cinema": "open-cinema",
    "open-cinema-orchestrator": "open-cinema",
    "wyreplumber": "wyreplumber",
}
_VERSION_COMMANDS = {
    "pipewire": ("pipewire", "--version"),
    "wireplumber": ("wireplumber", "--version"),
    "camilladsp": ("camilladsp", "--version"),
    "pcm-auto-decoder": ("pcm-auto-decoder", "--version"),
}
_DISPLAY_NAMES = {
    "open-cinema": "Open Cinema",
    "open-cinema-orchestrator": "Audio orchestrator",
    "management-ui": "Management UI",
    "wyreplumber": "WyrePlumber binding",
    "pipewire": "PipeWire",
    "wireplumber": "WirePlumber",
    "camilladsp": "CamillaDSP",
    "pcm-auto-decoder": "Adaptive PCM decoder",
}


def _manifest_paths() -> tuple[Path, ...]:
    configured = getattr(settings, "OPEN_CINEMA_RELEASE_MANIFEST", None)
    values = [Path(configured)] if configured else []
    values.extend(
        [
            Path("/etc/open-cinema/release-manifest.yml"),
            _REPOSITORY_ROOT / "deployment" / "development-manifest.yml",
        ]
    )
    return tuple(values)


def _load_manifest() -> dict[str, object]:
    for path in _manifest_paths():
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(document, dict):
            return document
    return {}


def _manifest_version(component_id: str, manifest: dict[str, object]) -> str | None:
    components = manifest.get("components")
    if not isinstance(components, dict):
        return None
    value = components.get(_MANIFEST_COMPONENTS.get(component_id, ""))
    if not isinstance(value, dict):
        return None
    version = value.get("version")
    return str(version)[:128] if version is not None else None


def _package_version(component_id: str) -> str | None:
    package = _PACKAGE_NAMES.get(component_id)
    if package is None:
        return None
    try:
        return metadata.version(package)[:128]
    except metadata.PackageNotFoundError:
        return None


def _command_version(component_id: str) -> str | None:
    command = _VERSION_COMMANDS.get(component_id)
    if command is None:
        return None
    executable = shutil.which(command[0])
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, *command[1:]],
            check=True,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = f"{result.stdout}\n{result.stderr}"[:1024]
    match = re.search(r"(?<![0-9])v?([0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?)", output)
    return match.group(1)[:128] if match else None


def _version(component_id: str, manifest: dict[str, object]) -> tuple[str | None, str]:
    for source, value in (
        ("release-manifest", _manifest_version(component_id, manifest)),
        ("python-package", _package_version(component_id)),
        ("fixed-version-probe", _command_version(component_id)),
    ):
        if value:
            return value, source
    return None, "unknown"


def readiness_document() -> dict[str, object]:
    flags = get_audio_orchestration_feature_flags()
    health = RuntimeProjection.objects.filter(
        is_current=True,
        projection_type__in=("health", "orchestration-health"),
    ).first()
    runtime = RuntimeProjection.objects.filter(is_current=True).first()
    blockers = list(flags.live_control_blockers)
    runtime_ready = runtime is not None and (health is None or bool(health.payload.get("ready")))
    if not runtime_ready:
        blockers.append("runtime_unavailable")
    blockers = list(dict.fromkeys(blockers))
    return {
        "ready": not blockers,
        "status": "ready" if not blockers else "degraded",
        "blockers": blockers,
    }


def _health_documents() -> tuple[dict[str, object] | None, list[dict[str, object]], bool]:
    orchestration = RuntimeProjection.objects.filter(
        is_current=True,
        projection_type__in=("health", "orchestration-health"),
    ).first()
    processors = list(
        RuntimeProjection.objects.filter(
            is_current=True,
            projection_type__in=("processor", "processor-health"),
        ).values_list("payload", flat=True)
    )
    runtime_available = RuntimeProjection.objects.filter(is_current=True).exists()
    return orchestration.payload if orchestration else None, processors, runtime_available


def _processor_health(processors: list[dict[str, object]], needle: str) -> str:
    matches = [
        item
        for item in processors
        if needle in str(item.get("nodeType", "")).lower()
        or needle in str(item.get("kind", "")).lower()
        or needle in str(item.get("processorKind", "")).lower()
    ]
    if not matches:
        return "unknown"
    return "ready" if all(item.get("ready") is True for item in matches) else "degraded"


def component_documents() -> list[dict[str, object]]:
    # Imported lazily so the read-only probe module remains usable during early
    # Django startup and migrations, before the control-operation model exists.
    from .control import component_action_documents

    observed_at = timestamp()
    manifest = _load_manifest()
    orchestration, processors, runtime_available = _health_documents()
    health = {
        "open-cinema": "ready",
        "open-cinema-orchestrator": (
            "ready" if orchestration and orchestration.get("ready") is True else "degraded"
        ),
        "management-ui": "ready",
        "wyreplumber": "ready" if runtime_available else "unknown",
        "pipewire": "ready" if runtime_available else "unknown",
        "wireplumber": "ready" if runtime_available else "unknown",
        "camilladsp": _processor_health(processors, "camilla"),
        "pcm-auto-decoder": _processor_health(processors, "decoder"),
    }
    documents: list[dict[str, object]] = []
    for component_id, name in _DISPLAY_NAMES.items():
        version, version_source = _version(component_id, manifest)
        documents.append(
            {
                "id": component_id,
                "name": name,
                "version": version,
                "versionStatus": "known" if version else "unknown",
                "versionSource": version_source,
                "health": health[component_id],
                "observedAt": observed_at,
                "actions": component_action_documents(component_id),
            }
        )
    return documents
