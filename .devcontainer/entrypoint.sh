#!/usr/bin/env bash
set -euo pipefail

/usr/local/lib/open-cinema-dev/start-pipewire.sh

export OPEN_CINEMA_RUNTIME_REDIS_URL="${OPEN_CINEMA_RUNTIME_REDIS_URL:-redis://127.0.0.1:6379/0}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://127.0.0.1:6379/0}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://127.0.0.1:6379/0}"

exec "$@"
