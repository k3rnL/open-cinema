from __future__ import annotations

import argparse
import json
from pathlib import Path

from .overlay import PluginControlHelper, PluginOverlayError, PluginOverlayManager


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="open-cinema-plugin-control",
        description="Operate only server-owned Open Cinema plugin generation identifiers.",
    )
    result.add_argument("--root", required=True, help=argparse.SUPPRESS)
    result.add_argument("--retention", required=True, type=int, help=argparse.SUPPRESS)
    result.add_argument("--check", action="store_true")
    result.add_argument("action", choices=("validate", "activate", "rollback", "cleanup"))
    result.add_argument("generation_id", nargs="?")
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    manager = PluginOverlayManager(Path(arguments.root), retention=arguments.retention)
    helper = PluginControlHelper(manager)
    try:
        if arguments.check:
            if arguments.action in {"validate", "activate"}:
                if arguments.generation_id is None:
                    raise PluginOverlayError("this action requires a generation identifier")
                manager.generation_path(arguments.generation_id, staged=arguments.action == "validate")
            elif arguments.generation_id is not None:
                raise PluginOverlayError("this action does not accept a generation identifier")
            result: object = {"valid": True, "action": arguments.action}
        else:
            result = helper.execute(arguments.action, arguments.generation_id)
        print(json.dumps({"ok": True, "result": result}, default=str, sort_keys=True))
        return 0
    except (OSError, PluginOverlayError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
