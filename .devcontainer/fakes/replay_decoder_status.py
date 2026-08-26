#!/usr/bin/env python3
"""Replay the decoder's versioned NDJSON status fixtures over a Unix socket."""

from __future__ import annotations

import argparse
import socket
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--interval", type=float, default=0.25)
    args = parser.parse_args()
    messages = [line for line in args.fixture.read_bytes().splitlines() if line]
    args.socket.parent.mkdir(parents=True, exist_ok=True)
    args.socket.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(args.socket))
        args.socket.chmod(0o600)
        server.listen()
        while True:
            connection, _address = server.accept()
            with connection:
                for message in messages:
                    connection.sendall(message + b"\n")
                    time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
