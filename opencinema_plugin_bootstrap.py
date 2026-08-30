"""Early, dependency-free plugin overlay selection used before Django imports."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_GENERATION_PATTERN = re.compile(r"^gen-[a-z0-9][a-z0-9.-]{0,95}$")


@dataclass(frozen=True, slots=True)
class PluginBootstrapResult:
    generation_id: str | None
    overlay_path: str | None
    editable_paths: tuple[str, ...]
    recovery_mode: bool
    diagnostic: str | None


def _plugin_root() -> Path:
    configured = os.environ.get("OPEN_CINEMA_PLUGIN_ROOT")
    if configured:
        return Path(configured).resolve()
    return (Path(__file__).parent / ".plugin-data" / "plugins").resolve()


def _pointer(root: Path) -> str | None:
    pointer = root / "pointers" / "current.json"
    if not pointer.exists():
        return None
    document = json.loads(pointer.read_text(encoding="utf-8"))
    generation_id = document.get("generationId")
    if not isinstance(generation_id, str) or not _GENERATION_PATTERN.fullmatch(generation_id):
        raise ValueError("active plugin generation pointer is invalid")
    return generation_id


def activate_plugin_overlay() -> PluginBootstrapResult:
    root = _plugin_root()
    generation_id = None
    overlay = None
    diagnostic = None
    recovery = False
    try:
        generation_id = _pointer(root)
        if generation_id is not None:
            generation = (root / "generations" / generation_id).resolve()
            expected_parent = (root / "generations").resolve()
            if generation.parent != expected_parent:
                raise ValueError("active generation escapes the plugin root")
            manifest = generation / "generation.json"
            overlay_path = generation / "site-packages"
            if not manifest.is_file() or not overlay_path.is_dir():
                raise ValueError("active generation is incomplete")
            document = json.loads(manifest.read_text(encoding="utf-8"))
            if document.get("generationId") != generation_id:
                raise ValueError("active generation manifest identity does not match its pointer")
            overlay = str(overlay_path)
            if overlay not in sys.path:
                sys.path.append(overlay)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        diagnostic = str(error)
        recovery = True
        os.environ["OPEN_CINEMA_PLUGIN_RECOVERY_MODE"] = "1"
        os.environ["OPEN_CINEMA_PLUGIN_RECOVERY_DIAGNOSTIC"] = diagnostic[:2048]

    editable_paths = []
    if os.environ.get("OPEN_CINEMA_PLUGIN_ALLOW_EDITABLE") == "1":
        for raw in os.environ.get("OPEN_CINEMA_PLUGIN_EDITABLE_DIRS", "").split(os.pathsep):
            if not raw:
                continue
            path = Path(raw).resolve()
            if not path.is_dir():
                diagnostic = f"editable plugin directory does not exist: {path}"
                recovery = True
                continue
            value = str(path)
            if value not in sys.path:
                sys.path.append(value)
            editable_paths.append(value)
    return PluginBootstrapResult(
        generation_id,
        overlay,
        tuple(editable_paths),
        recovery,
        diagnostic,
    )
