from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

DESIRED_GRAPH_SCHEMA_VERSION = 1
DESIRED_GRAPH_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "desired-audio-graph-v1.schema.json"
)


@lru_cache(maxsize=1)
def desired_graph_schema() -> dict[str, object]:
    schema = json.loads(DESIRED_GRAPH_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


@lru_cache(maxsize=1)
def desired_graph_envelope_validator() -> Draft202012Validator:
    return Draft202012Validator(desired_graph_schema())
