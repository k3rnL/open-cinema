from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from collections.abc import Mapping
from typing import Any

_ORDER_INSENSITIVE_GRAPH_COLLECTIONS = {
    "parameters": "name",
    "publicPorts": "name",
    "conditions": "id",
    "nodes": "id",
    "edges": "id",
}
_ORDER_INSENSITIVE_CONTRACT_COLLECTIONS = {
    "capabilities",
    "codecs",
    "layouts",
    "rates",
    "requiredCapabilities",
    "sampleFormats",
}


def _json_sort_key(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _normalize_condition(value: object) -> object:
    if isinstance(value, list):
        return [_normalize_condition(item) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)
    normalized = {key: _normalize_condition(item) for key, item in value.items()}
    if normalized.get("op") in {"all", "any"} and isinstance(normalized.get("args"), list):
        normalized["args"] = sorted(normalized["args"], key=_json_sort_key)
    if normalized.get("op") in {"in", "not_in"} and isinstance(normalized.get("values"), list):
        normalized["values"] = sorted(normalized["values"], key=_json_sort_key)
    return normalized


def _normalize_signal_contract(contract: object) -> object:
    if not isinstance(contract, dict):
        return deepcopy(contract)
    normalized = deepcopy(contract)
    for name in _ORDER_INSENSITIVE_CONTRACT_COLLECTIONS:
        values = normalized.get(name)
        if isinstance(values, list):
            normalized[name] = sorted(values, key=_json_sort_key)
    return normalized


def normalize_graph_document(
    document: Mapping[str, object],
    *,
    include_layout: bool = True,
) -> dict[str, object]:
    """Return a detached v1 graph with every non-semantic order normalized."""

    if not isinstance(document, Mapping):
        raise TypeError("graph content must be an object")
    normalized: dict[str, Any] = deepcopy(dict(document))

    for collection, identity_field in _ORDER_INSENSITIVE_GRAPH_COLLECTIONS.items():
        values = normalized.get(collection)
        if isinstance(values, list):
            normalized[collection] = sorted(
                values,
                key=lambda item: (
                    str(item.get(identity_field, ""))
                    if isinstance(item, dict)
                    else _json_sort_key(item)
                ),
            )

    parameters = normalized.get("parameters")
    if isinstance(parameters, list):
        for parameter in parameters:
            if isinstance(parameter, dict) and isinstance(parameter.get("enum"), list):
                parameter["enum"] = sorted(parameter["enum"], key=_json_sort_key)

    public_ports = normalized.get("publicPorts")
    if isinstance(public_ports, list):
        for port in public_ports:
            if isinstance(port, dict) and "contract" in port:
                port["contract"] = _normalize_signal_contract(port["contract"])

    conditions = normalized.get("conditions")
    if isinstance(conditions, list):
        for condition in conditions:
            if isinstance(condition, dict) and "expression" in condition:
                condition["expression"] = _normalize_condition(condition["expression"])

    nodes = normalized.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, dict) and isinstance(node.get("condition"), dict):
                condition = node["condition"]
                if "expression" in condition:
                    condition["expression"] = _normalize_condition(condition["expression"])
            if not include_layout and isinstance(node, dict):
                node.pop("layout", None)

    edges = normalized.get("edges")
    if isinstance(edges, list):
        for edge in edges:
            if isinstance(edge, dict) and isinstance(edge.get("condition"), dict):
                condition = edge["condition"]
                if "expression" in condition:
                    condition["expression"] = _normalize_condition(condition["expression"])
            if not include_layout and isinstance(edge, dict):
                edge.pop("layout", None)

    if not include_layout:
        normalized.pop("layout", None)
    return normalized


def _is_desired_graph_document(document: Mapping[str, object]) -> bool:
    return all(
        field in document for field in ("schemaVersion", "kind", "nodes", "edges", "parameters")
    )


def canonical_graph_json(
    document: Mapping[str, object],
    *,
    include_layout: bool = True,
) -> str:
    """Return the stable v1 JSON representation used by revision digests."""

    if not isinstance(document, Mapping):
        raise TypeError("graph content must be an object")
    try:
        normalized = (
            normalize_graph_document(document, include_layout=include_layout)
            if _is_desired_graph_document(document)
            else dict(document)
        )
        return json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"graph content is not canonical JSON: {error}") from error


def graph_content_digest(document: Mapping[str, object]) -> str:
    return hashlib.sha256(
        canonical_graph_json(document, include_layout=False).encode("utf-8")
    ).hexdigest()
