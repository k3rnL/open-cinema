import copy

import pytest
from django.contrib.auth import get_user_model
from hypothesis import given
from hypothesis import strategies as st

from api.models import (
    GraphDefinition,
    GraphDefinitionKind,
    GraphRevision,
    GraphRevisionState,
)
from core.orchestration.parameters import ParameterValueSource
from core.orchestration.graph_documents import graph_content_digest
from core.orchestration.subgraph_expansion import expand_subgraphs
from core.orchestration.subgraphs import validate_subgraph_interface


pytestmark = pytest.mark.django_db


def _subgraph_document(*, graph_id="graph:filter", nodes=None, public_ports=None):
    return {
        "schemaVersion": 1,
        "id": graph_id,
        "kind": "subgraph",
        "metadata": {"name": graph_id},
        "parameters": [
            {"name": "gain", "type": "number", "required": True}
        ],
        "publicPorts": public_ports
        or [
            {
                "name": "input",
                "direction": "input",
                "contract": {"mediaKind": "audio", "content": "any"},
                "internalBinding": {"node": "node:adapter", "port": "input"},
            },
            {
                "name": "output",
                "direction": "output",
                "contract": {"mediaKind": "audio", "content": "any"},
                "internalBinding": {"node": "node:adapter", "port": "output"},
            },
        ],
        "conditions": [],
        "nodes": nodes
        or [
            {
                "id": "node:adapter",
                "type": "core.explicit-adapter",
                "version": 1,
                "configuration": {"targetContract": {"mediaKind": "audio"}},
            }
        ],
        "edges": [],
        "layout": {},
    }


def _instance(node_id, definition_id, revision_id, binding):
    return {
        "id": node_id,
        "type": "core.subgraph-instance",
        "version": 1,
        "configuration": {},
        "subgraph": {
            "definitionId": str(definition_id),
            "revisionId": str(revision_id),
            "parameterBindings": {"gain": binding},
            "portBindings": {"input": "input", "output": "output"},
        },
    }


def _parent_document(instances):
    nodes = [
        {
            "id": "node:source",
            "type": "core.endpoint-reference",
            "version": 1,
            "configuration": {
                "logicalEndpointId": "endpoint:tv",
                "direction": "input",
            },
        },
        *instances,
        {
            "id": "node:sink",
            "type": "core.endpoint-reference",
            "version": 1,
            "configuration": {
                "logicalEndpointId": "endpoint:speakers",
                "direction": "output",
            },
        },
    ]
    route = ["node:source", *(node["id"] for node in instances), "node:sink"]
    edges = []
    for index, (source, target) in enumerate(zip(route, route[1:])):
        edges.append(
            {
                "id": f"edge:{index}",
                "from": {
                    "node": source,
                    "port": "output" if source == "node:source" else "output",
                },
                "to": {
                    "node": target,
                    "port": "input",
                },
            }
        )
    return {
        "schemaVersion": 1,
        "id": "graph:parent",
        "kind": "graph",
        "metadata": {"name": "Parent"},
        "parameters": [
            {
                "name": "roomGain",
                "type": "number",
                "required": False,
                "default": 0.7,
            }
        ],
        "publicPorts": [],
        "conditions": [],
        "nodes": nodes,
        "edges": edges,
        "layout": {},
    }


@pytest.fixture
def reusable_filter():
    owner = get_user_model().objects.create_user(username="subgraph-expansion")
    definition = GraphDefinition.objects.create(
        name="Expansion filter",
        kind=GraphDefinitionKind.SUBGRAPH,
        owner=owner,
    )
    revision = GraphRevision.objects.create(
        definition=definition,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content=_subgraph_document(),
    )
    return definition, revision


def test_repeated_instances_expand_with_independent_names_and_parameters(
    reusable_filter,
) -> None:
    definition, revision = reusable_filter
    first = _instance(
        "node:first-filter",
        definition.pk,
        revision.pk,
        {"parameter": "roomGain"},
    )
    second = _instance(
        "node:second-filter",
        definition.pk,
        revision.pk,
        {"value": 0.25},
    )

    result = expand_subgraphs(_parent_document([first, second]))

    assert result.valid is True
    node_ids = {node["id"] for node in result.document["nodes"]}
    assert node_ids == {
        "node:source",
        "node:first-filter/node:adapter",
        "node:second-filter/node:adapter",
        "node:sink",
    }
    assert result.document["edges"][0]["to"] == {
        "node": "node:first-filter/node:adapter",
        "port": "input",
    }
    assert result.document["edges"][1]["from"] == {
        "node": "node:first-filter/node:adapter",
        "port": "output",
    }
    assert result.document["edges"][1]["to"] == {
        "node": "node:second-filter/node:adapter",
        "port": "input",
    }
    assert result.parameters["node:first-filter.gain"].value == 0.7
    assert (
        result.parameters["node:first-filter.gain"].provenance.source
        == ParameterValueSource.PARENT_PARAMETER
    )
    assert result.parameters["node:second-filter.gain"].value == 0.25
    assert (
        result.parameters["node:second-filter.gain"].provenance.source
        == ParameterValueSource.LITERAL_BINDING
    )


def test_nested_instance_public_ports_are_rewired_recursively(reusable_filter) -> None:
    inner_definition, inner_revision = reusable_filter
    owner = inner_definition.owner
    outer_definition = GraphDefinition.objects.create(
        name="Outer expansion filter",
        kind=GraphDefinitionKind.SUBGRAPH,
        owner=owner,
    )
    inner_instance = _instance(
        "node:inner",
        inner_definition.pk,
        inner_revision.pk,
        {"parameter": "gain"},
    )
    outer_document = _subgraph_document(
        graph_id="graph:outer-filter",
        nodes=[inner_instance],
        public_ports=[
            {
                "name": "input",
                "direction": "input",
                "contract": {"mediaKind": "audio"},
                "internalBinding": {"node": "node:inner", "port": "input"},
            },
            {
                "name": "output",
                "direction": "output",
                "contract": {"mediaKind": "audio"},
                "internalBinding": {"node": "node:inner", "port": "output"},
            },
        ],
    )
    outer_revision = GraphRevision.objects.create(
        definition=outer_definition,
        revision_number=1,
        state=GraphRevisionState.PUBLISHED,
        author=owner,
        content=outer_document,
    )
    assert validate_subgraph_interface(outer_document).valid is True
    outer_instance = _instance(
        "node:outer",
        outer_definition.pk,
        outer_revision.pk,
        {"value": 0.4},
    )

    result = expand_subgraphs(_parent_document([outer_instance]))

    assert result.valid is True
    assert {node["id"] for node in result.document["nodes"]} >= {
        "node:outer/node:inner/node:adapter"
    }
    assert result.document["edges"][0]["to"]["node"] == (
        "node:outer/node:inner/node:adapter"
    )
    assert result.maximum_depth == 2


def test_recursive_revision_cycle_is_rejected_with_chain() -> None:
    a = _subgraph_document(graph_id="graph:a")
    b = _subgraph_document(graph_id="graph:b")
    a["nodes"] = [_instance("node:b", "definition:b", "revision:b", {"value": 1})]
    a["publicPorts"] = []
    b["nodes"] = [_instance("node:a", "definition:a", "revision:a", {"value": 1})]
    b["publicPorts"] = []
    documents = {"revision:a": a, "revision:b": b}
    parent = _parent_document(
        [_instance("node:a", "definition:a", "revision:a", {"value": 1})]
    )

    result = expand_subgraphs(
        parent,
        loader=lambda definition_id, revision_id: copy.deepcopy(
            documents.get(revision_id)
        ),
    )

    assert result.valid is False
    cycle = next(issue for issue in result.issues if issue.code == "subgraph_cycle")
    assert "revision:a -> revision:b -> revision:a" in cycle.message


def test_configurable_depth_stops_nested_expansion() -> None:
    leaf = _subgraph_document(graph_id="graph:leaf")
    middle = _subgraph_document(graph_id="graph:middle")
    middle["nodes"] = [
        _instance("node:leaf", "definition:leaf", "revision:leaf", {"value": 1})
    ]
    middle["publicPorts"] = []
    documents = {"revision:middle": middle, "revision:leaf": leaf}
    parent = _parent_document(
        [
            _instance(
                "node:middle",
                "definition:middle",
                "revision:middle",
                {"value": 1},
            )
        ]
    )

    result = expand_subgraphs(
        parent,
        maximum_depth=1,
        loader=lambda definition_id, revision_id: copy.deepcopy(
            documents.get(revision_id)
        ),
    )

    assert result.valid is False
    assert "subgraph_depth_exceeded" in {issue.code for issue in result.issues}
    assert result.maximum_depth == 2


def test_diamond_reuse_namespaces_the_shared_leaf_per_branch() -> None:
    leaf = _subgraph_document(graph_id="graph:shared-leaf")
    branch = _subgraph_document(graph_id="graph:branch")
    branch["nodes"] = [
        _instance(
            "node:shared-leaf",
            "definition:leaf",
            "revision:leaf",
            {"parameter": "gain"},
        )
    ]
    branch["publicPorts"] = [
        {
            "name": "input",
            "direction": "input",
            "contract": {"mediaKind": "audio"},
            "internalBinding": {"node": "node:shared-leaf", "port": "input"},
        },
        {
            "name": "output",
            "direction": "output",
            "contract": {"mediaKind": "audio"},
            "internalBinding": {"node": "node:shared-leaf", "port": "output"},
        },
    ]
    documents = {"revision:leaf": leaf, "revision:branch": branch}
    left = _instance(
        "node:left",
        "definition:branch",
        "revision:branch",
        {"value": 0.2},
    )
    right = _instance(
        "node:right",
        "definition:branch",
        "revision:branch",
        {"value": 0.8},
    )

    result = expand_subgraphs(
        _parent_document([left, right]),
        loader=lambda definition_id, revision_id: copy.deepcopy(
            documents.get(revision_id)
        ),
    )

    assert result.valid is True
    node_ids = {node["id"] for node in result.document["nodes"]}
    assert {
        "node:left/node:shared-leaf/node:adapter",
        "node:right/node:shared-leaf/node:adapter",
    } <= node_ids
    assert result.parameters["node:left.gain"].value == 0.2
    assert result.parameters["node:right.gain"].value == 0.8


@given(
    first_gain=st.floats(
        min_value=0,
        max_value=1,
        allow_nan=False,
        allow_infinity=False,
    ),
    second_gain=st.floats(
        min_value=0,
        max_value=1,
        allow_nan=False,
        allow_infinity=False,
    ),
    node_order=st.permutations(range(4)),
)
def test_expansion_is_deterministic_under_declaration_order_and_independent_values(
    first_gain,
    second_gain,
    node_order,
) -> None:
    leaf = _subgraph_document()
    first = _instance(
        "node:first-filter",
        "definition:leaf",
        "revision:leaf",
        {"value": first_gain},
    )
    second = _instance(
        "node:second-filter",
        "definition:leaf",
        "revision:leaf",
        {"value": second_gain},
    )
    canonical_parent = _parent_document([first, second])
    shuffled_parent = copy.deepcopy(canonical_parent)
    shuffled_parent["nodes"] = [
        canonical_parent["nodes"][index] for index in node_order
    ]
    loader = lambda definition_id, revision_id: copy.deepcopy(leaf)

    canonical = expand_subgraphs(canonical_parent, loader=loader)
    shuffled = expand_subgraphs(shuffled_parent, loader=loader)

    assert canonical.valid is shuffled.valid is True
    assert graph_content_digest(canonical.document) == graph_content_digest(
        shuffled.document
    )
    assert canonical.parameters["node:first-filter.gain"].value == first_gain
    assert canonical.parameters["node:second-filter.gain"].value == second_gain
