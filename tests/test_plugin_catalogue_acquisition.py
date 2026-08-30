from __future__ import annotations

import json
import platform
import subprocess
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from core.plugin_system.acquisition import (
    GitPluginAcquirer,
    PluginAcquisitionCancelled,
    PluginAcquisitionError,
    inspect_plugin_wheel,
    validate_git_source,
    verify_catalogue_candidate,
    verify_catalogue_wheel,
)
from core.plugin_system.catalogue import FirstPartyPluginCatalogue
from core.plugin_system.storage import PluginInstallationRepository

pytestmark = pytest.mark.django_db


def _manifest_toml(
    *,
    plugin_id: str = "open-cinema.librespot",
    distribution: str = "open-cinema-librespot",
    version: str = "0.1.0",
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


def test_first_party_catalogue_is_strict_and_exposes_unpublished_librespot() -> None:
    catalogue = FirstPartyPluginCatalogue.load()
    librespot = catalogue.get("open-cinema.librespot")

    assert librespot.verified_publisher
    assert librespot.repository.startswith("https://")
    assert librespot.latest().compatible
    assert not librespot.latest().published
    assert not librespot.latest().to_document()["installable"]


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
        installed_version="0.1.0",
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
    verify_catalogue_candidate(candidate, catalogue, expected_version="0.1.0")

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
            verify_catalogue_candidate(candidate, catalogue, expected_version="0.1.0")
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


def test_built_wheel_manifest_and_digest_are_inspected_before_activation(tmp_path) -> None:
    wheel = tmp_path / "open_cinema_librespot-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("open_cinema_librespot/open-cinema-plugin.toml", _manifest_toml())
        archive.writestr(
            "open_cinema_librespot-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.3\nName: open-cinema-librespot\nVersion: 0.1.0\n",
        )

    inspected = inspect_plugin_wheel(wheel)

    assert inspected.manifest.plugin_id == "open-cinema.librespot"
    assert inspected.digest.startswith("sha256:")
    verify_catalogue_wheel(
        inspected,
        FirstPartyPluginCatalogue.load().get("open-cinema.librespot"),
        expected_version="0.1.0",
    )


def test_wheel_with_multiple_manifests_is_rejected(tmp_path) -> None:
    wheel = tmp_path / "bad-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("one/open-cinema-plugin.toml", _manifest_toml())
        archive.writestr("two/open-cinema-plugin.toml", _manifest_toml())

    with pytest.raises(PluginAcquisitionError, match="exactly one"):
        inspect_plugin_wheel(wheel)
