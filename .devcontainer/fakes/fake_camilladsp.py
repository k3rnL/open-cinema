#!/usr/bin/env python3
"""Tiny TCP availability fake; unit tests provide the full Camilla protocol fake."""

from __future__ import annotations

import argparse
import signal
import socket


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1234)
    args = parser.parse_args()
    if args.version:
        print("camilladsp 3.0.1-dev-fake")
        return 0

    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    with socket.create_server((args.host, args.port), reuse_port=True) as server:
        server.settimeout(0.25)
        while not stopped:
            try:
                connection, _address = server.accept()
            except TimeoutError:
                continue
            connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
