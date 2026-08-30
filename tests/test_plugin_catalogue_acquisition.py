from __future__ import annotations

import hashlib
import io
import platform
import subprocess
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from api.models import PluginOperation, PluginOperationKind
from core.plugin_system.acquisition import (
    CatalogueWheelAcquirer,
    GitPluginAcquirer,
    PluginAcquisitionCancelled,
    PluginAcquisitionError,
    inspect_plugin_wheel,
    validate_git_source,
    verify_catalogue_candidate,
    verify_catalogue_wheel,
)
from core.plugin_system.catalogue import (
    CatalogueArtifact,
    FirstPartyPluginCatalogue,
    current_platform,
)
from core.plugin_system.operations import _install_catalogue_wheel
from core.plugin_system.storage import PluginInstallationRepository

pytestmark = pytest.mark.django_db


def _manifest_toml(
    *,
    plugin_id: str = "open-cinema.librespot",
    distribution: str = "open-cinema-librespot",
    version: str = "0.1.10",
) -> str:
    return f"""
schema-version = 2
permissions = []

[plugin]
id = "{plugin_id}"
distribution = "{distribution}"
display-name = "Test plugin"
description = "Acquisition fixture."
vendor = "Tests"
version = "{version}"
license = "MIT"
source-url = "https://github.com/k3rnL/open-cinema-librespot.git"
documentation-url = "https://example.test/docs"

[compatibility]
open-cinema = ">=0.3,<1"
python = ">=3.12,<4"
operating-systems = ["{platform.system().lower()}"]
architectures = ["{platform.machine().lower()}"]

[compatibility.plugin-contract]
minimum = 2
maximum = 2

[[capabilities]]
id = "{plugin_id}.api"
kind = "api"
version = 1

[lifecycle]
install = "application-restart"
enable = "hot"
disable = "hot"
update = "application-restart"
uninstall = "application-restart"
"""


def test_first_party_catalogue_publishes_verified_librespot_release() -> None:
    catalogue = FirstPartyPluginCatalogue.load()
    librespot = catalogue.get("open-cinema.librespot")

    assert librespot.verified_publisher
    assert librespot.repository.startswith("https://")
    assert librespot.latest().compatible
    assert librespot.latest().published
    assert librespot.latest().to_document()["installable"]
    assert {
        (artifact.operating_system, artifact.architecture, artifact.digest)
        for artifact in librespot.latest().artifacts
    } == {
        (
            "linux",
            "aarch64",
            "sha256:a3cb64aad42380a0640aad420f768d3074db9779c575c6d12bfbd82605745e7d",
        ),
        (
            "linux",
            "x86_64",
            "sha256:3b4afc0dc717a39e7f5e0d8cb30521239945d437da6e4005aa46805de83ad3c3",
        ),
    }


def test_catalogue_artifact_selection_normalizes_common_architecture_names() -> None:
    catalogue = FirstPartyPluginCatalogue.load().get("open-cinema.librespot")
    version = replace(
        catalogue.latest(),
        artifacts=(
            CatalogueArtifact(
                "linux",
                "aarch64",
                "https://example.test/open-cinema-librespot-aarch64.whl",
                "sha256:" + "a" * 64,
            ),
        ),
    )

    assert version.artifact_for("linux", "arm64").architecture == "aarch64"
    assert version.artifact_for("linux", "x86_64") is None


def test_catalogue_and_installed_inventory_apis_are_staff_only(client) -> None:
    catalogue_url = "/api/plugin-platform/v2/catalogue"
    anonymous = client.get(catalogue_url)
    user = get_user_model().objects.create_user(username="catalogue-user")
    client.force_login(user)
    ordinary = client.get(catalogue_url)
    staff = get_user_model().objects.create_user(username="catalogue-admin", is_staff=True)
    client.force_login(staff)
    PluginInstallationRepository.save_snapshot(
        plugin_id="open-cinema.librespot",
        distribution_id="open-cinema-librespot",
        installed_version="0.1.10",
        manifest={"id": "open-cinema.librespot"},
        provenance={"sourceType": "git", "resolvedRevision": "a" * 40},
        lifecycle_impact={"enable": "hot"},
    )
    catalogue = client.get(catalogue_url)
    installed = client.get("/api/plugin-platform/v2/installed")

    assert anonymous.status_code in {401, 403}
    assert ordinary.status_code == 403
    assert catalogue.status_code == 200
    assert catalogue.json()["items"][0]["installed"] is True
    assert installed.status_code == 200
    assert installed.json()["items"][0]["provenance"]["resolvedRevision"] == "a" * 40


@pytest.mark.parametrize(
    "url",
    (
        "http://example.test/plugin.git",
        "https://user:secret@example.test/plugin.git",
        "file:///tmp/plugin",
        "ssh://git@example.test/plugin",
        "https://example.test/plugin.git?token=secret",
    ),
)
def test_git_source_rejects_unsafe_urls(url) -> None:
    with pytest.raises(PluginAcquisitionError):
        validate_git_source(url)


def test_git_source_rejects_option_and_reflog_revision_syntax() -> None:
    with pytest.raises(PluginAcquisitionError):
        validate_git_source("https://example.test/plugin.git", "--upload-pack=bad")
    with pytest.raises(PluginAcquisitionError):
        validate_git_source("https://example.test/plugin.git", "main@{yesterday}")


class FakeGitRunner:
    commit = "a" * 40

    def __call__(self, argv, *, cwd=None, timeout):
        if argv[1] == "clone":
            checkout = Path(argv[-1])
            checkout.mkdir(parents=True)
            plugin_package = checkout / "plugin_package"
            plugin_package.mkdir()
            (plugin_package / "open-cinema-plugin.toml").write_text(_manifest_toml())
        stdout = f"{self.commit}\n" if argv[1] == "rev-parse" else ""
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


def test_git_candidate_records_resolved_provenance_and_cleans_staging(tmp_path) -> None:
    acquirer = GitPluginAcquirer(runner=FakeGitRunner(), staging_root=tmp_path)

    candidate = acquirer.acquire(
        repository_url="https://github.com/k3rnL/open-cinema-librespot.git",
        revision="main",
        trusted_code_acknowledged=True,
    )
    checkout = candidate.checkout_path
    catalogue = FirstPartyPluginCatalogue.load().get("open-cinema.librespot")
    catalogue = replace(
        catalogue,
        versions=(replace(catalogue.latest(), resolved_commit=candidate.resolved_commit),),
    )
    verify_catalogue_candidate(candidate, catalogue, expected_version="0.1.10")

    assert candidate.mutable_revision
    assert candidate.resolved_commit == "a" * 40
    assert candidate.provenance_document()["trustedCodeAcknowledged"] is True
    assert checkout.exists()
    candidate.cleanup()
    assert not checkout.exists()


def test_pinned_revision_is_classified_as_reproducible(tmp_path) -> None:
    runner = FakeGitRunner()
    candidate = GitPluginAcquirer(runner=runner, staging_root=tmp_path).acquire(
        repository_url="https://github.com/k3rnL/open-cinema-librespot.git",
        revision=runner.commit,
        trusted_code_acknowledged=True,
    )

    try:
        assert not candidate.mutable_revision
        assert candidate.requested_revision == runner.commit
    finally:
        candidate.cleanup()


def test_catalogue_version_mismatch_is_rejected(tmp_path) -> None:
    catalogue = FirstPartyPluginCatalogue.load().get("open-cinema.librespot")
    candidate = GitPluginAcquirer(
        runner=FakeGitRunner(),
        staging_root=tmp_path / "staging",
    ).acquire(
        repository_url="https://github.com/k3rnL/open-cinema-librespot.git",
        revision="main",
        trusted_code_acknowledged=True,
    )
    candidate.manifest = replace(candidate.manifest, version="0.2.0")
    try:
        with pytest.raises(PluginAcquisitionError, match="version"):
            verify_catalogue_candidate(candidate, catalogue, expected_version="0.1.10")
    finally:
        candidate.cleanup()


def test_malformed_source_repository_is_rejected_and_cleaned(tmp_path) -> None:
    class MissingManifestRunner(FakeGitRunner):
        def __call__(self, argv, *, cwd=None, timeout):
            if argv[1] == "clone":
                Path(argv[-1]).mkdir(parents=True)
            stdout = f"{self.commit}\n" if argv[1] == "rev-parse" else ""
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(PluginAcquisitionError, match="exactly one"):
        GitPluginAcquirer(
            runner=MissingManifestRunner(),
            staging_root=staging,
        ).acquire(
            repository_url="https://example.test/plugin.git",
            revision="main",
            trusted_code_acknowledged=True,
        )

    assert not tuple(staging.iterdir())


def test_git_timeout_is_reported_and_staging_is_cleaned(tmp_path) -> None:
    class TimeoutRunner:
        def __call__(self, argv, *, cwd=None, timeout):
            raise PluginAcquisitionError(f"command timed out after {timeout} seconds")

    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(PluginAcquisitionError, match="timed out"):
        GitPluginAcquirer(runner=TimeoutRunner(), staging_root=staging).acquire(
            repository_url="https://example.test/plugin.git",
            revision="main",
            trusted_code_acknowledged=True,
        )

    assert not tuple(staging.iterdir())


def test_git_acquisition_requires_trust_and_honours_cancellation(tmp_path) -> None:
    acquirer = GitPluginAcquirer(runner=FakeGitRunner(), staging_root=tmp_path)
    with pytest.raises(PluginAcquisitionError, match="trusted-code"):
        acquirer.acquire(
            repository_url="https://example.test/plugin.git",
            revision="main",
            trusted_code_acknowledged=False,
        )
    with pytest.raises(PluginAcquisitionCancelled):
        acquirer.acquire(
            repository_url="https://example.test/plugin.git",
            revision="main",
            trusted_code_acknowledged=True,
            cancelled=lambda: True,
        )


def test_built_wheel_manifest_and_digest_are_inspected_before_activation(
    tmp_path,
) -> None:
    wheel = tmp_path / "open_cinema_librespot-0.1.10-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("open_cinema_librespot/open-cinema-plugin.toml", _manifest_toml())
        archive.writestr(
            "open_cinema_librespot-0.1.10.dist-info/METADATA",
            "Metadata-Version: 2.3\nName: open-cinema-librespot\nVersion: 0.1.10\n",
        )

    inspected = inspect_plugin_wheel(wheel)

    assert inspected.manifest.plugin_id == "open-cinema.librespot"
    assert inspected.digest.startswith("sha256:")
    catalogue = FirstPartyPluginCatalogue.load().get("open-cinema.librespot")
    operating_system, architecture = current_platform()
    artifact = CatalogueArtifact(
        operating_system,
        architecture,
        "https://example.test/open-cinema-librespot.whl",
        inspected.digest,
    )
    catalogue = replace(
        catalogue,
        versions=(replace(catalogue.latest(), artifacts=(artifact,)),),
    )

    verify_catalogue_wheel(inspected, catalogue, expected_version="0.1.10")


def test_catalogue_wheel_download_is_bounded_verified_and_cleaned(tmp_path) -> None:
    wheel = tmp_path / "source.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("open_cinema_librespot/open-cinema-plugin.toml", _manifest_toml())
        archive.writestr(
            "open_cinema_librespot-0.1.10.dist-info/METADATA",
            "Metadata-Version: 2.3\nName: open-cinema-librespot\nVersion: 0.1.10\n",
        )
    wheel_bytes = wheel.read_bytes()
    digest = "sha256:" + hashlib.sha256(wheel_bytes).hexdigest()

    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(wheel_bytes))}

    acquirer = CatalogueWheelAcquirer(
        opener=lambda url, timeout: Response(wheel_bytes),
        staging_root=tmp_path / "downloads",
    )
    artifact = CatalogueArtifact(
        "linux",
        current_platform()[1],
        "https://example.test/open-cinema-librespot.whl",
        digest,
    )

    with acquirer.acquire(artifact) as candidate:
        downloaded = candidate.path
        assert candidate.inspected.manifest.plugin_id == "open-cinema.librespot"
        assert candidate.provenance_document()["artifactDigest"] == digest
        assert downloaded.exists()

    assert not downloaded.exists()


def test_catalogue_wheel_rejects_bad_digest_without_retaining_bytes(tmp_path) -> None:
    payload = b"not the pinned wheel"

    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(payload))}

    downloads = tmp_path / "downloads"
    acquirer = CatalogueWheelAcquirer(
        opener=lambda url, timeout: Response(payload),
        staging_root=downloads,
    )
    artifact = CatalogueArtifact(
        "linux",
        current_platform()[1],
        "https://example.test/open-cinema-librespot.whl",
        "sha256:" + "0" * 64,
    )

    with pytest.raises(PluginAcquisitionError, match="digest"):
        acquirer.acquire(artifact)

    assert not tuple(downloads.iterdir())


def test_catalogue_install_uses_published_wheel_without_source_build(tmp_path, monkeypatch) -> None:
    wheel = tmp_path / "open_cinema_librespot-0.1.10-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("open_cinema_librespot/open-cinema-plugin.toml", _manifest_toml())
        archive.writestr(
            "open_cinema_librespot-0.1.10.dist-info/METADATA",
            "Metadata-Version: 2.3\nName: open-cinema-librespot\nVersion: 0.1.10\n",
        )
    wheel_bytes = wheel.read_bytes()
    operating_system, architecture = current_platform()
    artifact = CatalogueArtifact(
        operating_system,
        architecture,
        "https://example.test/open-cinema-librespot.whl",
        "sha256:" + hashlib.sha256(wheel_bytes).hexdigest(),
    )
    entry = FirstPartyPluginCatalogue.load().get("open-cinema.librespot")
    entry = replace(
        entry,
        versions=(
            replace(
                entry.latest(),
                resolved_commit="a" * 40,
                published=True,
                artifacts=(artifact,),
            ),
        ),
    )

    class Catalogue:
        def get(self, plugin_id):
            return entry if plugin_id == entry.plugin_id else None

    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(wheel_bytes))}

    acquirer = CatalogueWheelAcquirer(
        opener=lambda url, timeout: Response(wheel_bytes),
        staging_root=tmp_path / "downloads",
    )
    activated = []
    monkeypatch.setattr(
        "core.plugin_system.operations.FirstPartyPluginCatalogue.load",
        lambda: Catalogue(),
    )
    monkeypatch.setattr(
        "core.plugin_system.operations.CatalogueWheelAcquirer",
        lambda **kwargs: acquirer,
    )
    monkeypatch.setattr(
        "core.plugin_system.operations._build_source_wheel",
        lambda *args, **kwargs: pytest.fail("catalogue install must not build source"),
    )
    monkeypatch.setattr(
        "core.plugin_system.operations._activate_plugin_wheel",
        lambda operation, inspected, provenance: activated.append((inspected, provenance)),
    )
    operation = PluginOperation.objects.create(
        plugin_id=entry.plugin_id,
        kind=PluginOperationKind.INSTALL,
        idempotency_key="published-wheel-install",
        requested_by=get_user_model().objects.create_user(
            username="published-wheel-admin",
            is_staff=True,
        ),
        stage_data={"sourceType": "catalogue", "version": "0.1.10"},
    )

    _install_catalogue_wheel(operation)

    assert len(activated) == 1
    inspected, provenance = activated[0]
    assert inspected.digest == artifact.digest
    assert provenance["sourceType"] == "catalogue"
    assert provenance["resolvedRevision"] == "a" * 40


def test_wheel_with_multiple_manifests_is_rejected(tmp_path) -> None:
    wheel = tmp_path / "bad-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("one/open-cinema-plugin.toml", _manifest_toml())
        archive.writestr("two/open-cinema-plugin.toml", _manifest_toml())

    with pytest.raises(PluginAcquisitionError, match="exactly one"):
        inspect_plugin_wheel(wheel)
