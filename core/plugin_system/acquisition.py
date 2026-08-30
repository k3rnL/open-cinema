from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from io import BufferedIOBase
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .catalogue import CatalogueArtifact, FirstPartyPlugin
from .manifest import parse_plugin_manifest
from .v2_contracts import PLUGIN_MANIFEST_FILENAME, PluginDistributionManifest

GIT_OPERATION_TIMEOUT_SECONDS = 120
PLUGIN_SOURCE_MAX_FILES = 10_000
PLUGIN_SOURCE_MAX_BYTES = 256 * 1024 * 1024
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_REVISION_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,256}$")
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class PluginAcquisitionError(ValueError):
    pass


class PluginAcquisitionCancelled(PluginAcquisitionError):
    pass


def validate_catalogue_artifact_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise PluginAcquisitionError("catalogue artifact URL is required")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith(".whl")
    ):
        raise PluginAcquisitionError(
            "catalogue artifacts must use a credential-free HTTPS wheel URL"
        )
    return url


def validate_git_source(
    repository_url: str, revision: str | None = None
) -> tuple[str, str]:
    if not isinstance(repository_url, str) or len(repository_url) > 2048:
        raise PluginAcquisitionError(
            "repository URL is required and cannot exceed 2048 characters"
        )
    parsed = urlparse(repository_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise PluginAcquisitionError(
            "plugin repositories must use a credential-free HTTPS URL without query or fragment"
        )
    revision = revision or "HEAD"
    if (
        not _REVISION_PATTERN.fullmatch(revision)
        or revision.startswith(("-", "/"))
        or ".." in revision
        or "@{" in revision
    ):
        raise PluginAcquisitionError(
            "revision contains unsupported characters or syntax"
        )
    return repository_url, revision


def _run(
    argv: list[str], *, cwd: Path | None = None, timeout: int
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise PluginAcquisitionError(
            f"command timed out after {timeout} seconds"
        ) from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error))[-4096:]
        raise PluginAcquisitionError(detail) from error


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise PluginAcquisitionCancelled("plugin acquisition was cancelled")


def _bounded_tree(root: Path) -> None:
    files = 0
    size = 0
    for path in root.rglob("*"):
        if ".git" in path.parts:
            continue
        files += 1
        if files > PLUGIN_SOURCE_MAX_FILES:
            raise PluginAcquisitionError("plugin source contains too many files")
        if path.is_symlink():
            target = path.resolve()
            if root.resolve() not in (target, *target.parents):
                raise PluginAcquisitionError(
                    "plugin source contains an escaping symbolic link"
                )
        if path.is_file():
            size += path.stat().st_size
            if size > PLUGIN_SOURCE_MAX_BYTES:
                raise PluginAcquisitionError("plugin source exceeds the size limit")


def _source_manifest(root: Path) -> PluginDistributionManifest:
    candidates = [
        path
        for path in root.rglob(PLUGIN_MANIFEST_FILENAME)
        if ".git" not in path.parts
    ]
    if len(candidates) != 1:
        raise PluginAcquisitionError(
            f"plugin source must contain exactly one {PLUGIN_MANIFEST_FILENAME}"
        )
    return parse_plugin_manifest(candidates[0].read_bytes())


@dataclass(slots=True)
class AcquiredPluginSource:
    repository_url: str
    requested_revision: str
    resolved_commit: str
    mutable_revision: bool
    checkout_path: Path
    manifest: PluginDistributionManifest
    trusted_code_acknowledged: bool
    _temporary_root: Path

    def provenance_document(self) -> dict[str, object]:
        return {
            "sourceType": "git",
            "sourceUrl": self.repository_url,
            "requestedRevision": self.requested_revision,
            "resolvedRevision": self.resolved_commit,
            "mutableRevision": self.mutable_revision,
            "trustedCodeAcknowledged": self.trusted_code_acknowledged,
        }

    def cleanup(self) -> None:
        if self._temporary_root.exists():
            shutil.rmtree(self._temporary_root)

    def __enter__(self) -> AcquiredPluginSource:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.cleanup()


class GitPluginAcquirer:
    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess] = _run,
        staging_root: Path | None = None,
    ) -> None:
        self.runner = runner
        self.staging_root = staging_root

    def acquire(
        self,
        *,
        repository_url: str,
        revision: str | None,
        trusted_code_acknowledged: bool,
        cancelled: Callable[[], bool] | None = None,
    ) -> AcquiredPluginSource:
        repository_url, revision = validate_git_source(repository_url, revision)
        if not trusted_code_acknowledged:
            raise PluginAcquisitionError(
                "explicit trusted-code acknowledgement is required before source acquisition"
            )
        _check_cancelled(cancelled)
        if self.staging_root is not None:
            self.staging_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary_root = Path(
            tempfile.mkdtemp(prefix="open-cinema-plugin-", dir=self.staging_root)
        )
        checkout = temporary_root / "checkout"
        try:
            self.runner(
                [
                    "git",
                    "clone",
                    "--filter=blob:none",
                    "--no-checkout",
                    "--depth=1",
                    repository_url,
                    str(checkout),
                ],
                timeout=GIT_OPERATION_TIMEOUT_SECONDS,
            )
            _check_cancelled(cancelled)
            self.runner(
                ["git", "fetch", "--depth=1", "origin", revision],
                cwd=checkout,
                timeout=GIT_OPERATION_TIMEOUT_SECONDS,
            )
            resolved = self.runner(
                ["git", "rev-parse", "--verify", "FETCH_HEAD^{commit}"],
                cwd=checkout,
                timeout=GIT_OPERATION_TIMEOUT_SECONDS,
            ).stdout.strip()
            if not _COMMIT_PATTERN.fullmatch(resolved):
                raise PluginAcquisitionError("Git did not resolve an immutable commit")
            self.runner(
                ["git", "checkout", "--detach", resolved],
                cwd=checkout,
                timeout=GIT_OPERATION_TIMEOUT_SECONDS,
            )
            _check_cancelled(cancelled)
            _bounded_tree(checkout)
            manifest = _source_manifest(checkout)
            return AcquiredPluginSource(
                repository_url,
                revision,
                resolved,
                not bool(_COMMIT_PATTERN.fullmatch(revision)),
                checkout,
                manifest,
                trusted_code_acknowledged,
                temporary_root,
            )
        except Exception:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise


@dataclass(slots=True)
class AcquiredCatalogueWheel:
    artifact: CatalogueArtifact
    inspected: InspectedPluginWheel
    _temporary_root: Path

    @property
    def path(self) -> Path:
        return self.inspected.path

    def provenance_document(self) -> dict[str, object]:
        return {
            "sourceType": "catalogue",
            "sourceUrl": self.artifact.url,
            "artifactDigest": self.inspected.digest,
            "operatingSystem": self.artifact.operating_system,
            "architecture": self.artifact.architecture,
            "mutableRevision": False,
        }

    def cleanup(self) -> None:
        shutil.rmtree(self._temporary_root, ignore_errors=True)

    def __enter__(self) -> AcquiredCatalogueWheel:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.cleanup()


def _open_catalogue_artifact(url: str, timeout: int):
    request = Request(url, headers={"User-Agent": "Open-Cinema-plugin-catalogue/1"})
    return urlopen(request, timeout=timeout)


class CatalogueWheelAcquirer:
    def __init__(
        self,
        *,
        opener: Callable[[str, int], BufferedIOBase] = _open_catalogue_artifact,
        staging_root: Path | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.opener = opener
        self.staging_root = staging_root
        self.timeout_seconds = timeout_seconds

    def acquire(
        self,
        artifact: CatalogueArtifact,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> AcquiredCatalogueWheel:
        validate_catalogue_artifact_url(artifact.url)
        if not _DIGEST_PATTERN.fullmatch(artifact.digest):
            raise PluginAcquisitionError("catalogue artifact digest is invalid")
        _check_cancelled(cancelled)
        if self.staging_root is not None:
            self.staging_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary_root = Path(
            tempfile.mkdtemp(prefix="open-cinema-plugin-wheel-", dir=self.staging_root)
        )
        wheel = temporary_root / PurePosixPath(urlparse(artifact.url).path).name
        try:
            digest = hashlib.sha256()
            size = 0
            with self.opener(artifact.url, self.timeout_seconds) as response:
                content_length = getattr(response, "headers", {}).get("Content-Length")
                if (
                    content_length is not None
                    and int(content_length) > PLUGIN_SOURCE_MAX_BYTES
                ):
                    raise PluginAcquisitionError(
                        "catalogue artifact exceeds the size limit"
                    )
                with wheel.open("wb") as stream:
                    while chunk := response.read(1024 * 1024):
                        _check_cancelled(cancelled)
                        size += len(chunk)
                        if size > PLUGIN_SOURCE_MAX_BYTES:
                            raise PluginAcquisitionError(
                                "catalogue artifact exceeds the size limit"
                            )
                        digest.update(chunk)
                        stream.write(chunk)
            actual_digest = "sha256:" + digest.hexdigest()
            if actual_digest != artifact.digest:
                raise PluginAcquisitionError(
                    "downloaded artifact digest differs from the pinned catalogue digest"
                )
            inspected = inspect_plugin_wheel(wheel)
            return AcquiredCatalogueWheel(artifact, inspected, temporary_root)
        except PluginAcquisitionError:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise
        except Exception as error:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise PluginAcquisitionError(
                f"catalogue artifact download failed: {error}"
            ) from error


def verify_catalogue_candidate(
    candidate: AcquiredPluginSource,
    catalogue: FirstPartyPlugin,
    *,
    expected_version: str,
) -> None:
    version = next(
        (item for item in catalogue.versions if item.version == expected_version), None
    )
    if version is None:
        raise PluginAcquisitionError("candidate version is absent from the catalogue")
    if candidate.manifest.plugin_id != catalogue.plugin_id:
        raise PluginAcquisitionError(
            "downloaded manifest plugin ID differs from the catalogue"
        )
    if candidate.manifest.version != expected_version:
        raise PluginAcquisitionError(
            "downloaded manifest version differs from the catalogue"
        )
    if candidate.repository_url.rstrip("/") != catalogue.repository.rstrip("/"):
        raise PluginAcquisitionError("downloaded repository differs from the catalogue")
    if (
        version.resolved_commit is not None
        and candidate.resolved_commit != version.resolved_commit
    ):
        raise PluginAcquisitionError(
            "resolved commit differs from the pinned catalogue commit"
        )


def verify_catalogue_wheel(
    candidate: InspectedPluginWheel,
    catalogue: FirstPartyPlugin,
    *,
    expected_version: str,
    expected_artifact: CatalogueArtifact | None = None,
) -> None:
    version = next(
        (item for item in catalogue.versions if item.version == expected_version),
        None,
    )
    if version is None:
        raise PluginAcquisitionError("candidate version is absent from the catalogue")
    if candidate.manifest.plugin_id != catalogue.plugin_id:
        raise PluginAcquisitionError(
            "built artifact plugin ID differs from the catalogue"
        )
    if candidate.manifest.version != expected_version:
        raise PluginAcquisitionError(
            "built artifact version differs from the catalogue"
        )
    artifact = expected_artifact or version.artifact_for()
    if artifact is None:
        raise PluginAcquisitionError("catalogue has no artifact for this platform")
    if candidate.digest != artifact.digest:
        raise PluginAcquisitionError(
            "built artifact digest differs from the pinned catalogue digest"
        )


@dataclass(frozen=True, slots=True)
class InspectedPluginWheel:
    path: Path
    digest: str
    manifest: PluginDistributionManifest


def inspect_plugin_wheel(path: Path) -> InspectedPluginWheel:
    path = Path(path)
    if not path.is_file() or path.suffix != ".whl":
        raise PluginAcquisitionError("candidate artifact must be a wheel")
    if path.stat().st_size > PLUGIN_SOURCE_MAX_BYTES:
        raise PluginAcquisitionError("candidate wheel exceeds the size limit")
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > PLUGIN_SOURCE_MAX_FILES:
                raise PluginAcquisitionError("candidate wheel contains too many files")
            if sum(item.file_size for item in members) > PLUGIN_SOURCE_MAX_BYTES:
                raise PluginAcquisitionError(
                    "expanded candidate wheel exceeds the size limit"
                )
            for member in members:
                member_path = PurePosixPath(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise PluginAcquisitionError(
                        "candidate wheel contains an unsafe path"
                    )
            manifests = [
                item
                for item in members
                if PurePosixPath(item.filename).name == PLUGIN_MANIFEST_FILENAME
            ]
            if len(manifests) != 1:
                raise PluginAcquisitionError(
                    f"candidate wheel must contain exactly one {PLUGIN_MANIFEST_FILENAME}"
                )
            manifest = parse_plugin_manifest(archive.read(manifests[0]))
    except zipfile.BadZipFile as error:
        raise PluginAcquisitionError("candidate wheel is malformed") from error
    return InspectedPluginWheel(path, digest, manifest)
