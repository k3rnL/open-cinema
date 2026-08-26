#!/usr/bin/env python3
"""Write portable provenance for one set of release assets."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", default="open-cinema")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--workflow-run", required=True)
    args = parser.parse_args()

    artifacts = []
    for path in sorted(args.dist_dir.iterdir()):
        if path == args.output or not path.is_file():
            continue
        if not (path.name.endswith(".whl") or path.name.endswith(".tar.gz")):
            continue
        artifacts.append(
            {
                "name": path.name,
                "sha256": sha256(path),
                "sizeBytes": path.stat().st_size,
            }
        )

    if not artifacts:
        raise SystemExit("no wheel or source archive found for provenance")

    document = {
        "schemaVersion": 1,
        "project": args.project,
        "repository": args.repository,
        "commit": args.commit,
        "tag": args.tag,
        "workflowRun": args.workflow_run,
        "artifacts": artifacts,
    }
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
