from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from email.parser import Parser
from importlib import metadata
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import Version

from .acquisition import InspectedPluginWheel, inspect_plugin_wheel
from .overlay_validation import RESULT_PREFIX

_GENERATION_PATTERN = re.compile(r"^gen-[a-z0-9][a-z0-9.-]{0,95}$")
GENERATION_MANIFEST_VERSION = 1
GENERATION_RETENTION_DEFAULT = 3


class PluginOverlayError(ValueError):
    pass


def validate_generation_id(generation_id: str) -> str:
    if not isinstance(generation_id, str) or not _GENERATION_PATTERN.fullmatch(generation_id):
        raise PluginOverlayError("invalid plugin generation identifier")
    return generation_id


def _json_write_atomic(path: Path, document: dict[str, object], *, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class PluginGenerationManifest:
    generation_id: str
    created_at: str
    core_environment: dict[str, object]
    artifacts: tuple[dict[str, object], ...]
    resolved_distributions: tuple[dict[str, str], ...]
    plugins: tuple[dict[str, object], ...]
    previous_generation: str | None = None

    def __post_init__(self) -> None:
        validate_generation_id(self.generation_id)

    def to_document(self) -> dict[str, object]:
        return {
            "schemaVersion": GENERATION_MANIFEST_VERSION,
            "generationId": self.generation_id,
            "createdAt": self.created_at,
            "previousGeneration": self.previous_generation,
            "coreEnvironment": self.core_environment,
            "artifacts": list(self.artifacts),
            "resolvedDistributions": list(self.resolved_distributions),
            "plugins": list(self.plugins),
        }


class PluginOverlayManager:
    def __init__(self, root: Path, *, retention: int = GENERATION_RETENTION_DEFAULT) -> None:
        self.root = Path(root).resolve()
        if (
            isinstance(retention, bool)
            or not isinstance(retention, int)
            or not 1 <= retention <= 20
        ):
            raise PluginOverlayError("retention must be between 1 and 20")
        self.retention = retention
        self.generations = self.root / "generations"
        self.staging = self.root / "staging"
        self.pointers = self.root / "pointers"

    def ensure_layout(self) -> None:
        for path in (self.root, self.generations, self.staging, self.pointers):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(path, 0o700)

    def generation_path(self, generation_id: str, *, staged: bool = False) -> Path:
        generation_id = validate_generation_id(generation_id)
        parent = self.staging if staged else self.generations
        path = (parent / generation_id).resolve()
        if path.parent != parent.resolve():
            raise PluginOverlayError("generation path escapes its server-owned directory")
        return path

    def create_staging(self, generation_id: str) -> Path:
        self.ensure_layout()
        path = self.generation_path(generation_id, staged=True)
        if path.exists() or self.generation_path(generation_id).exists():
            raise PluginOverlayError("generation identifier already exists")
        (path / "site-packages").mkdir(mode=0o700, parents=True)
        (path / "artifacts").mkdir(mode=0o700)
        return path

    def pointer(self, name: str) -> str | None:
        if name not in {"current", "last-known-good"}:
            raise PluginOverlayError("unsupported generation pointer")
        path = self.pointers / f"{name}.json"
        if not path.exists():
            return None
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            return validate_generation_id(document["generationId"])
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
            raise PluginOverlayError(f"{name} generation pointer is invalid") from error

    def write_manifest(self, generation_id: str, manifest: PluginGenerationManifest) -> Path:
        if manifest.generation_id != generation_id:
            raise PluginOverlayError("generation manifest belongs to another generation")
        path = self.generation_path(generation_id, staged=True) / "generation.json"
        _json_write_atomic(path, manifest.to_document())
        return path

    def validate(self, generation_id: str, *, staged: bool = False) -> dict[str, object]:
        path = self.generation_path(generation_id, staged=staged)
        manifest_path = path / "generation.json"
        site_packages = path / "site-packages"
        if not path.is_dir() or not manifest_path.is_file() or not site_packages.is_dir():
            raise PluginOverlayError("generation is incomplete")
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PluginOverlayError("generation manifest is malformed") from error
        if document.get("schemaVersion") != 1 or document.get("generationId") != generation_id:
            raise PluginOverlayError("generation manifest identity or schema is invalid")
        for item in path.rglob("*"):
            if item.is_symlink():
                resolved = item.resolve()
                if path not in (resolved, *resolved.parents):
                    raise PluginOverlayError("generation contains an escaping symbolic link")
        return document

    def validate_contracts(
        self,
        generation_id: str,
        *,
        staged: bool = False,
    ) -> dict[str, object]:
        document = self.validate(generation_id, staged=staged)
        path = self.generation_path(generation_id, staged=staged)
        site_packages = path / "site-packages"
        expected = {str(item["id"]): str(item["version"]) for item in document.get("plugins", ())}
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "core.plugin_system.overlay_validation",
                    str(site_packages),
                    json.dumps(expected, separators=(",", ":")),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as error:
            raise PluginOverlayError("generation contract validation timed out") from error
        result_line = next(
            (
                line.removeprefix(RESULT_PREFIX)
                for line in reversed(completed.stdout.splitlines())
                if line.startswith(RESULT_PREFIX)
            ),
            None,
        )
        if result_line is None:
            raise PluginOverlayError("generation contract validator returned no structured result")
        try:
            result = json.loads(result_line)
        except json.JSONDecodeError as error:
            raise PluginOverlayError(
                "generation contract validator returned malformed output"
            ) from error
        if completed.returncode != 0 or result.get("valid") is not True:
            details = result.get("diagnostics") or result.get("unhealthy") or []
            raise PluginOverlayError(
                "generation contract validation failed: "
                + json.dumps(details, ensure_ascii=False)[:2048]
            )
        return {
            **document,
            "validatedRegistry": result["registry"],
        }

    def activate(self, generation_id: str) -> str | None:
        self.ensure_layout()
        staged = self.generation_path(generation_id, staged=True)
        self.validate_contracts(generation_id, staged=True)
        active = self.generation_path(generation_id)
        if active.exists():
            raise PluginOverlayError("active generation already exists")
        previous = self.pointer("current")
        os.replace(staged, active)
        if previous is not None:
            _json_write_atomic(self.pointers / "last-known-good.json", {"generationId": previous})
        _json_write_atomic(self.pointers / "current.json", {"generationId": generation_id})
        return previous

    def rollback(self) -> tuple[str, str]:
        current = self.pointer("current")
        previous = self.pointer("last-known-good")
        if current is None or previous is None:
            raise PluginOverlayError("rollback pointers are unavailable")
        self.validate(previous)
        _json_write_atomic(self.pointers / "current.json", {"generationId": previous})
        _json_write_atomic(self.pointers / "last-known-good.json", {"generationId": current})
        return current, previous

    def cleanup(self) -> tuple[str, ...]:
        protected = {
            item for item in (self.pointer("current"), self.pointer("last-known-good")) if item
        }
        generations = sorted(
            (
                path
                for path in self.generations.iterdir()
                if path.is_dir() and _GENERATION_PATTERN.fullmatch(path.name)
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        keep = protected | {path.name for path in generations[: self.retention]}
        removed = []
        for path in generations:
            if path.name in keep:
                continue
            shutil.rmtree(path)
            removed.append(path.name)
        return tuple(removed)


def export_core_constraints(
    path: Path,
    *,
    excluded_root: Path | None = None,
    excluded_distributions: frozenset[str] = frozenset(),
) -> dict[str, str]:
    excluded = excluded_root.resolve() if excluded_root is not None else None
    excluded_names = {name.lower().replace("_", "-") for name in excluded_distributions}
    distributions = {
        distribution.metadata["Name"].lower().replace("_", "-"): distribution.version
        for distribution in metadata.distributions()
        if distribution.metadata.get("Name")
        and distribution.metadata["Name"].lower().replace("_", "-") not in excluded_names
        and (
            excluded is None or excluded not in Path(distribution.locate_file("")).resolve().parents
        )
    }
    lines = [f"{name}=={version}" for name, version in sorted(distributions.items())]
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return distributions


def _wheel_requirements(path: Path) -> tuple[Requirement, ...]:
    import zipfile

    with zipfile.ZipFile(path) as archive:
        metadata_names = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise PluginOverlayError("wheel must contain exactly one METADATA file")
        message = Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
    requirements = []
    for value in message.get_all("Requires-Dist", ()):
        try:
            requirements.append(Requirement(value))
        except InvalidRequirement as error:
            raise PluginOverlayError(f"wheel contains an invalid requirement: {value}") from error
    return tuple(requirements)


def reject_core_dependency_conflicts(
    wheels: tuple[Path, ...], core_distributions: dict[str, str]
) -> None:
    conflicts = []
    for wheel in wheels:
        for requirement in _wheel_requirements(wheel):
            name = requirement.name.lower().replace("_", "-")
            installed = core_distributions.get(name)
            if (
                installed is None
                or requirement.marker is not None
                and not requirement.marker.evaluate()
            ):
                continue
            if requirement.specifier and Version(installed) not in requirement.specifier:
                conflicts.append(f"{requirement} conflicts with core {name}=={installed}")
    if conflicts:
        raise PluginOverlayError("; ".join(conflicts))


class PluginGenerationBuilder:
    def __init__(
        self,
        manager: PluginOverlayManager,
        *,
        runner=subprocess.run,
        max_generation_bytes: int = 1024 * 1024 * 1024,
    ) -> None:
        if (
            isinstance(max_generation_bytes, bool)
            or not isinstance(max_generation_bytes, int)
            or not 1024 * 1024 <= max_generation_bytes <= 10 * 1024 * 1024 * 1024
        ):
            raise PluginOverlayError("generation size limit must be between 1 MiB and 10 GiB")
        self.manager = manager
        self.runner = runner
        self.max_generation_bytes = max_generation_bytes

    def build(
        self,
        *,
        generation_id: str,
        wheels: tuple[Path, ...],
        created_at: str,
        previous_generation: str | None,
    ) -> PluginGenerationManifest:
        staging = self.manager.create_staging(generation_id)
        try:
            inspected: tuple[InspectedPluginWheel, ...] = tuple(
                inspect_plugin_wheel(Path(item)) for item in wheels
            )
            constraints_path = staging / "core-constraints.txt"
            core = export_core_constraints(
                constraints_path,
                excluded_root=self.manager.root,
                excluded_distributions=frozenset(
                    item.manifest.distribution_id for item in inspected
                ),
            )
            reject_core_dependency_conflicts(tuple(item.path for item in inspected), core)
            artifact_documents = []
            installed_wheels = []
            for item in inspected:
                target = staging / "artifacts" / item.path.name
                shutil.copy2(item.path, target)
                installed_wheels.append(target)
                artifact_documents.append(
                    {"filename": target.name, "digest": item.digest, "size": target.stat().st_size}
                )
            if installed_wheels:
                command = [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    sys.executable,
                    "--target",
                    str(staging / "site-packages"),
                    "--constraint",
                    str(constraints_path),
                    *[str(path) for path in installed_wheels],
                ]
                completed = self.runner(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                build_log = (completed.stdout or "") + (completed.stderr or "")
            else:
                build_log = "No overlay plugins are installed in this generation."
            (staging / "build.log").write_text(build_log[-64 * 1024 :], encoding="utf-8")
            generation_size = sum(
                item.stat().st_size
                for item in staging.rglob("*")
                if item.is_file() and not item.is_symlink()
            )
            if generation_size > self.max_generation_bytes:
                raise PluginOverlayError(
                    f"plugin generation exceeds its {self.max_generation_bytes}-byte storage limit"
                )
            resolved = tuple(
                sorted(
                    (
                        {"name": item.metadata["Name"], "version": item.version}
                        for item in metadata.distributions(path=[str(staging / "site-packages")])
                        if item.metadata.get("Name")
                    ),
                    key=lambda item: item["name"].lower(),
                )
            )
            manifest = PluginGenerationManifest(
                generation_id,
                created_at,
                {
                    "python": sys.version.split()[0],
                    "executable": sys.executable,
                    "platform": sys.platform,
                    "implementation": sys.implementation.name,
                    "constraintsDigest": "sha256:"
                    + hashlib.sha256(constraints_path.read_bytes()).hexdigest(),
                    "installerOutput": build_log[-4096:],
                    "generationBytes": generation_size,
                },
                tuple(artifact_documents),
                resolved,
                tuple(item.manifest.to_document() for item in inspected),
                previous_generation,
            )
            self.manager.write_manifest(generation_id, manifest)
            self.manager.validate_contracts(generation_id, staged=True)
            return manifest
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise


class PluginControlHelper:
    """Allowlisted generation operations; accepts identifiers, never caller-owned paths."""

    def __init__(self, manager: PluginOverlayManager) -> None:
        self.manager = manager

    def execute(self, action: str, generation_id: str | None = None):
        if action == "validate" and generation_id is not None:
            return self.manager.validate(validate_generation_id(generation_id), staged=True)
        if action == "activate" and generation_id is not None:
            return self.manager.activate(validate_generation_id(generation_id))
        if action == "rollback" and generation_id is None:
            return self.manager.rollback()
        if action == "cleanup" and generation_id is None:
            return self.manager.cleanup()
        raise PluginOverlayError("unsupported plugin-control action or arguments")
