from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from open_cinema_plugin_sdk import (
    ApiCapability,
    OpenCinemaPlugin,
    RuntimePluginIdentity,
    assert_plugin_contract,
    validate_source_checkout,
)


MANIFEST = """
schema-version = 2
permissions = []
[plugin]
id = "example.test"
distribution = "open-cinema-example"
display-name = "SDK example"
description = "External contract fixture."
vendor = "Tests"
version = "1.0.0"
license = "MIT"
source-url = "https://example.test/source"
documentation-url = "https://example.test/docs"
[compatibility]
open-cinema = ">=0.3,<1"
python = ">=3.12,<4"
operating-systems = ["linux", "darwin"]
architectures = ["x86_64", "aarch64", "arm64"]
[compatibility.plugin-contract]
minimum = 2
maximum = 2
[[capabilities]]
id = "example.test.api"
kind = "api"
version = 1
[lifecycle]
install = "application-restart"
enable = "hot"
disable = "hot"
update = "application-restart"
uninstall = "application-restart"
"""


class ExamplePlugin(OpenCinemaPlugin):
    @property
    def identity(self):
        return RuntimePluginIdentity("example.test", "open-cinema-example", "1.0.0")

    def capabilities(self):
        return (ApiCapability("example.test.api", routes=lambda: ()),)


def source_checkout(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "open-cinema-example"
version = "1.0.0"
[project.entry-points."open_cinema.plugins"]
example = "example_plugin:ExamplePlugin"
""",
        encoding="utf-8",
    )
    package = tmp_path / "src" / "example_plugin"
    package.mkdir(parents=True)
    (package / "open-cinema-plugin.toml").write_text(MANIFEST, encoding="utf-8")
    return tmp_path


def built_wheel(tmp_path: Path) -> Path:
    wheel = tmp_path / "open_cinema_example-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("example_plugin/open-cinema-plugin.toml", MANIFEST)
        archive.writestr(
            "open_cinema_example-1.0.0.dist-info/METADATA",
            "Metadata-Version: 2.3\nName: open-cinema-example\nVersion: 1.0.0\n",
        )
        archive.writestr(
            "open_cinema_example-1.0.0.dist-info/entry_points.txt",
            "[open_cinema.plugins]\nexample = example_plugin:ExamplePlugin\n",
        )
        archive.writestr(
            "open_cinema_example-1.0.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
    return wheel


def test_public_contract_suite_validates_source_wheel_and_runtime(tmp_path) -> None:
    source = source_checkout(tmp_path / "source")
    wheel = built_wheel(tmp_path)

    report = assert_plugin_contract(source, wheel=wheel, plugin=ExamplePlugin())

    assert report.plugin_id == "example.test"
    assert report.capability_ids == ("example.test.api",)
    assert report.source_validated and report.wheel_validated and report.runtime_validated


def test_public_contract_suite_rejects_distribution_identity_mismatch(tmp_path) -> None:
    source = source_checkout(tmp_path)
    pyproject = source / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace("open-cinema-example", "wrong-name"),
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match="distribution name"):
        validate_source_checkout(source)
