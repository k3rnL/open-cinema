from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parents[1]
    / "deployment"
    / "roles"
    / "react-apps"
    / "files"
    / "compare-archive-tree.py"
)
ARCHIVE_FILES = {
    "assets/application.js": b"console.log('Open Cinema');\n",
    "index.html": b"<main>Open Cinema</main>\n",
}


def write_archive(path: Path, files: dict[str, bytes] = ARCHIVE_FILES) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))


def write_installed_tree(root: Path, files: dict[str, bytes] = ARCHIVE_FILES) -> None:
    root.mkdir()
    for name, content in files.items():
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)


def compare(archive: Path, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(archive), str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_compare_archive_tree_accepts_identical_regular_files(tmp_path: Path) -> None:
    archive = tmp_path / "ui.tar.gz"
    root = tmp_path / "installed"
    write_archive(archive)
    write_installed_tree(root)

    result = compare(archive, root)

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "fileCount": len(ARCHIVE_FILES),
        "result": "identical",
    }
    assert result.stderr == ""


def remove_application(root: Path) -> None:
    (root / "assets/application.js").unlink()


def modify_index(root: Path) -> None:
    (root / "index.html").write_bytes(b"modified\n")


def add_stale_file(root: Path) -> None:
    (root / "stale.js").write_bytes(b"stale\n")


@pytest.mark.parametrize(
    ("mutate", "difference", "expected_name"),
    [
        (remove_application, "missing", "assets/application.js"),
        (modify_index, "modified", "index.html"),
        (add_stale_file, "extra", "stale.js"),
    ],
)
def test_compare_archive_tree_reports_file_differences(
    tmp_path: Path,
    mutate: Callable[[Path], None],
    difference: str,
    expected_name: str,
) -> None:
    archive = tmp_path / "ui.tar.gz"
    root = tmp_path / "installed"
    write_archive(archive)
    write_installed_tree(root)
    mutate(root)

    result = compare(archive, root)

    assert result.returncode == 10
    expected = {"extra": [], "missing": [], "modified": []}
    expected[difference] = [expected_name]
    assert json.loads(result.stderr) == expected


@pytest.mark.parametrize(
    ("member", "message"),
    [
        (tarfile.TarInfo("../../escape"), "archive contains an unsafe member path"),
        (tarfile.TarInfo("assets/link.js"), "archive contains a non-regular member"),
    ],
)
def test_compare_archive_tree_rejects_unsafe_archive_members(
    tmp_path: Path,
    member: tarfile.TarInfo,
    message: str,
) -> None:
    archive = tmp_path / "ui.tar.gz"
    root = tmp_path / "installed"
    root.mkdir()
    if member.name == "assets/link.js":
        member.type = tarfile.SYMTYPE
        member.linkname = "../index.html"
    with tarfile.open(archive, mode="w:gz") as archive_file:
        archive_file.addfile(member)

    result = compare(archive, root)

    assert result.returncode not in (0, 10)
    assert message in result.stderr


def test_compare_archive_tree_rejects_installed_symlinks(tmp_path: Path) -> None:
    archive = tmp_path / "ui.tar.gz"
    root = tmp_path / "installed"
    write_archive(archive)
    write_installed_tree(root)
    (root / "assets/link.js").symlink_to("application.js")

    result = compare(archive, root)

    assert result.returncode not in (0, 10)
    assert "installed tree contains a symbolic link" in result.stderr
