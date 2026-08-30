from __future__ import annotations

import argparse
import logging
import os
import signal
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from threading import Event

logger = logging.getLogger(__name__)


def configure_django(settings_module: str) -> None:
    """Initialize Django before importing orchestration code that may use models."""

    if not isinstance(settings_module, str) or not settings_module:
        raise ValueError("settings_module must be a non-empty string")
    os.environ["DJANGO_SETTINGS_MODULE"] = settings_module
    import django

    django.setup()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="open-cinema-orchestrator",
        description="Run the dedicated Open Cinema audio orchestration process.",
    )
    parser.add_argument(
        "--settings",
        default=os.environ.get("DJANGO_SETTINGS_MODULE", "opencinema.settings"),
        help="Django settings module (default: %(default)s)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Initialize Django, run system checks, and exit without starting the service.",
    )
    return parser


@contextmanager
def _termination_event():
    stop_event = Event()
    previous_handlers = {}

    def request_stop(signum, _frame):
        logger.info("Orchestrator shutdown requested by signal %s", signum)
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, request_stop)
    try:
        yield stop_event
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def main(
    argv: Sequence[str] | None = None,
    *,
    service_factory: Callable[[], object] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    configure_django(args.settings)
    if args.check:
        from django.core.checks import run_checks

        errors = run_checks()
        if errors:
            for error in errors:
                logger.error("%s", error)
            return 1
        logger.info("Django initialized; orchestrator checks passed.")
        return 0

    if service_factory is None:
        from api.apps import initialize_plugin_runtime
        from core.orchestration.orchestrator_service import OrchestratorService

        if not initialize_plugin_runtime():
            raise RuntimeError("plugin runtime requires the migrated plugin platform schema")
        service_factory = OrchestratorService
    service = service_factory()
    run = getattr(service, "run", None)
    if not callable(run):
        raise TypeError("orchestrator service must expose run(stop_event)")
    with _termination_event() as stop_event:
        logger.info("Starting dedicated Open Cinema orchestrator process.")
        run(stop_event)
    logger.info("Open Cinema orchestrator stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
